enum ChatRole { user, assistant }

enum ChatStatus { ready, submitted, streaming }

enum ChatConnectorMode { auto, selected, off }

class ChatConversation {
  const ChatConversation({
    required this.id,
    required this.title,
    required this.createdAt,
    required this.updatedAt,
    this.titleSource = 'generated',
    this.deletedAt,
  });

  final String id;
  final String title;
  final String titleSource;
  final DateTime createdAt;
  final DateTime updatedAt;
  final DateTime? deletedAt;

  ChatConversation copyWith({
    String? title,
    String? titleSource,
    DateTime? updatedAt,
    DateTime? deletedAt,
  }) {
    return ChatConversation(
      id: id,
      title: title ?? this.title,
      titleSource: titleSource ?? this.titleSource,
      createdAt: createdAt,
      updatedAt: updatedAt ?? this.updatedAt,
      deletedAt: deletedAt ?? this.deletedAt,
    );
  }

  factory ChatConversation.fromJson(Map<String, dynamic> json) {
    return ChatConversation(
      id: json['id'] as String,
      title: json['title'] as String? ?? 'New conversation',
      titleSource: json['title_source'] as String? ?? 'generated',
      createdAt: DateTime.fromMillisecondsSinceEpoch(
        json['created_at'] as int? ?? 0,
      ),
      updatedAt: DateTime.fromMillisecondsSinceEpoch(
        json['updated_at'] as int? ?? 0,
      ),
      deletedAt: switch (json['deleted_at']) {
        final int value => DateTime.fromMillisecondsSinceEpoch(value),
        _ => null,
      },
    );
  }

  Map<String, dynamic> toJson() => <String, dynamic>{
    'id': id,
    'title': title,
    'title_source': titleSource,
    'created_at': createdAt.millisecondsSinceEpoch,
    'updated_at': updatedAt.millisecondsSinceEpoch,
    if (deletedAt case final value?) 'deleted_at': value.millisecondsSinceEpoch,
  };
}

class ConversationDocument {
  const ConversationDocument({
    required this.id,
    required this.fileName,
    required this.contentType,
    required this.sizeBytes,
    required this.mode,
    required this.status,
  });

  final String id;
  final String fileName;
  final String contentType;
  final int sizeBytes;
  final String mode;
  final String status;

  factory ConversationDocument.fromJson(Map<String, dynamic> json) {
    return ConversationDocument(
      id: json['id'] as String,
      fileName: json['file_name'] as String? ?? 'Document',
      contentType:
          json['content_type'] as String? ?? 'application/octet-stream',
      sizeBytes: json['size_bytes'] as int? ?? 0,
      mode: json['mode'] as String? ?? 'indexed',
      status: json['status'] as String? ?? 'available',
    );
  }

  Map<String, dynamic> toJson() => <String, dynamic>{
    'id': id,
    'file_name': fileName,
    'content_type': contentType,
    'size_bytes': sizeBytes,
    'mode': mode,
    'status': status,
  };
}

class ChatMessage {
  const ChatMessage({
    required this.id,
    required this.role,
    this.text = '',
    this.documents = const <ConversationDocument>[],
    this.turn,
    required this.createdAt,
  });

  final String id;
  final ChatRole role;
  final String text;
  final List<ConversationDocument> documents;
  final ChatTurnState? turn;
  final DateTime createdAt;

  String get displayText =>
      role == ChatRole.assistant ? (turn?.finalAnswerText ?? text) : text;

  factory ChatMessage.fromJson(Map<String, dynamic> json) {
    final documents = json['documents'];
    final turn = json['turn'];
    return ChatMessage(
      id: json['id'] as String,
      role: json['role'] == 'assistant' ? ChatRole.assistant : ChatRole.user,
      text: json['text'] as String? ?? '',
      documents: documents is List
          ? documents
                .whereType<Map>()
                .map(
                  (value) => ConversationDocument.fromJson(
                    Map<String, dynamic>.from(value),
                  ),
                )
                .toList()
          : const <ConversationDocument>[],
      turn: turn is Map
          ? ChatTurnState.fromJson(Map<String, dynamic>.from(turn))
          : null,
      createdAt: DateTime.fromMillisecondsSinceEpoch(
        json['created_at'] as int? ?? 0,
      ),
    );
  }

  Map<String, dynamic> toJson() => <String, dynamic>{
    'id': id,
    'role': role.name,
    'text': text,
    'documents': documents.map((document) => document.toJson()).toList(),
    if (turn case final value?) 'turn': value.toJson(),
    'created_at': createdAt.millisecondsSinceEpoch,
  };
}

class ChatConnector {
  const ChatConnector({
    required this.id,
    required this.provider,
    required this.displayName,
    this.capabilities = const <String>[],
  });

