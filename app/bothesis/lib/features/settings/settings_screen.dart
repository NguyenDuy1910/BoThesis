import 'package:flutter/material.dart';

import '../../config/app_config.dart';
import '../../shared/widgets/app_navigation_bar.dart';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;

    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            Text('Connection', style: textTheme.titleMedium),
            const SizedBox(height: 12),
            Card(
              child: ListTile(
                leading: const Icon(Icons.dns_outlined),
                title: const Text('Backend base URL'),
                subtitle: Text(AppConfig.apiBaseUrl),
              ),
            ),
            const SizedBox(height: 8),
            Text(
              'Set BOTHESIS_API_BASE_URL with --dart-define when running or building the app.',
              style: textTheme.bodyMedium,
            ),
          ],
        ),
      ),
      bottomNavigationBar: const AppNavigationBar(currentIndex: 1),
    );
  }
}
