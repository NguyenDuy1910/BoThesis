import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../features/chat/chat_page.dart';
import 'app_theme.dart';

class BoThesisApp extends StatefulWidget {
  const BoThesisApp({super.key});

  @override
  State<BoThesisApp> createState() => _BoThesisAppState();
}

class _BoThesisAppState extends State<BoThesisApp> {
  static const _themeKey = 'bothesis-theme';
  final _preferences = SharedPreferencesAsync();
  ThemeMode _themeMode = ThemeMode.system;

  @override
  void initState() {
    super.initState();
    _loadTheme();
  }

  Future<void> _loadTheme() async {
    final value = await _preferences.getString(_themeKey);
    if (!mounted) return;
    setState(() {
      _themeMode = switch (value) {
        'light' => ThemeMode.light,
        'dark' => ThemeMode.dark,
        _ => ThemeMode.system,
      };
    });
  }

  void _cycleTheme() {
    final next = switch (_themeMode) {
      ThemeMode.system => ThemeMode.light,
      ThemeMode.light => ThemeMode.dark,
      ThemeMode.dark => ThemeMode.system,
    };
    setState(() => _themeMode = next);
    _preferences.setString(_themeKey, next.name);
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'BoThesis',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light,
      darkTheme: AppTheme.dark,
      themeMode: _themeMode,
      home: ChatPage(themeMode: _themeMode, onCycleTheme: _cycleTheme),
    );
  }
}