  final String id;
  final String provider;
  final String displayName;
  final List<String> capabilities;

  factory ChatConnector.fromJson(Map<String, dynamic> json) {
    return ChatConnector(
      id: json['id'].toString(),
      provider: json['provider'] as String? ?? 'knowledge',
      displayName: json['display_name'] as String? ?? 'Knowledge source',
      capabilities:
          (json['capabilities'] as List?)?.whereType<String>().toList() ??
          const <String>[],
    );
  }
}

class ChatOutputPart {
  ChatOutputPart({
    required this.type,
    this.text = '',
    List<Map<String, dynamic>>? annotations,
  }) : annotations = annotations ?? <Map<String, dynamic>>[];

  String type;
  String text;
  final List<Map<String, dynamic>> annotations;

  factory ChatOutputPart.fromJson(Map<String, dynamic> json) {
    return ChatOutputPart(
      type: json['type'] as String? ?? 'output_text',
      text: json['text'] as String? ?? json['refusal'] as String? ?? '',
      annotations:
          (json['annotations'] as List?)
              ?.whereType<Map>()
              .map((value) => Map<String, dynamic>.from(value))
              .toList() ??
          <Map<String, dynamic>>[],
    );
  }

  Map<String, dynamic> toJson() => <String, dynamic>{
    'type': type,
    if (type == 'refusal') 'refusal': text else 'text': text,
    if (annotations.isNotEmpty) 'annotations': annotations,
  };
}

class ChatOutputItem {
  ChatOutputItem({
    required this.id,
    required this.type,
    this.status = 'in_progress',
    this.role,
    this.phase,
    List<ChatOutputPart>? content,
    List<ChatOutputPart>? summary,
    this.name,
    this.callId,
    this.arguments = '',
  }) : content = content ?? <ChatOutputPart>[],
       summary = summary ?? <ChatOutputPart>[];

  String id;
  String type;
  String status;
  String? role;
  String? phase;
  final List<ChatOutputPart> content;
  final List<ChatOutputPart> summary;
  String? name;
  String? callId;
  String arguments;

  String get messageText => content
      .where((part) => part.type == 'output_text' || part.type == 'refusal')
      .map((part) => part.text)
      .join();

  String get summaryText => summary.map((part) => part.text).join();

  factory ChatOutputItem.fromJson(
    Map<String, dynamic> json, {
    String? fallbackId,
  }) {
    List<ChatOutputPart> parts(Object? value) => value is List
        ? value
              .whereType<Map>()
              .map(
                (part) =>
                    ChatOutputPart.fromJson(Map<String, dynamic>.from(part)),
              )
              .toList()
        : <ChatOutputPart>[];

    return ChatOutputItem(
      id: json['id'] as String? ?? fallbackId ?? 'output',
      type: json['type'] as String? ?? 'message',
      status: json['status'] as String? ?? 'in_progress',
      role: json['role'] as String?,
      phase: json['phase'] as String?,
      content: parts(json['content']),
      summary: parts(json['summary']),
      name: json['name'] as String?,
      callId: json['call_id'] as String?,
      arguments: json['arguments'] as String? ?? '',
    );
  }

  Map<String, dynamic> toJson() => <String, dynamic>{
    'id': id,
    'type': type,
    'status': status,
    'role': ?role,
    'phase': ?phase,
    if (content.isNotEmpty)
      'content': content.map((part) => part.toJson()).toList(),
    if (summary.isNotEmpty)
      'summary': summary.map((part) => part.toJson()).toList(),
    'name': ?name,
    'call_id': ?callId,
    if (arguments.isNotEmpty) 'arguments': arguments,
  };
}

class ChatResponseState {
  ChatResponseState({
    required this.id,
    this.status = 'in_progress',
    Map<String, ChatOutputItem>? items,
    List<String>? itemOrder,
    this.previousResponseId,
  }) : items = items ?? <String, ChatOutputItem>{},
       itemOrder = itemOrder ?? <String>[];

  final String id;
  String status;
  final Map<String, ChatOutputItem> items;
  final List<String> itemOrder;
  String? previousResponseId;

  bool get hasFunctionCalls =>
      itemOrder.any((id) => items[id]?.type == 'function_call');

  factory ChatResponseState.fromJson(Map<String, dynamic> json) {
    final rawItems = json['items'];
    return ChatResponseState(
      id: json['id'] as String,
      status: json['status'] as String? ?? 'in_progress',
      items: rawItems is Map
          ? rawItems.map(
              (key, value) => MapEntry(
                key.toString(),
                ChatOutputItem.fromJson(
                  Map<String, dynamic>.from(value as Map),
                  fallbackId: key.toString(),
                ),
              ),
            )
          : <String, ChatOutputItem>{},
      itemOrder:
          (json['item_order'] as List?)?.whereType<String>().toList() ??
          <String>[],
      previousResponseId: json['previous_response_id'] as String?,
    );
  }

