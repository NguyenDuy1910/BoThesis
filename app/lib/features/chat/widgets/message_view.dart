import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../app/app_theme.dart';
import '../models/chat_models.dart';
import '../state/chat_controller.dart';

class ChatMessageView extends StatefulWidget {
  const ChatMessageView({
    super.key,
    required this.message,
    required this.controller,
    required this.isStreaming,
  });

  final ChatMessage message;
  final ChatController controller;
  final bool isStreaming;

  @override
  State<ChatMessageView> createState() => _ChatMessageViewState();
}

class _ChatMessageViewState extends State<ChatMessageView> {
  var _copied = false;

  @override
  Widget build(BuildContext context) {
    if (widget.message.role == ChatRole.user) return _buildUser(context);
    return _buildAssistant(context);
  }

  Widget _buildUser(BuildContext context) {
    final colors = context.colors;
    return Align(
      alignment: Alignment.centerRight,
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: MediaQuery.sizeOf(context).width < 600
              ? MediaQuery.sizeOf(context).width * 0.9
              : 610,
        ),
        child: Container(
          decoration: BoxDecoration(
            color: colors.subtle,
            borderRadius: BorderRadius.circular(22),
            border: Border.all(color: colors.border),
          ),
          padding: const EdgeInsets.symmetric(horizontal: 17, vertical: 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (widget.message.documents.isNotEmpty) ...[
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: widget.message.documents
                      .map(
                        (document) => Container(
                          decoration: BoxDecoration(
                            color: colors.border,
                            borderRadius: BorderRadius.circular(9),
                          ),
                          padding: const EdgeInsets.symmetric(
                            horizontal: 8,
                            vertical: 5,
                          ),
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              const Icon(Icons.find_in_page_outlined, size: 15),
                              const SizedBox(width: 5),
                              Flexible(
                                child: Text(
                                  document.fileName,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: Theme.of(context).textTheme.labelSmall,
                                ),
                              ),
                            ],
                          ),
                        ),
                      )
                      .toList(),
                ),
                const SizedBox(height: 7),
              ],
              if (widget.message.text.isNotEmpty)
                SelectableText(
                  widget.message.text,
                  style: Theme.of(context).textTheme.bodyLarge,
                ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildAssistant(BuildContext context) {
    final turn = widget.message.turn;
    final text = widget.message.displayText;
    final settled = !widget.isStreaming;
    return Align(
      alignment: Alignment.centerLeft,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          AssistantTurnView(
            turn: turn,
            isStreaming: widget.isStreaming,
            connectorLabel: widget.controller.activityConnectorLabel,
          ),
          if (turn?.error case final error?) ...[
            const SizedBox(height: 8),
            _ErrorBox(message: error),
          ],
          if (settled && turn != null && turn.sources.isNotEmpty) ...[
            const SizedBox(height: 7),
            _AnswerSources(
              sources: turn.sources,
              onOpen: (source) => _openSource(source),
            ),
          ],
          if (settled && (text.isNotEmpty || turn?.error != null)) ...[
            const SizedBox(height: 4),
            Row(
              children: [
                if (text.isNotEmpty)
                  IconButton(
                    tooltip: _copied ? 'Copied' : 'Copy response',
                    onPressed: _copy,
                    icon: Icon(
                      _copied ? Icons.check_rounded : Icons.copy_all_outlined,
                      size: 18,
                    ),
                  ),
                TextButton.icon(
                  onPressed: () => unawaited(
                    widget.controller.regenerate(widget.message.id),
                  ),
                  icon: const Icon(Icons.refresh_rounded, size: 18),
                  label: turn?.error == null
                      ? const SizedBox.shrink()
                      : const Text('Retry'),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Future<void> _copy() async {
    await Clipboard.setData(ClipboardData(text: widget.message.displayText));
    if (!mounted) return;
    setState(() => _copied = true);
    await Future<void>.delayed(const Duration(seconds: 2));
    if (mounted) setState(() => _copied = false);
  }

  Future<void> _openSource(AnswerSource source) async {
    final uri = widget.controller.sourceUri(source);
    if (!await launchUrl(uri, mode: LaunchMode.externalApplication) &&
        mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Could not open this source.')),
      );
    }
  }
}

class AssistantTurnView extends StatelessWidget {
  const AssistantTurnView({
    super.key,
    required this.turn,
    required this.isStreaming,
    this.connectorLabel,
  });

  final ChatTurnState? turn;
  final bool isStreaming;
  final String? connectorLabel;

  @override
  Widget build(BuildContext context) {
    final items = turn?.presentationItems ?? const <AssistantTurnItem>[];
    final pending = isStreaming && (turn?.modelPending ?? false);
    if (items.isEmpty && !pending) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final item in items)
          Padding(
            padding: EdgeInsets.only(bottom: item == items.last ? 0 : 8),
            child: switch (item.kind) {
              AssistantTurnItemKind.message => _MarkdownAnswer(
                text: item.text,
                muted: item.phase == 'commentary',
              ),
              AssistantTurnItemKind.tool => _ToolActivity(
                item: item,
                connectorLabel: connectorLabel,
              ),
              AssistantTurnItemKind.reasoning => const SizedBox.shrink(),
            },
          ),
        if (pending) const _PendingIndicator(),
      ],
    );
  }
}

class _MarkdownAnswer extends StatelessWidget {
  const _MarkdownAnswer({required this.text, this.muted = false});

  final String text;
  final bool muted;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final bodyStyle = Theme.of(context).textTheme.bodyLarge
        ?.copyWith(height: 1.65, color: muted ? colors.textSecondary : null);
    return MarkdownBody(
      data: text,
      selectable: true,
      softLineBreak: true,
      onTapLink: (text, href, title) {
        final uri = href == null ? null : Uri.tryParse(href);
        if (uri != null && uri.hasScheme) {
          launchUrl(uri, mode: LaunchMode.externalApplication);
        }
      },
      styleSheet: MarkdownStyleSheet(
        p: bodyStyle,
        a: bodyStyle?.copyWith(
          color: colors.brand,
          decoration: TextDecoration.underline,
          decorationColor: colors.brand,
        ),
        strong: bodyStyle?.copyWith(fontWeight: FontWeight.w700),
        h1: Theme.of(context).textTheme.titleLarge?.copyWith(fontSize: 20),
        h2: Theme.of(context).textTheme.titleLarge?.copyWith(fontSize: 17),
        h3: Theme.of(context).textTheme.titleMedium,
        h1Padding: const EdgeInsets.only(top: 10, bottom: 6),
        h2Padding: const EdgeInsets.only(top: 9, bottom: 5),
        h3Padding: const EdgeInsets.only(top: 8, bottom: 4),
        blockSpacing: 10,
        listIndent: 22,
        blockquote: bodyStyle?.copyWith(
          color: colors.textSecondary,
          fontStyle: FontStyle.italic,
        ),
        blockquotePadding: const EdgeInsets.symmetric(
          horizontal: 12,
          vertical: 8,
        ),
        blockquoteDecoration: BoxDecoration(
          color: colors.subtle,
          border: Border(left: BorderSide(color: colors.brand, width: 3)),
          borderRadius: const BorderRadius.horizontal(
            right: Radius.circular(8),
          ),
        ),
        code: TextStyle(
          color: colors.codeText,
          backgroundColor: colors.codeSurface,
          fontFamily: 'monospace',
          fontSize: 13,
          height: 1.5,
        ),
        codeblockPadding: const EdgeInsets.all(14),
        codeblockDecoration: BoxDecoration(
          color: colors.codeSurface,
          borderRadius: BorderRadius.circular(12),
        ),
        tableHead: bodyStyle?.copyWith(fontWeight: FontWeight.w700),
        tableBody: bodyStyle?.copyWith(fontSize: 13),
        tableBorder: TableBorder.all(color: colors.borderStrong),
        tableCellsPadding: const EdgeInsets.all(8),
        horizontalRuleDecoration: BoxDecoration(
          border: Border(top: BorderSide(color: colors.border)),
        ),
      ),
    );
  }
}

class _ToolActivity extends StatelessWidget {
  const _ToolActivity({required this.item, this.connectorLabel});

  final AssistantTurnItem item;
  final String? connectorLabel;

  @override
  Widget build(BuildContext context) {
    final presentation = _toolPresentation(
      item.name,
      item.state,
      item.resultCount,
    );
    final active = item.state == 'active';
    final error = item.state == 'failed' || item.state == 'timeout';
    return Semantics(
      liveRegion: active,
      label: presentation.label,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            active
                ? Icons.circle_outlined
                : error
                ? Icons.error_outline_rounded
                : Icons.check_rounded,
            size: 15,
            color: error ? context.colors.danger : context.colors.textMuted,
          ),
          const SizedBox(width: 7),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                presentation.label,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: error
                      ? context.colors.danger
                      : context.colors.textSecondary,
                  fontWeight: FontWeight.w500,
                ),
              ),
              if (presentation.detail != null)
                Text(
                  presentation.detail!,
                  style: Theme.of(context).textTheme.labelSmall
                      ?.copyWith(color: context.colors.textMuted),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _PendingIndicator extends StatefulWidget {
  const _PendingIndicator();

  @override
  State<_PendingIndicator> createState() => _PendingIndicatorState();
}

class _PendingIndicatorState extends State<_PendingIndicator>
    with SingleTickerProviderStateMixin {
  var _visible = false;
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 2000),
  )..repeat(reverse: true);

  @override
  void initState() {
    super.initState();
    Future<void>.delayed(const Duration(milliseconds: 700), () {
      if (mounted) setState(() => _visible = true);
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!_visible) return const SizedBox(height: 18);
    return Semantics(
      liveRegion: true,
      label: 'BoThesis is working',
      child: FadeTransition(
        opacity: Tween<double>(begin: 0.25, end: 0.7).animate(
          CurvedAnimation(parent: _controller, curve: Curves.easeInOut),
        ),
        child: Text(
          'BoThesis',
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
            color: context.colors.textSecondary,
            fontWeight: FontWeight.w400,
          ),
        ),
      ),
    );
  }
}

class _AnswerSources extends StatelessWidget {
  const _AnswerSources({required this.sources, required this.onOpen});

