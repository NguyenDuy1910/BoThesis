import 'dart:async';
import 'dart:math';

import 'package:flutter/foundation.dart';

import '../../../app/app_config.dart';
import '../models/chat_models.dart';
import '../models/chat_stream.dart';
import '../services/chat_service.dart';
import '../services/conversation_store.dart';

class ChatController extends ChangeNotifier {
  ChatController(this._service, this._store) : _draftId = _newUuid();

  final ChatService _service;
  final ConversationStore _store;

  List<ChatConversation> conversations = <ChatConversation>[];
  List<ChatMessage> messages = <ChatMessage>[];
  List<ChatConnector> connectors = <ChatConnector>[];
  List<ComposerAttachment> attachments = <ComposerAttachment>[];
  Set<String> selectedConnectorIds = <String>{};
  ChatConnectorMode connectorMode = ChatConnectorMode.auto;
  ChatStatus status = ChatStatus.ready;
  String? activeConversationId;
  String? error;
  String? connectorsError;
  bool isLoading = true;
  bool connectorsLoading = false;

  String _draftId;
  ChatStreamHandle? _activeHandle;
  String? _activeAssistantId;
  int _runToken = 0;
  bool _disposed = false;

  bool get isConfigured => AppConfig.isConfigured;
  bool get isGenerating => status != ChatStatus.ready;
  bool get isUploading => attachments.any(
    (attachment) => switch (attachment.progress) {
      UploadProgress.starting ||
      UploadProgress.uploading ||
      UploadProgress.validating => true,
      _ => false,
    },
  );
  String get conversationId => activeConversationId ?? _draftId;
  String get conversationTitle =>
      conversations
          .where((conversation) => conversation.id == activeConversationId)
          .map((conversation) => conversation.title)
          .firstOrNull ??
      'New conversation';
  bool get hasMessageError =>
      messages.any((message) => message.turn?.status == 'failed');
  List<ChatConnector> get selectedConnectors => connectors
      .where((connector) => selectedConnectorIds.contains(connector.id))
      .toList();

  String? get activityConnectorLabel {
    if (connectorMode == ChatConnectorMode.selected) {
      if (selectedConnectors.length == 1) {
        return selectedConnectors.first.displayName;
      }
      if (selectedConnectors.length > 1) return 'selected sources';
    }
    return connectorMode == ChatConnectorMode.auto
        ? 'permitted knowledge'
        : null;
  }

  Uri sourceUri(AnswerSource source) =>
      _service.resolveSourceUrl(source.originalUrl ?? source.internalUrl);

  Future<void> initialize() async {
    try {
      conversations = await _store.listConversations();
      activeConversationId = conversations.firstOrNull?.id;
      messages = activeConversationId == null
          ? <ChatMessage>[]
          : await _store.getMessages(activeConversationId!);
    } catch (cause) {
      error = _messageFrom(cause, 'Could not load local conversations.');
    } finally {
      isLoading = false;
      _notify();
    }
    if (isConfigured) unawaited(loadConnectors());
  }

  Future<void> loadConnectors() async {
    connectorsLoading = true;
    connectorsError = null;
    _notify();
    try {
      connectors = await _service.getAvailableConnectors();
      selectedConnectorIds = selectedConnectorIds
          .where((id) => connectors.any((connector) => connector.id == id))
          .toSet();
    } catch (cause) {
      connectorsError = _messageFrom(
        cause,
        'Could not load permitted connectors.',
      );
    } finally {
      connectorsLoading = false;
      _notify();
    }
  }

  Future<void> newChat() async {
    _cancelActive(markStopped: false);
    activeConversationId = null;
    _draftId = _newUuid();
    messages = <ChatMessage>[];
    error = null;
    attachments = <ComposerAttachment>[];
    _notify();
  }

  Future<void> selectConversation(String id) async {
    if (id == activeConversationId) return;
    _cancelActive(markStopped: false);
    activeConversationId = id;
    messages = await _store.getMessages(id);
    attachments = <ComposerAttachment>[];
    error = null;
    _notify();
  }

