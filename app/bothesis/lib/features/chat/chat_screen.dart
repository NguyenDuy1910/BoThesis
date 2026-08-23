import 'package:flutter/material.dart';

import '../../app/routes.dart';
import '../../models/chat_message.dart';
import '../../shared/widgets/app_navigation_bar.dart';
import 'widgets/chat_message_bubble.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _messageController = TextEditingController();
  final List<ChatMessage> _messages = [
    ChatMessage(
      role: ChatMessageRole.assistant,
      content: 'Welcome to BoThesis. Connect the chat endpoint to start grounded conversations.',
      createdAt: DateTime.now(),
    ),
  ];

  @override
  void dispose() {
    _messageController.dispose();
    super.dispose();
  }

  void _addDraftMessage() {
    final content = _messageController.text.trim();
    if (content.isEmpty) {
      return;
    }

    setState(() {
      _messages.add(
        ChatMessage(
          role: ChatMessageRole.user,
          content: content,
          createdAt: DateTime.now(),
        ),
      );
    });
    _messageController.clear();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('BoThesis'),
        actions: [
          IconButton(
            tooltip: 'Settings',
            onPressed: () =>
                Navigator.of(context).pushNamed(AppRoutes.settings),
            icon: const Icon(Icons.settings_outlined),
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: ListView.separated(
                padding: const EdgeInsets.fromLTRB(20, 16, 20, 12),
                itemCount: _messages.length,
                itemBuilder: (context, index) =>
                    ChatMessageBubble(message: _messages[index]),
                separatorBuilder: (_, _) => const SizedBox(height: 12),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 8, 20, 16),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _messageController,
                      minLines: 1,
                      maxLines: 4,
                      textCapitalization: TextCapitalization.sentences,
                      onSubmitted: (_) => _addDraftMessage(),
                      decoration: const InputDecoration(
                        hintText: 'Ask about your organization…',
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton.filled(
                    tooltip: 'Add message',
                    onPressed: _addDraftMessage,
                    icon: const Icon(Icons.arrow_upward_rounded),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
      bottomNavigationBar: const AppNavigationBar(currentIndex: 0),
    );
  }
}
