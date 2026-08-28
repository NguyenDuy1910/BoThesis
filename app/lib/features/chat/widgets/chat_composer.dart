import 'dart:async';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../../../app/app_theme.dart';
import '../models/chat_models.dart';
import '../services/chat_service.dart';
import '../state/chat_controller.dart';

class ChatComposer extends StatefulWidget {
  const ChatComposer({super.key, required this.controller});

  final ChatController controller;

  @override
  State<ChatComposer> createState() => _ChatComposerState();
}

class _ChatComposerState extends State<ChatComposer> {
  static const _extensions = <String>[
    'avif',
    'bmp',
    'csv',
    'docx',
    'gif',
    'htm',
    'html',
    'jpeg',
    'jpg',
    'json',
    'jsonl',
    'log',
    'markdown',
    'md',
    'pdf',
    'png',
    'pptx',
    'rst',
    'sql',
    'tif',
    'tiff',
    'tsv',
    'txt',
    'webp',
    'xlsx',
    'xml',
    'yaml',
    'yml',
  ];

  final _textController = TextEditingController();
  final _focusNode = FocusNode();

  @override
  void dispose() {
    _textController.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final value = _textController.text;
    if (!widget.controller.canSend(value)) return;
    _textController.clear();
    setState(() {});
    unawaited(widget.controller.sendMessage(value));
  }