  Future<void> renameConversation(String id, String title) async {
    final cleaned = title.replaceAll(RegExp(r'\s+'), ' ').trim();
    if (cleaned.isEmpty) return;
    await _store.updateConversation(id, title: cleaned, titleSource: 'custom');
    conversations = await _store.listConversations();
    _notify();
  }

  Future<void> hideConversation(String id) async {
    final hiddenMessages = await _store.getMessages(id);
    await _store.hideConversation(id);
    for (final documentId
        in hiddenMessages
            .expand((message) => message.documents)
            .map((document) => document.id)
            .toSet()) {
      unawaited(_service.releaseDocument(documentId).catchError((_) {}));
    }
    conversations = await _store.listConversations();
    if (activeConversationId == id) {
      _cancelActive(markStopped: false);
      activeConversationId = conversations.firstOrNull?.id;
      messages = activeConversationId == null
          ? <ChatMessage>[]
          : await _store.getMessages(activeConversationId!);
      if (activeConversationId == null) _draftId = _newUuid();
    }
    _notify();
  }

  void setConnectorMode(ChatConnectorMode mode) {
    connectorMode = mode;
    _notify();
  }

  void toggleConnector(String id) {
    if (selectedConnectorIds.contains(id)) {
      selectedConnectorIds.remove(id);
    } else {
      selectedConnectorIds.add(id);
    }
    _notify();
  }

  bool canSend(String input) {
    final hasReadyDocument = attachments.any(
      (attachment) => attachment.progress == UploadProgress.ready,
    );
    return isConfigured &&
        !isGenerating &&
        !isUploading &&
        (input.trim().isNotEmpty || hasReadyDocument) &&
        (connectorMode != ChatConnectorMode.selected ||
            selectedConnectorIds.isNotEmpty);
  }

  Future<void> addAttachment({
    required String fileName,
    required Uint8List bytes,
  }) async {
    if (attachments.length >= 12) return;
    final key = _newUuid();
    final attachment = ComposerAttachment(
      key: key,
      fileName: fileName,
      sizeBytes: bytes.length,
      progress: UploadProgress.starting,
    );
    attachments = <ComposerAttachment>[...attachments, attachment];
    _notify();
    try {
      final document = await _service.uploadDocument(
        UploadFile(
          fileName: fileName,
          contentType: _contentType(fileName),
          bytes: bytes,
          idempotencyKey: key,
        ),
        onProgress: (progress) {
          _updateAttachment(key, progress: progress);
        },
      );
      if (!attachments.any((item) => item.key == key)) {
        unawaited(_service.releaseDocument(document.id).catchError((_) {}));
        return;
      }
      _updateAttachment(
        key,
        progress: UploadProgress.ready,
        document: document,
      );
    } catch (cause) {
      _updateAttachment(
        key,
        progress: UploadProgress.failed,
        error: _messageFrom(cause, 'Document upload failed.'),
      );
    }
  }

  void removeAttachment(String key) {
    final match = attachments.where((item) => item.key == key).firstOrNull;
    attachments = attachments.where((item) => item.key != key).toList();
    if (match?.document case final document?) {
      unawaited(_service.releaseDocument(document.id).catchError((_) {}));
    }
    _notify();
  }

  Future<void> sendMessage(String value) async {
    if (!canSend(value)) return;
    final documents = attachments
        .map((attachment) => attachment.document)
        .whereType<ConversationDocument>()
        .toList();
    final text = value.trim().isNotEmpty
        ? value.trim()
        : 'Please analyze the attached file.';
    attachments = <ComposerAttachment>[];
    await _run(
      text: text,
      includeUserMessage: true,
      historyMessages: List<ChatMessage>.from(messages),
      displayMessages: List<ChatMessage>.from(messages),
      documents: documents,
    );
  }

