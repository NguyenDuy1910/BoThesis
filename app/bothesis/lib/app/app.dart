import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import 'routes.dart';

class BoThesisApp extends StatelessWidget {
  const BoThesisApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'BoThesis',
      theme: AppTheme.light,
      debugShowCheckedModeBanner: false,
      initialRoute: AppRoutes.bootstrap,
      onGenerateRoute: AppRoutes.onGenerateRoute,
    );
  }
}
