import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';

import '../../app/app_config.dart';
import '../../app/app_theme.dart';
import 'models/chat_models.dart';
import 'services/chat_service.dart';
import 'services/conversation_store.dart';
import 'state/chat_controller.dart';
import 'widgets/app_sidebar.dart';
import 'widgets/chat_composer.dart';
import 'widgets/message_view.dart';
import 'widgets/product_mark.dart';
import 'widgets/welcome_view.dart';

class ChatPage extends StatefulWidget {
  const ChatPage({
    super.key,
    required this.themeMode,
    required this.onCycleTheme,
  });

  final ThemeMode themeMode;
  final VoidCallback onCycleTheme;

  @override
  State<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends State<ChatPage> {
  final _scaffoldKey = GlobalKey<ScaffoldState>();
  final _scrollController = ScrollController();
  late final ChatController _controller;
  var _sidebarCollapsed = false;
  var _showJumpToLatest = false;
  var _stickToLatest = true;
  var _lastMessageCount = 0;

  @override
  void initState() {
    super.initState();
    _controller = ChatController(
      ChatService(),
      ConversationStore(userNamespace: AppConfig.userId),
    )..addListener(_onControllerChanged);
    _scrollController.addListener(_onScroll);
    unawaited(_controller.initialize());
  }

  @override
  void dispose() {
    _controller
      ..removeListener(_onControllerChanged)
      ..dispose();
    _scrollController
      ..removeListener(_onScroll)
      ..dispose();
    super.dispose();
  }

  void _onControllerChanged() {
    final countChanged = _lastMessageCount != _controller.messages.length;
    _lastMessageCount = _controller.messages.length;
    if ((_stickToLatest && _controller.isGenerating) || countChanged) {
      _scheduleScrollToLatest(animated: countChanged);
    }
  }

  void _onScroll() {
    if (!_scrollController.hasClients) return;
    final distance =
        _scrollController.position.maxScrollExtent -
        _scrollController.position.pixels;
    final show = distance > 140;
    _stickToLatest = distance < 96;
    if (show != _showJumpToLatest && mounted) {
      setState(() => _showJumpToLatest = show);
    }
  }

  void _scheduleScrollToLatest({required bool animated}) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_scrollController.hasClients) return;
      final target = _scrollController.position.maxScrollExtent;
      if (animated && !MediaQuery.disableAnimationsOf(context)) {
        _scrollController.animateTo(
          target,
          duration: const Duration(milliseconds: 220),
          curve: Curves.easeOutCubic,
        );
      } else {
        _scrollController.jumpTo(target);
      }
      _stickToLatest = true;
    });
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, _) => LayoutBuilder(
        builder: (context, constraints) {
          final desktop = constraints.maxWidth >= 900;
          final sidebarWidth = _sidebarCollapsed ? 64.0 : 268.0;
          return Scaffold(
            key: _scaffoldKey,
            resizeToAvoidBottomInset: true,
            drawer: desktop
                ? null
                : Drawer(
                    width: min(constraints.maxWidth * 0.88, 330),
                    shape: const RoundedRectangleBorder(),
                    child: ChatSidebar(
                      controller: _controller,
                      collapsed: false,
                      themeMode: widget.themeMode,
                      onCycleTheme: widget.onCycleTheme,
                      onClose: () => Navigator.of(context).pop(),
                    ),
                  ),
            body: Row(
              children: [
                if (desktop)
                  AnimatedContainer(
                    duration: MediaQuery.disableAnimationsOf(context)
                        ? Duration.zero
                        : const Duration(milliseconds: 180),
                    curve: Curves.easeOutCubic,
                    width: sidebarWidth,
                    decoration: BoxDecoration(
                      border: Border(
                        right: BorderSide(color: context.colors.border),
                      ),
                    ),
                    child: ChatSidebar(
                      controller: _controller,
                      collapsed: _sidebarCollapsed,
                      themeMode: widget.themeMode,
                      onCycleTheme: widget.onCycleTheme,
                      onToggleCollapsed: () => setState(
                        () => _sidebarCollapsed = !_sidebarCollapsed,
                      ),
                    ),
                  ),
                Expanded(child: _buildConversation(desktop)),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _buildConversation(bool desktop) {
    final colors = context.colors;
    return ColoredBox(
      color: colors.appBackground,
      child: SafeArea(
        left: false,
        right: false,
        bottom: false,
        child: Column(
          children: [
            Container(
              height: 56,
              padding: EdgeInsets.symmetric(horizontal: desktop ? 20 : 8),
              decoration: BoxDecoration(
                color: colors.appBackground.withValues(alpha: 0.94),
                border: Border(bottom: BorderSide(color: colors.border)),
              ),
              child: Row(
                children: [
                  if (!desktop)
                    IconButton(
                      tooltip: 'Open conversation sidebar',
                      onPressed: () => _scaffoldKey.currentState?.openDrawer(),
                      icon: const Icon(Icons.menu_rounded, size: 21),
                    ),
                  if (!desktop) ...[
                    const ProductMark(size: 30),
                    const SizedBox(width: 9),
                  ],
                  Expanded(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        if (desktop)
                          Text(
                            'KNOWLEDGE ASSISTANT',
                            style: Theme.of(context).textTheme.labelSmall
                                ?.copyWith(
                                  color: colors.textMuted,
                                  letterSpacing: 0.65,
                                  fontSize: 10,
                                ),
                          ),
                        Text(
                          _controller.conversationTitle,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                      ],
                    ),
                  ),
                  if (_controller.isGenerating)
                    Semantics(
                      liveRegion: true,
                      label: 'Assistant is working',
                      child: const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                    ),
                ],
              ),
            ),
            Expanded(
              child: Stack(
                children: [
                  if (_controller.isLoading)
                    const Center(
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  else if (_controller.messages.isEmpty)
                    WelcomeView(
                      onSelect: (prompt) =>
                          unawaited(_controller.sendMessage(prompt)),
                    )
                  else
                    ListView.separated(
                      controller: _scrollController,
                      keyboardDismissBehavior:
                          ScrollViewKeyboardDismissBehavior.onDrag,
                      padding: EdgeInsets.fromLTRB(
                        MediaQuery.sizeOf(context).width < 600 ? 14 : 24,
                        24,
                        MediaQuery.sizeOf(context).width < 600 ? 14 : 24,
                        26,
                      ),
                      itemCount: _controller.messages.length,
                      separatorBuilder: (_, _) => const SizedBox(height: 26),
                      itemBuilder: (context, index) {
                        final message = _controller.messages[index];
                        final isLast = index == _controller.messages.length - 1;
                        return Center(
                          child: ConstrainedBox(
                            constraints: const BoxConstraints(maxWidth: 864),
                            child: ChatMessageView(
                              key: ValueKey(message.id),
                              message: message,
                              controller: _controller,
                              isStreaming:
                                  isLast &&
                                  message.role == ChatRole.assistant &&
                                  _controller.isGenerating,
                            ),
                          ),
                        );
                      },
                    ),
                  if (_showJumpToLatest && _controller.messages.isNotEmpty)
                    Positioned(
                      right: 20,
                      bottom: 12,
                      child: FloatingActionButton.small(
                        tooltip: 'Jump to latest',
                        onPressed: () =>
                            _scheduleScrollToLatest(animated: true),
                        backgroundColor: colors.surface,
                        foregroundColor: colors.textSecondary,
                        child: const Icon(
                          Icons.arrow_downward_rounded,
                          size: 18,
                        ),
                      ),
                    ),
                ],
              ),
            ),
            if (_controller.error != null && !_controller.hasMessageError)
              Padding(
                padding: const EdgeInsets.fromLTRB(14, 0, 14, 6),
                child: _PageError(message: _controller.error!),
              ),
            if (!_controller.isConfigured)
              const Padding(
                padding: EdgeInsets.fromLTRB(14, 0, 14, 6),
                child: _PageError(
                  message: 'Chat is unavailable because workspace access has not been configured. Pass the API URL, tenant ID, and user ID when running the app.',
                ),
              ),
            ChatComposer(controller: _controller),
          ],
        ),
      ),
    );
  }
}

class _PageError extends StatelessWidget {
  const _PageError({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 864),
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
          decoration: BoxDecoration(
            color: context.colors.dangerSoft,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(
              color: context.colors.danger.withValues(alpha: 0.35),
            ),
          ),
          child: Text(
            message,
            style: Theme.of(context).textTheme.bodySmall
                ?.copyWith(color: context.colors.danger),
          ),
        ),
      ),
    );
  }
}
