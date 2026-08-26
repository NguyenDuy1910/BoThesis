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
    if (items.isEmpty && !isStreaming) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final item in items)
          Padding(
            padding: EdgeInsets.only(bottom: item == items.last ? 0 : 8),
            child: switch (item.kind) {
              AssistantTurnItemKind.message => _MarkdownAnswer(text: item.text),
              AssistantTurnItemKind.tool => _ToolActivity(
                item: item,
                connectorLabel: connectorLabel,
              ),
              AssistantTurnItemKind.reasoning => _ReasoningActivity(item: item),
            },
          ),
        if (items.isEmpty && isStreaming)
          const _StatusLine(label: 'Analyzing…'),
      ],
    );
  }
}

class _MarkdownAnswer extends StatelessWidget {
  const _MarkdownAnswer({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final bodyStyle = Theme.of(context).textTheme.bodyLarge
        ?.copyWith(height: 1.65);
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
      connectorLabel,
    );
    final active = item.state == 'active';
    final error = item.state == 'error';
    return Semantics(
      liveRegion: active,
      label: presentation.label,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (active)
            const SizedBox(
              width: 14,
              height: 14,
              child: CircularProgressIndicator(strokeWidth: 1.8),
            )
          else
            Icon(
              error ? Icons.error_outline_rounded : Icons.check_rounded,
              size: 15,
              color: error ? context.colors.danger : context.colors.brand,
            ),
          const SizedBox(width: 7),
          Text(
            presentation.label,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: error
                  ? context.colors.danger
                  : context.colors.textSecondary,
              fontWeight: FontWeight.w500,
            ),
          ),
        ],
      ),
    );
  }
}

class _ReasoningActivity extends StatelessWidget {
  const _ReasoningActivity({required this.item});

  final AssistantTurnItem item;

  @override
  Widget build(BuildContext context) {
    if (item.state == 'active') return const _StatusLine(label: 'Thinking…');
    if (item.text.isEmpty) return const SizedBox.shrink();
    return Theme(
      data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
      child: ExpansionTile(
        tilePadding: EdgeInsets.zero,
        childrenPadding: const EdgeInsets.fromLTRB(0, 0, 0, 8),
        dense: true,
        visualDensity: VisualDensity.compact,
        leading: Icon(
          Icons.psychology_outlined,
          size: 17,
          color: context.colors.textMuted,
        ),
        title: Text(
          'Thought process',
          style: Theme.of(context).textTheme.bodySmall
              ?.copyWith(fontWeight: FontWeight.w500),
        ),
        children: [
          Align(
            alignment: Alignment.centerLeft,
            child: Text(
              item.text,
              style: Theme.of(context).textTheme.bodySmall
                  ?.copyWith(color: context.colors.textSecondary),
            ),
          ),
        ],
      ),
    );
  }
}

class _StatusLine extends StatelessWidget {
  const _StatusLine({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      liveRegion: true,
      label: label,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const SizedBox(
            width: 14,
            height: 14,
            child: CircularProgressIndicator(strokeWidth: 1.8),
          ),
          const SizedBox(width: 7),
          Text(label, style: Theme.of(context).textTheme.bodySmall),
        ],
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

({String label}) _toolPresentation(
  String name,
  String state,
  String? connectorLabel,
) {
  final completed = state == 'completed';
  if (name == 'knowledge_search') {
    return (
      label: state == 'error'
          ? 'Knowledge search could not complete'
          : completed
          ? 'Searched ${connectorLabel ?? 'knowledge'}'
          : 'Searching ${connectorLabel ?? 'knowledge'}…',
    );
  }
  if (name == 'sql_query') {
    return (
      label: state == 'error'
          ? 'Data query could not complete'
          : completed
          ? 'Queried data'
          : 'Querying data…',
    );
  }
  return (
    label: state == 'error'
        ? 'Tool could not complete'
        : completed
        ? 'Completed tool activity'
        : 'Running tool…',
  );
}
