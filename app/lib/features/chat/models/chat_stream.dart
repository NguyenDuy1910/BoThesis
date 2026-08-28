import 'dart:convert';

import 'chat_models.dart';

class ChatStreamEvent {
  const ChatStreamEvent(this.payload);

  final Map<String, dynamic> payload;

  String get type => payload['type'] as String? ?? '';
  int? get sequenceNumber => payload['sequence_number'] as int?;

  factory ChatStreamEvent.decode(String value) {
    final decoded = jsonDecode(value);
    if (decoded is! Map) {
      throw const FormatException('Agent stream event must be a JSON object.');
    }
    return ChatStreamEvent(Map<String, dynamic>.from(decoded));
  }
}

abstract final class ChatStreamReducer {
  static void apply(ChatTurnState turn, ChatStreamEvent event) {
    final sequenceNumber = event.sequenceNumber;
    if (sequenceNumber != null) {
      if (sequenceNumber <= turn.lastSequenceNumber) return;
      turn.lastSequenceNumber = sequenceNumber;
    }

    final payload = event.payload;
    switch (event.type) {
      case 'response.created':
      case 'response.queued':
      case 'response.in_progress':
        final response = _responsePayload(payload);
        if (response == null) return;
        _reconcileResponse(turn, response);
        turn.currentResponseId = response['id'] as String?;
        turn.status = 'streaming';
        turn.error = null;
      case 'response.output_item.added':
        _upsertItem(turn, payload, done: false);
      case 'response.output_item.done':
        _upsertItem(turn, payload, done: true);
      case 'response.content_part.added':
      case 'response.content_part.done':
        final part = payload['part'];
        if (part is Map) {
          _setContentPart(
            turn,
            payload,
            ChatOutputPart.fromJson(Map<String, dynamic>.from(part)),
          );
        }
      case 'response.output_text.delta':
        final part = _contentPart(turn, payload, type: 'output_text');
        part.text += payload['delta'] as String? ?? '';
      case 'response.output_text.done':
        final part = _contentPart(turn, payload, type: 'output_text');
        part.text = payload['text'] as String? ?? '';
      case 'response.output_text.annotation.added':
        final annotation = payload['annotation'];
        if (annotation is Map) {
          final part = _contentPart(turn, payload, type: 'output_text');
          final index =
              payload['annotation_index'] as int? ?? part.annotations.length;
          part.annotations.insert(
            index.clamp(0, part.annotations.length),
            Map<String, dynamic>.from(annotation),
          );
        }
      case 'response.refusal.delta':
        final part = _contentPart(turn, payload, type: 'refusal');
        part.text += payload['delta'] as String? ?? '';
      case 'response.refusal.done':
        final part = _contentPart(turn, payload, type: 'refusal');
        part.text = payload['refusal'] as String? ?? '';
      case 'response.reasoning.delta':
        final part = _reasoningPart(turn, payload, summary: false);
        part.text += payload['delta'] as String? ?? '';
      case 'response.reasoning.done':
        final part = _reasoningPart(turn, payload, summary: false);
        part.text = payload['text'] as String? ?? '';
      case 'response.reasoning_summary_part.added':
      case 'response.reasoning_summary_part.done':
        final part = payload['part'];
        if (part is Map) {
          _setReasoningPart(
            turn,
            payload,
            ChatOutputPart.fromJson(Map<String, dynamic>.from(part)),
            summary: true,
          );
        }
      case 'response.reasoning_summary_text.delta':
        final part = _reasoningPart(turn, payload, summary: true);
        part.text += payload['delta'] as String? ?? '';
      case 'response.reasoning_summary_text.done':
        final part = _reasoningPart(turn, payload, summary: true);
        part.text = payload['text'] as String? ?? '';
      case 'response.function_call_arguments.delta':
        final item = _addressedItem(turn, payload, type: 'function_call');
        item.arguments += payload['delta'] as String? ?? '';
      case 'response.function_call_arguments.done':
        final item = _addressedItem(turn, payload, type: 'function_call');
        item.arguments = payload['arguments'] as String? ?? '';
      case 'response.completed':
        final responsePayload = _responsePayload(payload);
        if (responsePayload == null) return;
        final response = _reconcileResponse(turn, responsePayload);
        turn.status = response.hasFunctionCalls ? 'streaming' : 'completed';
        turn.error = null;
      case 'response.incomplete':
      case 'response.failed':
        final responsePayload = _responsePayload(payload);
        if (responsePayload == null) return;
        _reconcileResponse(turn, responsePayload);
        turn.status = 'failed';
        turn.error = _responseFailure(responsePayload);
      case 'error':
        final error = payload['error'];
        turn.status = 'failed';
        turn.error = error is Map
            ? error['message'] as String? ??
                  'The response could not be completed.'
            : 'The response could not be completed.';
    }
  }