  final List<AnswerSource> sources;
  final ValueChanged<AnswerSource> onOpen;

  @override
  Widget build(BuildContext context) {
    final label =
        '${sources.length} ${sources.length == 1 ? 'source' : 'sources'}';
    return Theme(
      data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
      child: ExpansionTile(
        tilePadding: EdgeInsets.zero,
        childrenPadding: const EdgeInsets.only(bottom: 8),
        dense: true,
        visualDensity: VisualDensity.compact,
        leading: Icon(
          Icons.library_books_outlined,
          size: 17,
          color: context.colors.textMuted,
        ),
        title: Text(label, style: Theme.of(context).textTheme.bodySmall),
        children: sources
            .map(
              (source) => ListTile(
                dense: true,
                contentPadding: const EdgeInsets.only(left: 6, right: 4),
                minLeadingWidth: 24,
                leading: const Icon(Icons.article_outlined, size: 17),
                title: Text(
                  source.title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
                subtitle: source.origin == null && source.locator == null
                    ? null
                    : Text(
                        <String?>[
                          source.origin,
                          source.locator,
                        ].whereType<String>().join(' · '),
                      ),
                trailing: const Icon(Icons.open_in_new_rounded, size: 16),
                onTap: () => onOpen(source),
              ),
            )
            .toList(),
      ),
    );
  }
}

class _ErrorBox extends StatelessWidget {
  const _ErrorBox({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: context.colors.dangerSoft,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: context.colors.danger.withValues(alpha: 0.38),
        ),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      child: Row(
        children: [
          Icon(
            Icons.error_outline_rounded,
            size: 18,
            color: context.colors.danger,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              message,
              style: Theme.of(context).textTheme.bodySmall
                  ?.copyWith(color: context.colors.danger),
            ),
          ),
        ],
      ),
    );
  }
}

