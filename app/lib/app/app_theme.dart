import 'package:flutter/material.dart';

@immutable
class BoThesisColors extends ThemeExtension<BoThesisColors> {
  const BoThesisColors({
    required this.appBackground,
    required this.surface,
    required this.sidebar,
    required this.subtle,
    required this.hover,
    required this.selected,
    required this.border,
    required this.borderStrong,
    required this.textPrimary,
    required this.textSecondary,
    required this.textMuted,
    required this.brand,
    required this.brandHover,
    required this.brandSoft,
    required this.onBrand,
    required this.danger,
    required this.dangerSoft,
    required this.codeSurface,
    required this.codeText,
  });

  final Color appBackground;
  final Color surface;
  final Color sidebar;
  final Color subtle;
  final Color hover;
  final Color selected;
  final Color border;
  final Color borderStrong;
  final Color textPrimary;
  final Color textSecondary;
  final Color textMuted;
  final Color brand;
  final Color brandHover;
  final Color brandSoft;
  final Color onBrand;
  final Color danger;
  final Color dangerSoft;
  final Color codeSurface;
  final Color codeText;

  static const light = BoThesisColors(
    appBackground: Color(0xFFF7F7F6),
    surface: Color(0xFFFFFFFF),
    sidebar: Color(0xFFF3F3F1),
    subtle: Color(0xFFFAFAF9),
    hover: Color(0xFFECECEA),
    selected: Color(0xFFEEEEFF),
    border: Color(0x1A18181B),
    borderStrong: Color(0x2918181B),
    textPrimary: Color(0xFF18181B),
    textSecondary: Color(0xFF52525B),
    textMuted: Color(0xFF71717A),
    brand: Color(0xFF5B5BD6),
    brandHover: Color(0xFF4F46C8),
    brandSoft: Color(0xFFEEEEFF),
    onBrand: Color(0xFFFFFFFF),
    danger: Color(0xFFDC5252),
    dangerSoft: Color(0xFFFFF1F1),
    codeSurface: Color(0xFF18181B),
    codeText: Color(0xFFE4E4E7),
  );

  static const dark = BoThesisColors(
    appBackground: Color(0xFF111113),
    surface: Color(0xFF1A1A1E),
    sidebar: Color(0xFF151518),
    subtle: Color(0xFF222226),
    hover: Color(0xFF25252A),
    selected: Color(0xFF292943),
    border: Color(0x1AFFFFFF),
    borderStrong: Color(0x2BFFFFFF),
    textPrimary: Color(0xFFF4F4F5),
    textSecondary: Color(0xFFD4D4D8),
    textMuted: Color(0xFFA1A1AA),
    brand: Color(0xFF8B8BEA),
    brandHover: Color(0xFFA2A2F0),
    brandSoft: Color(0x26292943),
    onBrand: Color(0xFF111113),
    danger: Color(0xFFFF8A8A),
    dangerSoft: Color(0x1CFF8A8A),
    codeSurface: Color(0xFF09090B),
    codeText: Color(0xFFE4E4E7),
  );

  @override
  BoThesisColors copyWith() => this;

  @override
  BoThesisColors lerp(BoThesisColors? other, double t) =>
      t < 0.5 || other == null ? this : other;
}

abstract final class AppTheme {
  static ThemeData get light => _build(Brightness.light, BoThesisColors.light);
  static ThemeData get dark => _build(Brightness.dark, BoThesisColors.dark);

  static ThemeData _build(Brightness brightness, BoThesisColors colors) {
    final colorScheme = ColorScheme(
      brightness: brightness,
      primary: colors.brand,
      onPrimary: colors.onBrand,
      secondary: colors.brand,
      onSecondary: colors.onBrand,
      error: colors.danger,
      onError: brightness == Brightness.dark
          ? colors.textPrimary
          : Colors.white,
      surface: colors.surface,
      onSurface: colors.textPrimary,
      outline: colors.borderStrong,
      outlineVariant: colors.border,
      surfaceContainerHighest: colors.subtle,
    );
    final base = ThemeData(
      useMaterial3: true,
      brightness: brightness,
      colorScheme: colorScheme,
      scaffoldBackgroundColor: colors.appBackground,
      canvasColor: colors.surface,
      dividerColor: colors.border,
      extensions: <ThemeExtension<dynamic>>[colors],
    );
    return base.copyWith(
      textTheme: base.textTheme.copyWith(
        headlineSmall: TextStyle(
          color: colors.textPrimary,
          fontSize: 26,
          height: 1.2,
          fontWeight: FontWeight.w600,
          letterSpacing: -0.7,
        ),
        titleLarge: TextStyle(
          color: colors.textPrimary,
          fontSize: 18,
          height: 1.25,
          fontWeight: FontWeight.w600,
          letterSpacing: -0.25,
        ),
        titleMedium: TextStyle(
          color: colors.textPrimary,
          fontSize: 15,
          height: 1.35,
          fontWeight: FontWeight.w600,
        ),
        bodyLarge: TextStyle(
          color: colors.textPrimary,
          fontSize: 15,
          height: 1.58,
          letterSpacing: -0.05,
        ),
        bodyMedium: TextStyle(
          color: colors.textPrimary,
          fontSize: 14,
          height: 1.5,
        ),
        bodySmall: TextStyle(
          color: colors.textMuted,
          fontSize: 12,
          height: 1.45,
        ),
        labelLarge: TextStyle(
          color: colors.textPrimary,
          fontSize: 13,
          fontWeight: FontWeight.w600,
        ),
      ),
      appBarTheme: AppBarTheme(
        backgroundColor: colors.appBackground,
        foregroundColor: colors.textPrimary,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        scrolledUnderElevation: 0,
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: colors.subtle,
        hintStyle: TextStyle(color: colors.textMuted),
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 12,
          vertical: 10,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: BorderSide(color: colors.border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: BorderSide(color: colors.border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: BorderSide(color: colors.brand, width: 1.5),
        ),
      ),
      iconButtonTheme: IconButtonThemeData(
        style: IconButton.styleFrom(
          minimumSize: const Size(44, 44),
          foregroundColor: colors.textSecondary,
        ),
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: colors.surface,
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      ),
      bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: colors.surface,
        surfaceTintColor: Colors.transparent,
        showDragHandle: true,
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
        ),
      ),
    );
  }
}

extension BoThesisThemeContext on BuildContext {
  BoThesisColors get colors =>
      Theme.of(this).extension<BoThesisColors>() ?? BoThesisColors.light;
}