  Future<void> regenerate(String assistantMessageId) async {
    if (isGenerating || !isConfigured) return;
    final target = messages.indexWhere(
      (message) => message.id == assistantMessageId,
    );
    if (target < 0) return;
    ChatMessage? user;
    var userIndex = target - 1;
    while (userIndex >= 0) {
      if (messages[userIndex].role == ChatRole.user) {
        user = messages[userIndex];
        break;
      }
      userIndex -= 1;
    }
    if (user == null || user.text.trim().isEmpty) return;
    await _run(
      text: user.text.trim(),
      includeUserMessage: false,
      historyMessages: messages.sublist(0, userIndex),
      displayMessages: messages.sublist(0, userIndex + 1),
      documents: user.documents,
    );
  }

  void stop() => _cancelActive(markStopped: true);

  Future<void> _run({
    required String text,
    required bool includeUserMessage,
    required List<ChatMessage> historyMessages,
    required List<ChatMessage> displayMessages,
    required List<ConversationDocument> documents,
  }) async {
    if (_activeHandle != null) return;
    error = null;
    status = ChatStatus.submitted;
    final assistantId = _newUuid();
    final assistant = ChatMessage(
      id: assistantId,
      role: ChatRole.assistant,
      turn: ChatTurnState(id: assistantId),
      createdAt: DateTime.now(),
    );
    final next = List<ChatMessage>.from(displayMessages);
    if (includeUserMessage) {
      next.add(
        ChatMessage(
          id: _newUuid(),
          role: ChatRole.user,
          text: text,
          documents: documents,
          createdAt: DateTime.now(),
        ),
      );
    }
    next.add(assistant);
    messages = next;
    _activeAssistantId = assistantId;
    final token = ++_runToken;
    final handle = _service.streamMessage(
      message: text,
      conversationId: conversationId,
      history: _historyFromMessages(historyMessages),
      documentIds: documents.map((document) => document.id).toList(),
      connectorMode: connectorMode,
      connectorIds: selectedConnectorIds.toList(),
    );
    _activeHandle = handle;
    _notify();

    try {
      await for (final event in handle.events) {
        if (token != _runToken) return;
        status = ChatStatus.streaming;
        ChatStreamReducer.apply(assistant.turn!, event);
        if (assistant.turn!.status == 'failed') {
          error = assistant.turn!.error;
        }
        _notify();
      }
      if (token == _runToken) await _saveMessages();
    } catch (cause) {
      if (token != _runToken) return;
      final message = _messageFrom(cause, 'Chat request failed.');
      assistant.turn!
        ..status = 'failed'
        ..error = message;
      error = message;
      _notify();
      await _saveMessages();
    } finally {
      if (token == _runToken) {
        _activeHandle = null;
        _activeAssistantId = null;
        status = ChatStatus.ready;
        _notify();
      }
    }
  }

  void _cancelActive({required bool markStopped}) {
    final activeAssistantId = _activeAssistantId;
    _runToken += 1;
    _activeHandle?.cancel();
    _activeHandle = null;
    _activeAssistantId = null;
    if (markStopped && activeAssistantId != null) {
      final assistant = messages
          .where((message) => message.id == activeAssistantId)
          .firstOrNull;
      assistant?.turn
        ?..status = 'failed'
        ..error = 'Response stopped.';
    }
    status = ChatStatus.ready;
    _notify();
  }

  Future<void> _saveMessages() async {
    final firstUser = messages
        .where((message) => message.role == ChatRole.user)
        .firstOrNull;
    if (firstUser == null) return;
    final id = conversationId;
    final existing = conversations
        .where((conversation) => conversation.id == id)
        .firstOrNull;
    if (existing == null) {
      await _store.createConversation(
        id: id,
        title: _titleFromMessage(firstUser.text),
      );
    }
    await _store.saveMessages(id, messages);
    if (existing?.titleSource != 'custom') {
      await _store.updateConversation(
        id,
        title: _titleFromMessage(firstUser.text),
        titleSource: 'generated',
      );
    }
    activeConversationId = id;
    conversations = await _store.listConversations();
    _notify();
  }

