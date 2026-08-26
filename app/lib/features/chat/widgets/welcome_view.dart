import 'package:flutter/material.dart';

import '../../../app/app_theme.dart';
import 'product_mark.dart';

class WelcomeView extends StatelessWidget {
  const WelcomeView({super.key, required this.onSelect});

  final ValueChanged<String> onSelect;

  static const _suggestions = <_Suggestion>[
    _Suggestion(
      title: 'Executive briefing',
      description:
          'Summarize priorities, blockers, and source-backed decisions.',
      prompt: 'Summarize the latest executive priorities from the knowledge base with sources.',
      icon: Icons.manage_search_rounded,
    ),
    _Suggestion(
      title: 'Risk review',
      description: 'Surface exceptions, policy gaps, and operating signals.',
      prompt: 'What risks should leadership review this week, and what evidence supports them?',
      icon: Icons.bar_chart_rounded,
    ),
    _Suggestion(
      title: 'Decision memo',
      description:
          'Draft a concise memo from the most relevant internal context.',
      prompt: 'Draft a concise decision memo from the most relevant internal context.',
      icon: Icons.edit_note_rounded,
    ),
    _Suggestion(
      title: 'Source lookup',
      description: 'Find policy details, owners, and referenced documents.',
      prompt: 'Find policy details related to internal permissions and cite the source documents.',
      icon: Icons.fact_check_outlined,
    ),
  ];

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 28, 20, 40),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 720),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const ProductMark(size: 44),
              const SizedBox(height: 16),
              Text(
                'BOTHESIS WORKSPACE',
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: colors.textMuted,
                  fontFamily: 'monospace',
                  letterSpacing: 1.15,
                  fontWeight: FontWeight.w500,
                ),
              ),
              const SizedBox(height: 10),
              Text(
                'What can I help you understand?',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.headlineSmall,
              ),
              const SizedBox(height: 10),
              Text(
                'Ask across the company knowledge you can access, compare business signals, or turn trusted context into a clear next step.',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodyLarge
                    ?.copyWith(color: colors.textSecondary),
              ),
              const SizedBox(height: 14),
              Wrap(
                alignment: WrapAlignment.center,
                spacing: 18,
                runSpacing: 8,
                children: [
                  _TrustLabel(
                    icon: Icons.shield_outlined,
                    label: 'Searches only content you can access',
                  ),
                  _TrustLabel(
                    icon: Icons.find_in_page_outlined,
                    label: 'Keeps evidence with every answer',
                  ),
                ],
              ),
              const SizedBox(height: 30),
              Text(
                'TRY A STARTING POINT',
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: colors.textMuted,
                  fontFamily: 'monospace',
                  letterSpacing: 1.05,
                  fontWeight: FontWeight.w500,
                ),
              ),
              const SizedBox(height: 10),
              LayoutBuilder(
                builder: (context, constraints) {
                  final columns = constraints.maxWidth >= 600 ? 2 : 1;
                  final width = columns == 2
                      ? (constraints.maxWidth - 10) / 2
                      : constraints.maxWidth;
                  return Wrap(
                    spacing: 10,
                    runSpacing: 10,
                    children: _suggestions
                        .map(
                          (suggestion) => SizedBox(
                            width: width,
                            child: _SuggestionCard(
                              suggestion: suggestion,
                              onTap: () => onSelect(suggestion.prompt),
                            ),
                          ),
                        )
                        .toList(),
                  );
                },
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _TrustLabel extends StatelessWidget {
  const _TrustLabel({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 15, color: context.colors.brand),
        const SizedBox(width: 6),
        Text(
          label,
          style: Theme.of(context).textTheme.bodySmall
              ?.copyWith(color: context.colors.textMuted),
        ),
      ],
    );
  }
}

class _SuggestionCard extends StatelessWidget {
  const _SuggestionCard({required this.suggestion, required this.onTap});

  final _Suggestion suggestion;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Material(
      color: colors.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(color: colors.border),
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 78),
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Row(
              children: [
                Container(
                  width: 34,
                  height: 34,
                  decoration: BoxDecoration(
                    color: colors.brandSoft,
                    borderRadius: BorderRadius.circular(9),
                  ),
                  alignment: Alignment.center,
                  child: Icon(suggestion.icon, size: 18, color: colors.brand),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        suggestion.title,
                        style: Theme.of(context).textTheme.labelLarge,
                      ),
                      const SizedBox(height: 2),
                      Text(
                        suggestion.description,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _Suggestion {
  const _Suggestion({
    required this.title,
    required this.description,
    required this.prompt,
    required this.icon,
  });

  final String title;
  final String description;
  final String prompt;
  final IconData icon;
}
