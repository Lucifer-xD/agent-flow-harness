// AFH's look on the phone: warm near-black, the amber → pink gradient of the mark, Space Grotesk
// for headings and Inter for text.
import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

class Afh {
  static const bg = Color(0xFF0B0908);
  static const bg2 = Color(0xFF110D0B);
  static const surface = Color(0xFF17120F);
  static const surface2 = Color(0xFF201915);
  static const surface3 = Color(0xFF2A221D);
  static const line = Color(0x17FFECDE);
  static const line2 = Color(0x26FFECDE);
  static const text = Color(0xFFF6EFE9);
  static const text2 = Color(0xFFBDB0A5);
  static const text3 = Color(0xFF7F736A);
  static const amber = Color(0xFFFFB11F);
  static const orange = Color(0xFFFF6A2A);
  static const coral = Color(0xFFFF4A68);
  static const pink = Color(0xFFFF3D8A);
  static const magenta = Color(0xFFE0169A);
  static const good = Color(0xFF3DDC84);
  static const bad = Color(0xFFFF5C7A);

  static const grad = LinearGradient(begin: Alignment(-1, -0.6), end: Alignment(1, 0.6), colors: [amber, orange, pink, magenta], stops: [0, 0.4, 0.78, 1]);
  static const gradSoft = LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [Color(0x33FFB11F), Color(0x33FF3D8A)]);

  static const display = 'SpaceGrotesk';
  static const body = 'Inter';
  static const mono = 'JetBrainsMono';

  static const ease = Cubic(0.2, 0.8, 0.2, 1);
  static const spring = Cubic(0.34, 1.56, 0.64, 1);

  static TextStyle h1([Color c = text]) =>
      TextStyle(fontFamily: display, fontSize: 34, height: 1.05, fontWeight: FontWeight.w700, letterSpacing: -1.1, color: c);
  static TextStyle h2([Color c = text]) =>
      TextStyle(fontFamily: display, fontSize: 24, height: 1.1, fontWeight: FontWeight.w700, letterSpacing: -0.6, color: c);
  static TextStyle h3([Color c = text]) =>
      TextStyle(fontFamily: display, fontSize: 18, height: 1.2, fontWeight: FontWeight.w600, letterSpacing: -0.2, color: c);
  static const label = TextStyle(fontFamily: body, fontSize: 12, fontWeight: FontWeight.w600, letterSpacing: 1.1, color: text3);

  static ThemeData theme() {
    final scheme = ColorScheme.fromSeed(seedColor: orange, brightness: Brightness.dark).copyWith(
      primary: orange,
      onPrimary: const Color(0xFF1A0D05),
      secondary: pink,
      surface: bg,
      onSurface: text,
      surfaceContainerLowest: bg,
      surfaceContainerLow: surface,
      surfaceContainer: surface,
      surfaceContainerHigh: surface2,
      surfaceContainerHighest: surface3,
      outline: line2,
      outlineVariant: line,
      error: bad,
    );
    final base = ThemeData(useMaterial3: true, colorScheme: scheme, fontFamily: body, scaffoldBackgroundColor: bg, brightness: Brightness.dark);
    return base.copyWith(
      textTheme: base.textTheme.apply(bodyColor: text, displayColor: text, fontFamily: body),
      splashFactory: InkSparkle.splashFactory,
      appBarTheme: const AppBarTheme(
        backgroundColor: Colors.transparent,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        systemOverlayStyle: SystemUiOverlayStyle(
          statusBarColor: Colors.transparent,
          statusBarIconBrightness: Brightness.light,
          statusBarBrightness: Brightness.dark,
        ),
        titleTextStyle: TextStyle(fontFamily: display, fontSize: 19, fontWeight: FontWeight.w600, color: text, letterSpacing: -0.3),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: Colors.white.withValues(alpha: 0.045),
        hintStyle: const TextStyle(color: text3),
        labelStyle: const TextStyle(color: text2),
        contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: line),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: line),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: orange, width: 1.4),
        ),
      ),
      bottomSheetTheme: const BottomSheetThemeData(
        backgroundColor: surface,
        surfaceTintColor: Colors.transparent,
        showDragHandle: true,
        dragHandleColor: line2,
      ),
      dialogTheme: const DialogThemeData(backgroundColor: surface, surfaceTintColor: Colors.transparent),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        backgroundColor: surface3,
        contentTextStyle: const TextStyle(color: text, fontFamily: body),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      ),
      dividerTheme: const DividerThemeData(color: line, space: 1, thickness: 1),
      pageTransitionsTheme: const PageTransitionsTheme(
        builders: {
          TargetPlatform.android: FadeForwardsPageTransitionsBuilder(backgroundColor: bg),
          TargetPlatform.iOS: CupertinoPageTransitionsBuilder(),
        },
      ),
    );
  }
}