({String label, String? detail}) _toolPresentation(
  String name,
  String state,
  int? resultCount,
) {
  final completed = state == 'completed';
  if (name == 'knowledge_search') {
    return (
      label: state == 'failed' || state == 'timeout'
          ? 'Không thể hoàn tất thao tác'
          : completed
          ? 'Đã tìm tài liệu liên quan'
          : 'Đang tìm tài liệu liên quan…',
      detail: completed && resultCount != null
          ? '$resultCount tài liệu phù hợp'
          : 'Đang kiểm tra các tài liệu phù hợp',
    );
  }
  const vocabulary =
      <String, ({String active, String completed, String detail})>{
        'read_resource': (
          active: 'Đang đọc tài liệu…',
          completed: 'Đã đọc tài liệu',
          detail: 'Đang đọc nội dung tài liệu',
        ),
        'inspect_resource': (
          active: 'Đang kiểm tra tài liệu…',
          completed: 'Đã kiểm tra tài liệu',
          detail: 'Đang xem thông tin tài liệu',
        ),
        'materialize_resource': (
          active: 'Đang chuẩn bị tài liệu…',
          completed: 'Đã chuẩn bị tài liệu',
          detail: 'Đang chuẩn bị nội dung để phân tích',
        ),
        'document_edit': (
          active: 'Đang chỉnh sửa tài liệu…',
          completed: 'Đã chỉnh sửa tài liệu',
          detail: 'Đang cập nhật nội dung tài liệu',
        ),
        'artifact_create': (
          active: 'Đang hoàn thiện tài liệu…',
          completed: 'Đã tạo tài liệu',
          detail: 'Đang tạo phiên bản tài liệu',
        ),
      };
  final text =
      vocabulary[name] ??
      (
        active: 'Đang xử lý yêu cầu…',
        completed: 'Đã hoàn tất thao tác',
        detail: 'Đang thực hiện thao tác cần thiết',
      );
  if (state == 'failed') {
    return (label: 'Không thể hoàn tất thao tác', detail: null);
  }
  if (state == 'timeout') {
    return (label: 'Thao tác mất quá nhiều thời gian', detail: null);
  }
  if (state == 'skipped') return (label: 'Đã bỏ qua thao tác', detail: null);
  return (
    label: completed ? text.completed : text.active,
    detail: completed ? null : text.detail,
  );
}
