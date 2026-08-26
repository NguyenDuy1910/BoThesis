import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import '../models/chat_models.dart';

class ConversationStore {
  ConversationStore({
    required String userNamespace,
    SharedPreferencesAsync? preferences,
  }) : _userNamespace = userNamespace.trim().toLowerCase().isEmpty
           ? 'anonymous'
           : userNamespace.trim().toLowerCase(),
       _preferences = preferences ?? SharedPreferencesAsync();

  final String _userNamespace;
  final SharedPreferencesAsync _preferences;

  String get _conversationKey => 'bothesis-conversations:$_userNamespace';
  String _messageKey(String id) => 'bothesis-messages:$_userNamespace:$id';

  Future<List<ChatConversation>> listConversations() async {
    final conversations = await _readConversations();
    return conversations
        .where((conversation) => conversation.deletedAt == null)
        .toList()
      ..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
  }

  Future<ChatConversation> createConversation({
    required String id,
    required String title,
  }) async {
    final conversations = await _readConversations();
    final existingIndex = conversations.indexWhere(
      (conversation) => conversation.id == id,
    );
    final now = DateTime.now();
    if (existingIndex >= 0) {
      final restored = ChatConversation(
        id: id,
        title: title,
        titleSource: conversations[existingIndex].titleSource,
        createdAt: conversations[existingIndex].createdAt,
        updatedAt: now,
      );
      conversations[existingIndex] = restored;
      await _writeConversations(conversations);
      return restored;
    }
    final created = ChatConversation(
      id: id,
      title: title,
      createdAt: now,
      updatedAt: now,
    );
    await _writeConversations(<ChatConversation>[created, ...conversations]);
    return created;
  }

  Future<void> saveMessages(String id, List<ChatMessage> messages) async {
    final bounded = messages.length > 100
        ? messages.sublist(messages.length - 100)
        : messages;
    await _preferences.setString(
      _messageKey(id),
      jsonEncode(bounded.map((message) => message.toJson()).toList()),
    );
  }

  Future<List<ChatMessage>> getMessages(String id) async {
    final raw = await _preferences.getString(_messageKey(id));
    if (raw == null) return <ChatMessage>[];
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! List) return <ChatMessage>[];
      return decoded
          .whereType<Map>()
          .map(
            (message) =>
                ChatMessage.fromJson(Map<String, dynamic>.from(message)),
          )
          .toList();
    } on FormatException {
      return <ChatMessage>[];
    }
  }

  Future<void> updateConversation(
    String id, {
    required String title,
    required String titleSource,
  }) async {
    final conversations = await _readConversations();
    final index = conversations.indexWhere(
      (conversation) => conversation.id == id && conversation.deletedAt == null,
    );
    if (index < 0) return;
    conversations[index] = conversations[index].copyWith(
      title: title,
      titleSource: titleSource,
      updatedAt: DateTime.now(),
    );
    await _writeConversations(conversations);
  }

  Future<void> hideConversation(String id) async {
    final conversations = await _readConversations();
    final index = conversations.indexWhere(
      (conversation) => conversation.id == id && conversation.deletedAt == null,
    );
    if (index < 0) return;
    conversations[index] = conversations[index].copyWith(
      updatedAt: DateTime.now(),
      deletedAt: DateTime.now(),
    );
    await _writeConversations(conversations);
  }

  Future<List<ChatConversation>> _readConversations() async {
    final raw = await _preferences.getString(_conversationKey);
    if (raw == null) return <ChatConversation>[];
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! List) return <ChatConversation>[];
      return decoded
          .whereType<Map>()
          .map(
            (conversation) => ChatConversation.fromJson(
              Map<String, dynamic>.from(conversation),
            ),
          )
          .toList();
    } on FormatException {
      return <ChatConversation>[];
    }
  }

  Future<void> _writeConversations(List<ChatConversation> conversations) async {
    await _preferences.setString(
      _conversationKey,
      jsonEncode(
        conversations.map((conversation) => conversation.toJson()).toList(),
      ),
    );
  }
}
