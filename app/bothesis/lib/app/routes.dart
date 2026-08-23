import 'package:flutter/material.dart';

import '../features/bootstrap/bootstrap_screen.dart';
import '../features/chat/chat_screen.dart';
import '../features/settings/settings_screen.dart';

abstract final class AppRoutes {
  static const bootstrap = '/';
  static const chat = '/chat';
  static const settings = '/settings';

  static Route<void> onGenerateRoute(RouteSettings settings) {
    final Widget page = switch (settings.name) {
      AppRoutes.bootstrap => const BootstrapScreen(),
      AppRoutes.settings => const SettingsScreen(),
      _ => const ChatScreen(),
    };

    return MaterialPageRoute<void>(builder: (_) => page, settings: settings);
  }
}
