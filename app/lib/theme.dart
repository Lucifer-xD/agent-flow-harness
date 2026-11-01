// AFH's look on the phone ("Studio"): calm and flat, one accent, hairline borders. The colours come
// from the same theme presets as AFH on the PC (palettes.dart), picked in Settings → Appearance.
import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'palettes.dart';

class Palette {
  const Palette({
    required this.id,
    required this.name,
    required this.dark,
    required this.accent,
    required this.bg,
    required this.side,
    required this.surface,
    required this.surface2,
    required this.surface3,
    required this.line,
    required this.line2,
    required this.text,
    required this.text2,
    required this.text3,
    required this.code,
  });
  final String id, name;
  final bool dark;
  final Color accent, bg, side, surface, surface2, surface3, line, line2, text, text2, text3;
  final Color code; // code block background

  /// Text and icons drawn on the accent: whichever of near-black or white reads better.
  Color get onAccent {
    final l = accent.computeLuminance();
    return (l + 0.05) / 0.05 >= 1.05 / (l + 0.05) ? Color.lerp(accent, const Color(0xFF000000), 0.86)! : const Color(0xFFFFFFFF);
  }

  /// The user's message bubble: the accent washed into the surface.
  Color get bubble => Color.lerp(surface2, accent, dark ? 0.17 : 0.13)!;

  /// A faint accent tint for selected rows and chips.
  Color get tint => accent.withValues(alpha: dark ? 0.13 : 0.10);

  static Palette byId(String? id, {required bool dark}) =>
      palettes.firstWhere((p) => p.id == id && p.dark == dark, orElse: () => palettes.firstWhere((p) => p.dark == dark));
}

class Afh {
  static Palette p = Palette.byId('sunset', dark: true);

  static Color get bg => p.bg;
  static Color get bg2 => p.side;
  static Color get surface => p.surface;
  static Color get surface2 => p.surface2;
  static Color get surface3 => p.surface3;
  static Color get line => p.line;
  static Color get line2 => p.line2;
  static Color get text => p.text;
  static Color get text2 => p.text2;
  static Color get text3 => p.text3;
  static Color get accent => p.accent;
  static Color get onAccent => p.onAccent;
  static Color get tint => p.tint;
  static Color get good => p.dark ? const Color(0xFF3DDC84) : const Color(0xFF16934F);
  static Color get warn => p.dark ? const Color(0xFFFFC24D) : const Color(0xFFB7701A);
  static Color get bad => p.dark ? const Color(0xFFFF5C7A) : const Color(0xFFD3264A);

  static const display = 'SpaceGrotesk';
  static const body = 'Inter';
  static const mono = 'JetBrainsMono';

  static const ease = Cubic(0.2, 0.8, 0.2, 1);
  static const spring = Cubic(0.34, 1.56, 0.64, 1);
  static const fast = Duration(milliseconds: 160);
  static const med = Duration(milliseconds: 260);

  static const r = 14.0; // cards, rows
  static const rSm = 10.0; // chips, small buttons
  static const rLg = 22.0; // composer, sheets

  static BorderSide get hair => BorderSide(color: line);
  static Border get hairBorder => Border.all(color: line);

  static TextStyle h1([Color? c]) =>
      TextStyle(fontFamily: display, fontSize: 30, height: 1.1, fontWeight: FontWeight.w600, letterSpacing: -0.8, color: c ?? text);
  static TextStyle h2([Color? c]) =>
      TextStyle(fontFamily: display, fontSize: 22, height: 1.15, fontWeight: FontWeight.w600, letterSpacing: -0.4, color: c ?? text);
  static TextStyle h3([Color? c]) =>
      TextStyle(fontFamily: display, fontSize: 17, height: 1.25, fontWeight: FontWeight.w600, letterSpacing: -0.2, color: c ?? text);
  static TextStyle get label => TextStyle(fontFamily: body, fontSize: 11.5, fontWeight: FontWeight.w600, letterSpacing: 0.6, color: text3);
  static TextStyle get bodyText => TextStyle(fontFamily: body, fontSize: 15, height: 1.45, color: text);
  static TextStyle get small => TextStyle(fontFamily: body, fontSize: 13, height: 1.35, color: text2);

  static SystemUiOverlayStyle get overlay => SystemUiOverlayStyle(
    statusBarColor: Colors.transparent,
    statusBarIconBrightness: p.dark ? Brightness.light : Brightness.dark,
    statusBarBrightness: p.dark ? Brightness.dark : Brightness.light,
    systemNavigationBarColor: Colors.transparent,
    systemNavigationBarIconBrightness: p.dark ? Brightness.light : Brightness.dark,
    systemNavigationBarContrastEnforced: false,
  );

