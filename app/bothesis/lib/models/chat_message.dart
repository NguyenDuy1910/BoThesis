enum ChatMessageRole { assistant, user }

class ChatMessage {
  const ChatMessage({
    required this.role,
    required this.content,
    required this.createdAt,
  });

  final ChatMessageRole role;
  final String content;
  final DateTime createdAt;
}