  void _updateAttachment(
    String key, {
    required UploadProgress progress,
    ConversationDocument? document,
    String? error,
  }) {
    attachments = attachments
        .map(
          (attachment) => attachment.key == key
              ? attachment.copyWith(
                  progress: progress,
                  document: document,
                  error: error,
                )
              : attachment,
        )
        .toList();
    _notify();
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _activeHandle?.cancel();
    _service.close();
    super.dispose();
  }
}

class ComposerAttachment {
  const ComposerAttachment({
    required this.key,
    required this.fileName,
    required this.sizeBytes,
    required this.progress,
    this.document,
    this.error,
  });

  final String key;
  final String fileName;
  final int sizeBytes;
  final UploadProgress progress;
  final ConversationDocument? document;
  final String? error;

  ComposerAttachment copyWith({
    UploadProgress? progress,
    ConversationDocument? document,
    String? error,
  }) => ComposerAttachment(
    key: key,
    fileName: fileName,
    sizeBytes: sizeBytes,
    progress: progress ?? this.progress,
    document: document ?? this.document,
    error: error ?? this.error,
  );
}

List<Map<String, String>> _historyFromMessages(List<ChatMessage> messages) {
  const maxMessages = 24;
  const maxCharacters = 24000;
  var remaining = maxCharacters;
  final selected = <Map<String, String>>[];
  for (final message in messages.reversed) {
    final content = _clipHistory(message.displayText.trim());
    if (content.isEmpty) continue;
    if (selected.length == maxMessages || content.length > remaining) break;
    selected.add(<String, String>{
      'role': message.role.name,
      'content': content,
    });
    remaining -= content.length;
  }
  final result = selected.reversed.toList();
  while (result.firstOrNull?['role'] == 'assistant') {
    result.removeAt(0);
  }
  return result;
}

String _clipHistory(String value) {
  const max = 8000;
  const marker = '\n…\n';
  if (value.length <= max) return value;
  final available = max - marker.length;
  final leading = (available * 0.6).ceil();
  return '${value.substring(0, leading)}$marker'
      '${value.substring(value.length - (available - leading))}';
}

String _titleFromMessage(String value) {
  final cleaned = value.replaceAll(RegExp(r'\s+'), ' ').trim();
  if (cleaned.isEmpty) return 'New conversation';
  return cleaned.length > 54 ? '${cleaned.substring(0, 51)}…' : cleaned;
}

String _messageFrom(Object cause, String fallback) {
  if (cause is ChatRequestException) return cause.message;
  final value = cause.toString().trim();
  return value.isEmpty ? fallback : value;
}

String _contentType(String fileName) {
  final extension = fileName.split('.').last.toLowerCase();
  return switch (extension) {
    'pdf' => 'application/pdf',
    'png' => 'image/png',
    'jpg' || 'jpeg' => 'image/jpeg',
    'gif' => 'image/gif',
    'webp' => 'image/webp',
    'csv' => 'text/csv',
    'json' || 'jsonl' => 'application/json',
    'html' || 'htm' => 'text/html',
    'md' || 'markdown' => 'text/markdown',
    'txt' || 'log' || 'sql' || 'yaml' || 'yml' || 'xml' => 'text/plain',
    'docx' =>
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'pptx' => 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'xlsx' =>
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    _ => 'application/octet-stream',
  };
}

String _newUuid() {
  final bytes = List<int>.generate(16, (_) => Random.secure().nextInt(256));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  String hex(int value) => value.toRadixString(16).padLeft(2, '0');
  final value = bytes.map(hex).join();
  return '${value.substring(0, 8)}-${value.substring(8, 12)}-'
      '${value.substring(12, 16)}-${value.substring(16, 20)}-'
      '${value.substring(20)}';
}