  static ThemeData theme() {
    final brightness = p.dark ? Brightness.dark : Brightness.light;
    final scheme = ColorScheme.fromSeed(seedColor: accent, brightness: brightness).copyWith(
      primary: accent,
      onPrimary: onAccent,
      secondary: accent,
      onSecondary: onAccent,
      surface: bg,
      onSurface: text,
      onSurfaceVariant: text2,
      surfaceContainerLowest: bg,
      surfaceContainerLow: surface,
      surfaceContainer: surface,
      surfaceContainerHigh: surface2,
      surfaceContainerHighest: surface3,
      outline: line2,
      outlineVariant: line,
      error: bad,
      surfaceTint: Colors.transparent,
    );
    final base = ThemeData(useMaterial3: true, colorScheme: scheme, fontFamily: body, scaffoldBackgroundColor: bg, brightness: brightness);
    final input = OutlineInputBorder(borderRadius: BorderRadius.circular(r), borderSide: BorderSide(color: line));
    return base.copyWith(
      textTheme: base.textTheme.apply(bodyColor: text, displayColor: text, fontFamily: body),
      splashFactory: InkRipple.splashFactory,
      highlightColor: text.withValues(alpha: 0.04),
      splashColor: text.withValues(alpha: 0.06),
      iconTheme: IconThemeData(color: text2, size: 20),
      textSelectionTheme: TextSelectionThemeData(
        cursorColor: accent,
        selectionColor: accent.withValues(alpha: 0.3),
        selectionHandleColor: accent,
      ),
      appBarTheme: AppBarTheme(
        backgroundColor: bg,
        surfaceTintColor: Colors.transparent,
        foregroundColor: text,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: true,
        toolbarHeight: 52,
        systemOverlayStyle: overlay,
        iconTheme: IconThemeData(color: text, size: 21),
        titleTextStyle: TextStyle(fontFamily: body, fontSize: 16, fontWeight: FontWeight.w600, color: text, letterSpacing: -0.1),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: surface,
        hintStyle: TextStyle(color: text3),
        labelStyle: TextStyle(color: text2),
        floatingLabelStyle: TextStyle(color: accent),
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        border: input,
        enabledBorder: input,
        focusedBorder: input.copyWith(borderSide: BorderSide(color: accent, width: 1.3)),
      ),
      bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: surface,
        modalBackgroundColor: surface,
        surfaceTintColor: Colors.transparent,
        showDragHandle: true,
        dragHandleColor: line2,
        dragHandleSize: const Size(36, 4),
        shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(rLg))),
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: surface,
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(rLg), side: BorderSide(color: line)),
        titleTextStyle: h3(),
        contentTextStyle: TextStyle(fontFamily: body, fontSize: 14.5, height: 1.45, color: text2),
      ),
      popupMenuTheme: PopupMenuThemeData(
        color: surface2,
        surfaceTintColor: Colors.transparent,
        elevation: 8,
        shadowColor: Colors.black.withValues(alpha: p.dark ? 0.5 : 0.15),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(r), side: BorderSide(color: line)),
        textStyle: TextStyle(fontFamily: body, fontSize: 14.5, color: text),
      ),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        backgroundColor: p.dark ? surface3 : const Color(0xFF1E1E22),
        contentTextStyle: TextStyle(color: p.dark ? text : Colors.white, fontFamily: body, fontSize: 14),
        actionTextColor: accent,
        elevation: 0,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(r)),
      ),
      switchTheme: SwitchThemeData(
        thumbColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? onAccent : text3),
        trackColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? accent : surface3),
        trackOutlineColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? accent : line2),
      ),
      progressIndicatorTheme: ProgressIndicatorThemeData(color: accent, linearTrackColor: surface3, circularTrackColor: Colors.transparent),
      dividerTheme: DividerThemeData(color: line, space: 1, thickness: 1),
      tooltipTheme: TooltipThemeData(
        decoration: BoxDecoration(color: surface3, borderRadius: BorderRadius.circular(8)),
        textStyle: TextStyle(color: text, fontSize: 12.5),
      ),
      pageTransitionsTheme: PageTransitionsTheme(
        builders: {
          TargetPlatform.android: FadeForwardsPageTransitionsBuilder(backgroundColor: bg),
          TargetPlatform.iOS: const CupertinoPageTransitionsBuilder(),
        },
      ),
    );
  }
}
