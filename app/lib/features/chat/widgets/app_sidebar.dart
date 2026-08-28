import 'package:flutter/material.dart';

import '../../../app/app_config.dart';
import '../../../app/app_theme.dart';
import '../models/chat_models.dart';
import '../state/chat_controller.dart';
import 'product_mark.dart';

class ChatSidebar extends StatefulWidget {
  const ChatSidebar({
    super.key,
    required this.controller,
    required this.collapsed,
    required this.themeMode,
    required this.onCycleTheme,
    this.onToggleCollapsed,
    this.onClose,
  });

  final ChatController controller;
  final bool collapsed;
  final ThemeMode themeMode;
  final VoidCallback onCycleTheme;
  final VoidCallback? onToggleCollapsed;
  final VoidCallback? onClose;

  @override
  State<ChatSidebar> createState() => _ChatSidebarState();
}

class _ChatSidebarState extends State<ChatSidebar> {
  final _searchController = TextEditingController();
  var _searchOpen = false;

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final collapsed = widget.collapsed;
    final query = _searchController.text.trim().toLowerCase();
    final conversations = widget.controller.conversations
        .where(
          (conversation) =>
              query.isEmpty || conversation.title.toLowerCase().contains(query),
        )
        .toList();
    return Material(
      color: colors.sidebar,
      child: SafeArea(
        right: false,
        child: Column(
          children: [
            SizedBox(
              height: 56,
              child: Padding(
                padding: EdgeInsets.symmetric(horizontal: collapsed ? 8 : 14),
                child: Row(
                  children: [
                    const ProductMark(),
                    if (!collapsed) ...[
                      const SizedBox(width: 9),
                      Expanded(
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'BoThesis',
                              style: Theme.of(context).textTheme.labelLarge,
                            ),
                            Text(
                              'Knowledge workspace',
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: Theme.of(context).textTheme.labelSmall
                                  ?.copyWith(
                                    color: colors.textMuted,
                                    fontFamily: 'monospace',
                                    fontSize: 10,
                                  ),
                            ),
                          ],
                        ),
                      ),
                    ] else
                      const Spacer(),
                    IconButton(
                      tooltip: widget.onClose != null
                          ? 'Close sidebar'
                          : collapsed
                          ? 'Expand sidebar'
                          : 'Collapse sidebar',
                      onPressed: widget.onClose ?? widget.onToggleCollapsed,
                      icon: Icon(
                        widget.onClose != null
                            ? Icons.close_rounded
                            : collapsed
                            ? Icons.view_sidebar_outlined
                            : Icons.view_sidebar_rounded,
                        size: 19,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            Divider(height: 1, color: colors.border),
            Padding(
              padding: EdgeInsets.fromLTRB(
                collapsed ? 8 : 12,
                10,
                collapsed ? 8 : 12,
                6,
              ),
              child: Column(
                children: [
                  _SidebarAction(
                    collapsed: collapsed,
                    active: widget.controller.activeConversationId == null,
                    icon: Icons.edit_square,
                    label: 'New chat',
                    onTap: () {
                      widget.controller.newChat();
                      widget.onClose?.call();
                    },
                  ),
                  const SizedBox(height: 4),
                  _SidebarAction(
                    collapsed: collapsed,
                    active: _searchOpen,
                    icon: Icons.search_rounded,
                    label: 'Search chats',
                    onTap: collapsed
                        ? widget.onToggleCollapsed
                        : () => setState(() => _searchOpen = !_searchOpen),
                  ),
                ],
              ),
            ),
            if (!collapsed && _searchOpen)
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 2, 12, 8),
                child: TextField(
                  controller: _searchController,
                  autofocus: true,
                  onChanged: (_) => setState(() {}),
                  decoration: InputDecoration(
                    hintText: 'Search chats…',
                    prefixIcon: const Icon(Icons.search_rounded, size: 18),
                    suffixIcon: IconButton(
                      tooltip: 'Close search',
                      onPressed: () {
                        _searchController.clear();
                        setState(() => _searchOpen = false);
                      },
                      icon: const Icon(Icons.close_rounded, size: 17),
                    ),
                  ),
                ),
              ),
            Expanded(
              child: widget.controller.isLoading
                  ? const Center(
                      child: SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                    )
                  : _ConversationList(
                      collapsed: collapsed,
                      conversations: conversations,
                      activeId: widget.controller.activeConversationId,
                      onSelect: (id) {
                        widget.controller.selectConversation(id);
                        widget.onClose?.call();
                      },
                      onRename: _rename,
                      onHide: _hide,
                    ),
            ),
            Divider(height: 1, color: colors.border),
            Padding(
              padding: EdgeInsets.all(collapsed ? 8 : 10),
              child: Column(
                children: [
                  if (!collapsed)
                    _SidebarAction(
                      collapsed: false,
                      icon: Icons.settings_outlined,
                      label: AppConfig.isConfigured
                          ? 'Workspace connected'
                          : 'Workspace not configured',
                      onTap: _showConnection,
                    ),
                  _SidebarAction(
                    collapsed: collapsed,
                    icon: _themeIcon(widget.themeMode),
                    label: 'Theme: ${widget.themeMode.name}',
                    onTap: widget.onCycleTheme,
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _rename(ChatConversation conversation) async {
    final input = TextEditingController(text: conversation.title);
    final result = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Rename conversation'),
        content: TextField(
          controller: input,
          autofocus: true,
          maxLength: 120,
          decoration: const InputDecoration(labelText: 'Name'),
          onSubmitted: (value) => Navigator.pop(context, value),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, input.text),
            child: const Text('Save'),
          ),
        ],
      ),
    );
    input.dispose();
    if (result?.trim().isNotEmpty == true) {
      await widget.controller.renameConversation(conversation.id, result!);
    }
  }

  Future<void> _hide(ChatConversation conversation) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Hide conversation?'),
        content: Text(
          'This will hide “${conversation.title}”. Its locally stored messages are retained.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton.tonal(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Hide'),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      await widget.controller.hideConversation(conversation.id);
    }
  }

  void _showConnection() {
    showModalBottomSheet<void>(
      context: context,
      builder: (context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 4, 20, 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Workspace connection',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 12),
              Text(AppConfig.apiBaseUrl),
              const SizedBox(height: 8),
              Text(
                AppConfig.isConfigured
                    ? 'Development identity headers are configured for this build.'
                    : 'Pass BOTHESIS_API_URL, BOTHESIS_TENANT_ID, and BOTHESIS_USER_ID with --dart-define.',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ConversationList extends StatelessWidget {
  const _ConversationList({
    required this.collapsed,
    required this.conversations,
    required this.activeId,
    required this.onSelect,
    required this.onRename,
    required this.onHide,
  });

  final bool collapsed;
  final List<ChatConversation> conversations;
  final String? activeId;
  final ValueChanged<String> onSelect;
  final ValueChanged<ChatConversation> onRename;
  final ValueChanged<ChatConversation> onHide;

  @override
  Widget build(BuildContext context) {
    if (conversations.isEmpty) {
      if (collapsed) return const SizedBox.shrink();
      return Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.forum_outlined, color: context.colors.textMuted),
            const SizedBox(height: 10),
            Text(
              'Start your first brief',
              style: Theme.of(context).textTheme.labelLarge,
            ),
            const SizedBox(height: 3),
            Text(
              'Your conversations will appear here.',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ),
      );
    }
    final groups = _groupConversations(conversations);
    return ListView(
      padding: EdgeInsets.fromLTRB(
        collapsed ? 8 : 12,
        2,
        collapsed ? 8 : 12,
        16,
      ),
      children: [
        for (final group in groups)
          if (group.conversations.isNotEmpty) ...[
            if (!collapsed)
              Padding(
                padding: const EdgeInsets.fromLTRB(8, 15, 8, 6),
                child: Text(
                  group.label.toUpperCase(),
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: context.colors.textMuted,
                    letterSpacing: 0.7,
                    fontSize: 10,
                  ),
                ),
              ),
            for (final conversation in group.conversations)
              _ConversationRow(
                collapsed: collapsed,
                conversation: conversation,
                active: conversation.id == activeId,
                onSelect: () => onSelect(conversation.id),
                onRename: () => onRename(conversation),
                onHide: () => onHide(conversation),
              ),
          ],
      ],
    );
  }
}

class _ConversationRow extends StatelessWidget {
  const _ConversationRow({
    required this.collapsed,
    required this.conversation,
    required this.active,
    required this.onSelect,
    required this.onRename,
    required this.onHide,
  });

  final bool collapsed;
  final ChatConversation conversation;
  final bool active;
  final VoidCallback onSelect;
  final VoidCallback onRename;
  final VoidCallback onHide;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Padding(
      padding: const EdgeInsets.only(bottom: 3),
      child: Material(
        color: active ? colors.surface : Colors.transparent,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(10),
          side: active ? BorderSide(color: colors.border) : BorderSide.none,
        ),
        clipBehavior: Clip.antiAlias,
        child: Row(
          children: [
            Expanded(
              child: InkWell(
                onTap: onSelect,
                child: Tooltip(
                  message: conversation.title,
                  child: SizedBox(
                    height: 44,
                    child: Padding(
                      padding: EdgeInsets.symmetric(
                        horizontal: collapsed ? 12 : 10,
                      ),
                      child: Row(
                        children: [
                          if (collapsed)
                            const Icon(
                              Icons.chat_bubble_outline_rounded,
                              size: 17,
                            )
                          else
                            Expanded(
                              child: Text(
                                _displayTitle(conversation.title),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: Theme.of(context).textTheme.bodyMedium
                                    ?.copyWith(
                                      fontWeight: active
                                          ? FontWeight.w600
                                          : FontWeight.w400,
                                    ),
                              ),
                            ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
            if (!collapsed)
              PopupMenuButton<String>(
                tooltip: 'Conversation actions',
                iconSize: 18,
                onSelected: (value) =>
                    value == 'rename' ? onRename() : onHide(),
                itemBuilder: (context) => const [
                  PopupMenuItem(value: 'rename', child: Text('Rename')),
                  PopupMenuItem(value: 'hide', child: Text('Hide')),
                ],
              ),
          ],
        ),
      ),
    );
  }
}

class _SidebarAction extends StatelessWidget {
  const _SidebarAction({
    required this.collapsed,
    required this.icon,
    required this.label,
    required this.onTap,
    this.active = false,
  });

  final bool collapsed;
  final IconData icon;
  final String label;
  final VoidCallback? onTap;
  final bool active;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Material(
      color: active ? colors.surface : Colors.transparent,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(10),
        side: active ? BorderSide(color: colors.border) : BorderSide.none,
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Tooltip(
          message: collapsed ? label : '',
          child: SizedBox(
            height: 44,
            child: Padding(
              padding: EdgeInsets.symmetric(horizontal: collapsed ? 12 : 10),
              child: Row(
                mainAxisAlignment: collapsed
                    ? MainAxisAlignment.center
                    : MainAxisAlignment.start,
                children: [
                  Icon(
                    icon,
                    size: 19,
                    color: active ? colors.textPrimary : colors.textSecondary,
                  ),
                  if (!collapsed) ...[
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        label,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _ConversationGroup {
  const _ConversationGroup(this.label, this.conversations);

  final String label;
  final List<ChatConversation> conversations;
}

List<_ConversationGroup> _groupConversations(List<ChatConversation> values) {
  final now = DateTime.now();
  final today = DateTime(now.year, now.month, now.day);
  final yesterday = today.subtract(const Duration(days: 1));
  final sevenDays = today.subtract(const Duration(days: 7));
  final thirtyDays = today.subtract(const Duration(days: 30));
  return [
    _ConversationGroup(
      'Recent',
      values.where((value) => !value.updatedAt.isBefore(yesterday)).toList(),
    ),
    _ConversationGroup(
      'Previous 7 days',
      values
          .where(
            (value) =>
                value.updatedAt.isBefore(yesterday) &&
                !value.updatedAt.isBefore(sevenDays),
          )
          .toList(),
    ),
    _ConversationGroup(
      'Previous 30 days',
      values
          .where(
            (value) =>
                value.updatedAt.isBefore(sevenDays) &&
                !value.updatedAt.isBefore(thirtyDays),
          )
          .toList(),
    ),
    _ConversationGroup(
      'Older',
      values.where((value) => value.updatedAt.isBefore(thirtyDays)).toList(),
    ),
  ];
}

String _displayTitle(String title) => title
    .replaceFirst(
      RegExp(
        r'^(please|can you|could you|help me|tell me|show me)\s+',
        caseSensitive: false,
      ),
      '',
    )
    .replaceFirst(RegExp(r'[?.!]+$'), '');

IconData _themeIcon(ThemeMode mode) => switch (mode) {
  ThemeMode.system => Icons.laptop_rounded,
  ThemeMode.light => Icons.light_mode_outlined,
  ThemeMode.dark => Icons.dark_mode_outlined,
};
