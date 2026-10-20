import 'package:flutter/material.dart';

class JColors {
  static const bg = Color(0xFF02060D);
  static const panel = Color(0xCC08142A);
  static const line = Color(0x2E00E5FF);
  static const cyan = Color(0xFF00E5FF);
  static const blue = Color(0xFF1E7BFF);
  static const text = Color(0xFFE6F6FF);
  static const muted = Color(0xFF7FA3BD);
  static const ok = Color(0xFF2EE6A6);
  static const warn = Color(0xFFFFC24B);
  static const err = Color(0xFFFF5470);
}

ThemeData jarvisTheme() {
  final base = ThemeData(brightness: Brightness.dark, useMaterial3: true);
  return base.copyWith(
    scaffoldBackgroundColor: JColors.bg,
    colorScheme: const ColorScheme.dark(primary: JColors.cyan, secondary: JColors.blue, surface: JColors.bg, error: JColors.err),
    appBarTheme: const AppBarTheme(backgroundColor: Colors.transparent, elevation: 0, centerTitle: false),
    cardTheme: CardThemeData(
      color: JColors.panel,
      elevation: 0,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14), side: const BorderSide(color: JColors.line)),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: const Color(0x9900101C),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: const BorderSide(color: JColors.line)),
      enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: const BorderSide(color: JColors.line)),
      focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: const BorderSide(color: JColors.cyan)),
    ),
    navigationBarTheme: const NavigationBarThemeData(backgroundColor: Color(0xF005101F), indicatorColor: Color(0x2200E5FF)),
  );
}

Color statusColor(String? s) => switch (s) {
      'succeeded' => JColors.ok,
      'running' => JColors.cyan,
      'approval_required' => JColors.warn,
      'failed' || 'cancelled' || 'offline' => JColors.err,
      _ => JColors.muted,
    };
