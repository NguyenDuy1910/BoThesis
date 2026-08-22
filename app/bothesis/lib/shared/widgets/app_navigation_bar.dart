import 'package:flutter/material.dart';

import '../../app/routes.dart';

class AppNavigationBar extends StatelessWidget {
  const AppNavigationBar({super.key, required this.currentIndex});

  final int currentIndex;

  @override
  Widget build(BuildContext context) {
    return NavigationBar(
      selectedIndex: currentIndex,
      onDestinationSelected: (index) {
        if (index == currentIndex) {
          return;
        }
        final destination = index == 0 ? AppRoutes.chat : AppRoutes.settings;
        Navigator.of(context).pushReplacementNamed(destination);
      },
      destinations: const [
        NavigationDestination(
          icon: Icon(Icons.forum_outlined),
          selectedIcon: Icon(Icons.forum),
          label: 'Chat',
        ),
        NavigationDestination(
          icon: Icon(Icons.settings_outlined),
          selectedIcon: Icon(Icons.settings),
          label: 'Settings',
        ),
      ],
    );
  }
}