  Future<void> _pickFiles() async {
    final remaining = 12 - widget.controller.attachments.length;
    if (remaining <= 0) return;
    final result = await FilePicker.pickFiles(
      type: FileType.custom,
      allowedExtensions: _extensions,
    );
    if (result.isEmpty) return;
    for (final file in result.take(remaining)) {
      try {
        final bytes = await file.readAsBytes();
        unawaited(
          widget.controller.addAttachment(fileName: file.name, bytes: bytes),
        );
      } catch (_) {
        if (!mounted) return;
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('Could not read ${file.name}.')));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final controller = widget.controller;
    final colors = context.colors;
    final horizontal = MediaQuery.sizeOf(context).width < 600 ? 12.0 : 24.0;
    return SafeArea(
      top: false,
      minimum: EdgeInsets.fromLTRB(horizontal, 8, horizontal, 8),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 864),
            child: AnimatedContainer(
              duration: MediaQuery.disableAnimationsOf(context)
                  ? Duration.zero
                  : const Duration(milliseconds: 160),
              decoration: BoxDecoration(
                color: colors.surface,
                borderRadius: BorderRadius.circular(22),
                border: Border.all(
                  color: _focusNode.hasFocus ? colors.brand : colors.border,
                ),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withValues(
                      alpha: Theme.of(context).brightness == Brightness.dark
                          ? 0.34
                          : 0.07,
                    ),
                    blurRadius: 28,
                    offset: const Offset(0, 8),
                  ),
                ],
              ),
              padding: const EdgeInsets.fromLTRB(12, 10, 10, 10),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (controller.selectedConnectorIds.isNotEmpty &&
                      controller.connectorMode == ChatConnectorMode.selected)
                    Align(
                      alignment: Alignment.centerLeft,
                      child: Padding(
                        padding: const EdgeInsets.only(bottom: 7),
                        child: Wrap(
                          spacing: 6,
                          runSpacing: 6,
                          children: controller.selectedConnectors
                              .map(
                                (connector) => InputChip(
                                  avatar: const Icon(
                                    Icons.extension_outlined,
                                    size: 15,
                                  ),
                                  label: Text(connector.displayName),
                                  onDeleted: () =>
                                      controller.toggleConnector(connector.id),
                                  visualDensity: VisualDensity.compact,
                                ),
                              )
                              .toList(),
                        ),
                      ),
                    ),
                  if (controller.attachments.isNotEmpty)
                    Align(
                      alignment: Alignment.centerLeft,
                      child: Padding(
                        padding: const EdgeInsets.only(bottom: 7),
                        child: Wrap(
                          spacing: 6,
                          runSpacing: 6,
                          children: controller.attachments
                              .map(
                                (attachment) => _AttachmentChip(
                                  attachment: attachment,
                                  onRemove: () => controller.removeAttachment(
                                    attachment.key,
                                  ),
                                ),
                              )
                              .toList(),
                        ),
                      ),
                    ),
                  Semantics(
                    label: 'Message assistant',
                    textField: true,
                    child: TextField(
                      controller: _textController,
                      focusNode: _focusNode,
                      enabled: controller.isConfigured,
                      minLines: 1,
                      maxLines: 6,
                      textCapitalization: TextCapitalization.sentences,
                      keyboardType: TextInputType.multiline,
                      onChanged: (_) => setState(() {}),
                      onTap: () => setState(() {}),
                      decoration: const InputDecoration(
                        hintText: 'Ask about your company knowledge…',
                        filled: false,
                        border: InputBorder.none,
                        enabledBorder: InputBorder.none,
                        focusedBorder: InputBorder.none,
                        contentPadding: EdgeInsets.fromLTRB(3, 2, 3, 8),
                      ),
                      style: Theme.of(context).textTheme.bodyLarge,
                    ),
                  ),
                  Row(
                    children: [
                      _ComposerTool(
                        tooltip: 'Attach files',
                        icon: Icons.attach_file_rounded,
                        label: 'Attach',
                        enabled:
                            controller.isConfigured &&
                            controller.attachments.length < 12,
                        onTap: _pickFiles,
                      ),
                      const SizedBox(width: 4),
                      _ComposerTool(
                        tooltip: 'Choose knowledge sources',
                        icon: Icons.extension_outlined,
                        label: _sourceLabel(controller),
                        enabled:
                            controller.isConfigured && !controller.isGenerating,
                        onTap: () => _showSourcePicker(context),
                      ),
                      const Spacer(),
                      if (MediaQuery.sizeOf(context).width >= 700)
                        Padding(
                          padding: const EdgeInsets.only(right: 10),
                          child: Row(
                            children: [
                              Icon(
                                Icons.shield_outlined,
                                size: 14,
                                color: colors.brand,
                              ),
                              const SizedBox(width: 4),
                              Text(
                                'Permission-aware',
                                style: Theme.of(context).textTheme.labelSmall
                                    ?.copyWith(color: colors.brand),
                              ),
                            ],
                          ),
                        ),
                      SizedBox(
                        width: 44,
                        height: 44,
                        child: IconButton.filled(
                          tooltip: controller.isGenerating
                              ? 'Stop generating'
                              : 'Send message',
                          onPressed: controller.isGenerating
                              ? controller.stop
                              : controller.canSend(_textController.text)
                              ? _send
                              : null,
                          style: IconButton.styleFrom(
                            backgroundColor: controller.isGenerating
                                ? colors.textPrimary
                                : colors.brand,
                            foregroundColor: controller.isGenerating
                                ? colors.surface
                                : colors.onBrand,
                            disabledBackgroundColor: colors.subtle,
                            disabledForegroundColor: colors.textMuted,
                          ),
                          icon: Icon(
                            controller.isGenerating
                                ? Icons.stop_rounded
                                : Icons.arrow_upward_rounded,
                            size: controller.isGenerating ? 18 : 20,
                          ),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
          if (MediaQuery.sizeOf(context).width >= 600)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                'BoThesis can make mistakes. Verify important decisions with the cited sources.',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodySmall
                    ?.copyWith(fontSize: 11),
              ),
            ),
        ],
      ),
    );
  }

  Future<void> _showSourcePicker(BuildContext context) async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (context) => _SourcePicker(controller: widget.controller),
    );
  }
}

class _ComposerTool extends StatelessWidget {
  const _ComposerTool({
    required this.tooltip,
    required this.icon,
    required this.label,
    required this.enabled,
    required this.onTap,
  });

  final String tooltip;
  final IconData icon;
  final String label;
  final bool enabled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final compact = MediaQuery.sizeOf(context).width < 480;
    return Tooltip(
      message: tooltip,
      child: TextButton.icon(
        onPressed: enabled ? onTap : null,
        style: TextButton.styleFrom(
          minimumSize: const Size(44, 44),
          padding: EdgeInsets.symmetric(horizontal: compact ? 12 : 10),
          foregroundColor: context.colors.textSecondary,
          backgroundColor: context.colors.subtle,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(10),
          ),
        ),
        icon: Icon(icon, size: 17),
        label: compact ? const SizedBox.shrink() : Text(label),
      ),
    );
  }
}

class _AttachmentChip extends StatelessWidget {
  const _AttachmentChip({required this.attachment, required this.onRemove});