  static Map<String, dynamic>? _responsePayload(Map<String, dynamic> payload) {
    final response = payload['response'];
    return response is Map ? Map<String, dynamic>.from(response) : null;
  }

  static ChatResponseState _reconcileResponse(
    ChatTurnState turn,
    Map<String, dynamic> payload,
  ) {
    final id = payload['id'] as String? ?? 'response';
    final response = turn.responses.putIfAbsent(
      id,
      () => ChatResponseState(id: id),
    );
    if (!turn.responseOrder.contains(id)) turn.responseOrder.add(id);
    response.status = payload['status'] as String? ?? response.status;
    response.previousResponseId =
        payload['previous_response_id'] as String? ??
        response.previousResponseId;
    final output = payload['output'];
    if (output is List) {
      for (var index = 0; index < output.length; index += 1) {
        final item = output[index];
        if (item is Map) {
          _mergeItem(
            response,
            index,
            Map<String, dynamic>.from(item),
            done: true,
          );
        }
      }
    }
    return response;
  }

  static void _upsertItem(
    ChatTurnState turn,
    Map<String, dynamic> payload, {
    required bool done,
  }) {
    final incoming = payload['item'];
    if (incoming is! Map) return;
    final response = _activeResponse(turn);
    _mergeItem(
      response,
      payload['output_index'] as int? ?? response.itemOrder.length,
      Map<String, dynamic>.from(incoming),
      done: done,
    );
  }

  static ChatOutputItem _mergeItem(
    ChatResponseState response,
    int outputIndex,
    Map<String, dynamic> payload, {
    required bool done,
  }) {
    final fallbackId = outputIndex < response.itemOrder.length
        ? response.itemOrder[outputIndex]
        : '${response.id}:output:$outputIndex';
    final id = payload['id'] as String? ?? fallbackId;
    final incoming = ChatOutputItem.fromJson(payload, fallbackId: id);
    if (payload['status'] == null) {
      incoming.status = done ? 'completed' : 'in_progress';
    }
    final previous = response.items[id];
    if (previous != null) {
      if (incoming.type == 'message' && previous.type == 'message') {
        _mergeParts(previous.content, incoming.content);
        incoming.content
          ..clear()
          ..addAll(previous.content);
      } else if (incoming.type == 'reasoning' && previous.type == 'reasoning') {
        if (incoming.content.isEmpty) incoming.content.addAll(previous.content);
        if (incoming.summary.isEmpty) incoming.summary.addAll(previous.summary);
      }
    }
    response.items[id] = incoming;
    _placeItem(response.itemOrder, id, outputIndex);
    return incoming;
  }

  static void _mergeParts(
    List<ChatOutputPart> previous,
    List<ChatOutputPart> incoming,
  ) {
    if (incoming.isEmpty) return;
    for (var index = 0; index < incoming.length; index += 1) {
      if (index >= previous.length) {
        previous.add(incoming[index]);
        continue;
      }
      final current = previous[index];
      final next = incoming[index];
      current.type = next.type;
      if (next.text.isNotEmpty) current.text = next.text;
      final known = current.annotations.map(jsonEncode).toSet();
      for (final annotation in next.annotations) {
        if (known.add(jsonEncode(annotation))) {
          current.annotations.add(annotation);
        }
      }
    }
  }