  Map<String, dynamic> toJson() => <String, dynamic>{
    'id': id,
    'status': status,
    'items': items.map((key, item) => MapEntry(key, item.toJson())),
    'item_order': itemOrder,
    'previous_response_id': ?previousResponseId,
  };
}

class ChatTurnState {
  ChatTurnState({
    required this.id,
    this.status = 'streaming',
    Map<String, ChatResponseState>? responses,
    List<String>? responseOrder,
    this.currentResponseId,
    this.error,
    this.lastSequenceNumber = 0,
  }) : responses = responses ?? <String, ChatResponseState>{},
       responseOrder = responseOrder ?? <String>[];

  final String id;
  String status;
  final Map<String, ChatResponseState> responses;
  final List<String> responseOrder;
  String? currentResponseId;
  String? error;
  int lastSequenceNumber;

  Iterable<OrderedTurnItem> get orderedItems sync* {
    for (
      var responseIndex = 0;
      responseIndex < responseOrder.length;
      responseIndex += 1
    ) {
      final responseId = responseOrder[responseIndex];
      final response = responses[responseId];
      if (response == null) continue;
      for (
        var outputIndex = 0;
        outputIndex < response.itemOrder.length;
        outputIndex += 1
      ) {
        final item = response.items[response.itemOrder[outputIndex]];
        if (item == null) continue;
        yield OrderedTurnItem(
          item: item,
          responseIndex: responseIndex,
          outputIndex: outputIndex,
        );
      }
    }
  }

  String get finalAnswerText {
    if (responseOrder.isEmpty) return '';
    final response = responses[responseOrder.last];
    if (response == null) return '';
    final messages = response.itemOrder
        .map((id) => response.items[id])
        .whereType<ChatOutputItem>()
        .where((item) => item.type == 'message' && item.role == 'assistant')
        .toList();
    final answers = messages
        .where((item) => item.phase == 'final_answer')
        .toList();
    final selected = answers.isNotEmpty
        ? answers
        : messages.where((item) => item.phase != 'commentary');
    return selected.map((item) => item.messageText).join();
  }

  List<AssistantTurnItem> get presentationItems {
    final newestResponseIndex = responseOrder.length - 1;
    final result = <AssistantTurnItem>[];
    for (final ordered in orderedItems) {
      final item = ordered.item;
      if (item.type == 'message' && item.role == 'assistant') {
        final text = item.messageText;
        if (text.isNotEmpty) {
          result.add(
            AssistantTurnItem.message(
              id: item.id,
              text: text,
              state: item.status == 'completed' || status != 'streaming'
                  ? 'done'
                  : 'streaming',
            ),
          );
        }
      } else if (item.type == 'function_call') {
        final state =
            status == 'failed' && ordered.responseIndex == newestResponseIndex
            ? 'error'
            : status == 'streaming' &&
                  ordered.responseIndex == newestResponseIndex
            ? 'active'
            : 'completed';
        result.add(
          AssistantTurnItem.tool(
            id: item.id,
            name: item.name ?? 'tool',
            state: state,
          ),
        );
      } else if (item.type == 'reasoning') {
        final active =
            status == 'streaming' &&
            ordered.responseIndex == newestResponseIndex &&
            item.status != 'completed';
        if (item.summaryText.isNotEmpty || active) {
          result.add(
            AssistantTurnItem.reasoning(
              id: item.id,
              text: item.summaryText,
              state: active ? 'active' : 'completed',
            ),
          );
        }
      }
    }
    return result;
  }

  List<AnswerSource> get sources {
    const citationType = 'bothesis:document_citation';
    final result = <String, AnswerSource>{};
    final order = <String>[];
    for (final ordered in orderedItems) {
      if (ordered.item.type != 'message') continue;
      for (final part in ordered.item.content) {
        for (final annotation in part.annotations) {
          if (annotation['type'] != citationType ||
              annotation['citation'] is! Map) {
            continue;
          }
          final source = AnswerSource.fromCitation(
            Map<String, dynamic>.from(annotation['citation'] as Map),
          );
          if (source == null) continue;
          if (!result.containsKey(source.id)) order.add(source.id);
          result[source.id] = source;
        }
      }
    }
    return order.map((id) => result[id]!).toList();
  }