  final ComposerAttachment attachment;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    final active =
        attachment.progress != UploadProgress.ready &&
        attachment.progress != UploadProgress.failed;
    final failed = attachment.progress == UploadProgress.failed;
    return Container(
      constraints: const BoxConstraints(maxWidth: 260),
      decoration: BoxDecoration(
        color: failed ? context.colors.dangerSoft : context.colors.subtle,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: failed ? context.colors.danger : context.colors.border,
        ),
      ),
      padding: const EdgeInsets.only(left: 9),
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
              Icons.find_in_page_outlined,
              size: 16,
              color: failed ? context.colors.danger : context.colors.textMuted,
            ),
          const SizedBox(width: 6),
          Flexible(
            child: Text(
              attachment.fileName,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.labelSmall,
            ),
          ),
          IconButton(
            tooltip: 'Remove ${attachment.fileName}',
            onPressed: onRemove,
            visualDensity: VisualDensity.compact,
            icon: const Icon(Icons.close_rounded, size: 15),
          ),
        ],
      ),
    );
  }
}

class _SourcePicker extends StatelessWidget {
  const _SourcePicker({required this.controller});

  final ChatController controller;

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: controller,
      builder: (context, _) => SafeArea(
        child: ConstrainedBox(
          constraints: BoxConstraints(
            maxHeight: MediaQuery.sizeOf(context).height * 0.72,
          ),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 2, 20, 18),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Knowledge sources',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                const SizedBox(height: 4),
                Text(
                  'Choose what BoThesis may search for this conversation.',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                const SizedBox(height: 14),
                SizedBox(
                  width: double.infinity,
                  child: SegmentedButton<ChatConnectorMode>(
                    showSelectedIcon: false,
                    segments: const [
                      ButtonSegment(
                        value: ChatConnectorMode.auto,
                        label: Text('Auto'),
                      ),
                      ButtonSegment(
                        value: ChatConnectorMode.selected,
                        label: Text('Selected'),
                      ),
                      ButtonSegment(
                        value: ChatConnectorMode.off,
                        label: Text('Off'),
                      ),
                    ],
                    selected: <ChatConnectorMode>{controller.connectorMode},
                    onSelectionChanged: (selection) =>
                        controller.setConnectorMode(selection.first),
                  ),
                ),
                const SizedBox(height: 10),
                Text(switch (controller.connectorMode) {
                  ChatConnectorMode.auto => 'Search every permitted source when it helps answer the question.',
                  ChatConnectorMode.selected =>
                    'Search only the sources selected below.',
                  ChatConnectorMode.off =>
                    'Answer without searching workspace knowledge.',
                }, style: Theme.of(context).textTheme.bodySmall),
                if (controller.connectorMode == ChatConnectorMode.selected) ...[
                  const SizedBox(height: 10),
                  Flexible(child: _ConnectorList(controller: controller)),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ConnectorList extends StatelessWidget {
  const _ConnectorList({required this.controller});

  final ChatController controller;

  @override
  Widget build(BuildContext context) {
    if (controller.connectorsLoading) {
      return const Center(child: CircularProgressIndicator(strokeWidth: 2));
    }
    if (controller.connectorsError case final error?) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(error, textAlign: TextAlign.center),
            const SizedBox(height: 8),
            TextButton.icon(
              onPressed: controller.loadConnectors,
              icon: const Icon(Icons.refresh_rounded),
              label: const Text('Reload'),
            ),
          ],
        ),
      );
    }
    if (controller.connectors.isEmpty) {
      return const Center(child: Text('No permitted sources are available.'));
    }
    return ListView.builder(
      shrinkWrap: true,
      itemCount: controller.connectors.length,
      itemBuilder: (context, index) {
        final connector = controller.connectors[index];
        return CheckboxListTile(
          value: controller.selectedConnectorIds.contains(connector.id),
          onChanged: (_) => controller.toggleConnector(connector.id),
          controlAffinity: ListTileControlAffinity.trailing,
          secondary: const Icon(Icons.extension_outlined),
          title: Text(connector.displayName),
          subtitle: connector.capabilities.isEmpty
              ? null
              : Text(connector.capabilities.join(' · ')),
        );
      },
    );
  }
}

String _sourceLabel(ChatController controller) =>
    switch (controller.connectorMode) {
      ChatConnectorMode.auto => 'Auto',
      ChatConnectorMode.off => 'Off',
      ChatConnectorMode.selected =>
        controller.selectedConnectorIds.isEmpty
            ? 'Select'
            : '${controller.selectedConnectorIds.length}',
    };