  static void _placeItem(List<String> order, String id, int outputIndex) {
    final currentIndex = order.indexOf(id);
    if (currentIndex >= 0) order.removeAt(currentIndex);
    order.insert(outputIndex.clamp(0, order.length), id);
  }

  static ChatResponseState _activeResponse(ChatTurnState turn) {
    final id =
        turn.currentResponseId ??
        (turn.responseOrder.isEmpty ? 'response' : turn.responseOrder.last);
    final response = turn.responses.putIfAbsent(
      id,
      () => ChatResponseState(id: id),
    );
    if (!turn.responseOrder.contains(id)) turn.responseOrder.add(id);
    return response;
  }

  static ChatOutputItem _addressedItem(
    ChatTurnState turn,
    Map<String, dynamic> payload, {
    required String type,
  }) {
    final response = _activeResponse(turn);
    final outputIndex =
        payload['output_index'] as int? ?? response.itemOrder.length;
    final itemId =
        payload['item_id'] as String? ?? '${response.id}:output:$outputIndex';
    final existing = response.items[itemId];
    if (existing != null) return existing;
    final item = ChatOutputItem(id: itemId, type: type);
    response.items[itemId] = item;
    _placeItem(response.itemOrder, itemId, outputIndex);
    return item;
  }

  static ChatOutputPart _contentPart(
    ChatTurnState turn,
    Map<String, dynamic> payload, {
    required String type,
  }) {
    final item = _addressedItem(turn, payload, type: 'message');
    item.role ??= 'assistant';
    final index = payload['content_index'] as int? ?? 0;
    while (item.content.length <= index) {
      item.content.add(ChatOutputPart(type: type));
    }
    item.content[index].type = type;
    return item.content[index];
  }

  static void _setContentPart(
    ChatTurnState turn,
    Map<String, dynamic> payload,
    ChatOutputPart part,
  ) {
    final item = _addressedItem(turn, payload, type: 'message');
    item.role ??= 'assistant';
    final index = payload['content_index'] as int? ?? 0;
    while (item.content.length <= index) {
      item.content.add(ChatOutputPart(type: 'output_text'));
    }
    item.content[index] = part;
  }

  static ChatOutputPart _reasoningPart(
    ChatTurnState turn,
    Map<String, dynamic> payload, {
    required bool summary,
  }) {
    final item = _addressedItem(turn, payload, type: 'reasoning');
    final list = summary ? item.summary : item.content;
    final index = summary
        ? payload['summary_index'] as int? ?? 0
        : payload['content_index'] as int? ?? 0;
    while (list.length <= index) {
      list.add(
        ChatOutputPart(type: summary ? 'summary_text' : 'reasoning_text'),
      );
    }
    return list[index];
  }

  static void _setReasoningPart(
    ChatTurnState turn,
    Map<String, dynamic> payload,
    ChatOutputPart part, {
    required bool summary,
  }) {
    final item = _addressedItem(turn, payload, type: 'reasoning');
    final list = summary ? item.summary : item.content;
    final index = summary
        ? payload['summary_index'] as int? ?? 0
        : payload['content_index'] as int? ?? 0;
    while (list.length <= index) {
      list.add(
        ChatOutputPart(type: summary ? 'summary_text' : 'reasoning_text'),
      );
    }
    list[index] = part;
  }

  static String _responseFailure(Map<String, dynamic> response) {
    final error = response['error'];
    if (error is Map && error['message'] is String) {
      return error['message'] as String;
    }
    final details = response['incomplete_details'];
    if (details is Map && details['reason'] is String) {
      return details['reason'] as String;
    }
    return 'The response could not be completed.';
  }
}