  factory ChatTurnState.fromJson(Map<String, dynamic> json) {
    final rawResponses = json['responses'];
    return ChatTurnState(
      id: json['id'] as String,
      status: json['status'] as String? ?? 'completed',
      responses: rawResponses is Map
          ? rawResponses.map(
              (key, value) => MapEntry(
                key.toString(),
                ChatResponseState.fromJson(
                  Map<String, dynamic>.from(value as Map),
                ),
              ),
            )
          : <String, ChatResponseState>{},
      responseOrder:
          (json['response_order'] as List?)?.whereType<String>().toList() ??
          <String>[],
      currentResponseId: json['current_response_id'] as String?,
      error: json['error'] as String?,
      lastSequenceNumber: json['last_sequence_number'] as int? ?? 0,
    );
  }

  Map<String, dynamic> toJson() => <String, dynamic>{
    'id': id,
    'status': status,
    'responses': responses.map(
      (key, response) => MapEntry(key, response.toJson()),
    ),
    'response_order': responseOrder,
    'current_response_id': ?currentResponseId,
    'error': ?error,
    'last_sequence_number': lastSequenceNumber,
  };
}

class OrderedTurnItem {
  const OrderedTurnItem({
    required this.item,
    required this.responseIndex,
    required this.outputIndex,
  });

  final ChatOutputItem item;
  final int responseIndex;
  final int outputIndex;
}

enum AssistantTurnItemKind { message, tool, reasoning }

class AssistantTurnItem {
  const AssistantTurnItem._({
    required this.kind,
    required this.id,
    required this.state,
    this.text = '',
    this.name = '',
  });

  factory AssistantTurnItem.message({
    required String id,
    required String text,
    required String state,
  }) => AssistantTurnItem._(
    kind: AssistantTurnItemKind.message,
    id: id,
    text: text,
    state: state,
  );

  factory AssistantTurnItem.tool({
    required String id,
    required String name,
    required String state,
  }) => AssistantTurnItem._(
    kind: AssistantTurnItemKind.tool,
    id: id,
    name: name,
    state: state,
  );

  factory AssistantTurnItem.reasoning({
    required String id,
    required String text,
    required String state,
  }) => AssistantTurnItem._(
    kind: AssistantTurnItemKind.reasoning,
    id: id,
    text: text,
    state: state,
  );

  final AssistantTurnItemKind kind;
  final String id;
  final String state;
  final String text;
  final String name;
}

class AnswerSource {
  const AnswerSource({
    required this.id,
    required this.title,
    required this.itemId,
    required this.chunkId,
    required this.internalUrl,
    this.originalUrl,
    this.locator,
    this.origin,
  });

  final String id;
  final String title;
  final String itemId;
  final String chunkId;
  final String internalUrl;
  final String? originalUrl;
  final String? locator;
  final String? origin;

  static AnswerSource? fromCitation(Map<String, dynamic> citation) {
    final itemId = (citation['item_id'] as String?)?.trim();
    final chunkId = (citation['chunk_id'] as String?)?.trim();
    if (itemId == null ||
        itemId.isEmpty ||
        chunkId == null ||
        chunkId.isEmpty) {
      return null;
    }
    final source = citation['source'] is Map
        ? Map<String, dynamic>.from(citation['source'] as Map)
        : const <String, dynamic>{};
    final spans =
        (citation['spans'] as List?)
            ?.whereType<Map>()
            .map((span) => Map<String, dynamic>.from(span))
            .toList() ??
        const <Map<String, dynamic>>[];
    final pages = spans.map((span) => span['page']).whereType<int>().toList();
    final section = (citation['section'] as String?)?.trim();
    final locatorParts = <String>[
      if (pages.isNotEmpty)
        pages.length == 1
            ? 'p. ${pages.first}'
            : 'p. ${pages.first}–${pages.last}',
      if (section != null && section.isNotEmpty) section,
    ];
    final provider = (source['provider'] as String?)?.trim();
    final internal = (citation['internal_url'] as String?)?.trim();
    return AnswerSource(
      id: (citation['id'] as String?)?.trim().isNotEmpty == true
          ? (citation['id'] as String).trim()
          : chunkId,
      title: (citation['title'] as String?)?.trim().isNotEmpty == true
          ? (citation['title'] as String).trim()
          : provider?.isNotEmpty == true
          ? provider!
          : 'Untitled source',
      itemId: itemId,
      chunkId: chunkId,
      internalUrl: internal?.isNotEmpty == true
          ? internal!
          : '/knowledge/items/${Uri.encodeComponent(itemId)}'
                '?chunk=${Uri.encodeComponent(chunkId)}',
      originalUrl:
          (citation['original_url'] as String?)?.trim().isNotEmpty == true
          ? (citation['original_url'] as String).trim()
          : (source['url'] as String?)?.trim(),
      locator: locatorParts.isEmpty ? null : locatorParts.join(' · '),
      origin: provider?.isEmpty == true ? null : provider,
    );
  }
}
