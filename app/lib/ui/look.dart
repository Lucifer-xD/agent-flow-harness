// The look: colours, type and shape. Neutral surfaces with hairlines, one accent the user picks, and
// the three strand colours only where something is alive.
import 'dart:ui';

import 'package:flutter/cupertino.dart' show CupertinoPageTransitionsBuilder;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/l10n.dart';
import '../core/store.dart';

const strand1 = Color(0xFFFF3D8A), strand2 = Color(0xFFFF5F5A), strand3 = Color(0xFFFFA62B);
const strands = [strand1, strand2, strand3];

const accents = <String, (String, Color, Color)>{
  // id: (name, on dark, on light)
  'ember': ('Ember', Color(0xFFFF6A45), Color(0xFFE8482A)),
  'blue': ('Blue', Color(0xFF6C9BFF), Color(0xFF2F6BEA)),
  'violet': ('Violet', Color(0xFFA78BFA), Color(0xFF7047EB)),
  'mint': ('Mint', Color(0xFF3ED3A0), Color(0xFF0B8F66)),
  'rose': ('Rose', Color(0xFFFF6FA0), Color(0xFFD92F6A)),
  'amber': ('Amber', Color(0xFFF5B642), Color(0xFFB97800)),
  'mono': ('Mono', Color(0xFFEDEDF0), Color(0xFF1A1A1D)),
};

@immutable
class Pal {
  const Pal({
    required this.dark,
    required this.bg,
    required this.surface,
    required this.raised,
    required this.fill,
    required this.fill2,
    required this.line,
    required this.text,
    required this.text2,
    required this.text3,
    required this.accent,
    required this.good,
    required this.warn,
    required this.bad,
  });
  final bool dark;
  final Color bg, surface, raised, fill, fill2, line, text, text2, text3, accent, good, warn, bad;
  Color get inv => text;
  Color get onInv => dark ? const Color(0xFF0C0C0E) : const Color(0xFFFFFFFF);
  Color get onAccent => accent.computeLuminance() > .45 ? const Color(0xFF141416) : const Color(0xFFFFFFFF);
  Color get code => dark ? Color.lerp(bg, surface, .75)! : const Color(0xFFFAFAF8);
  Color tint(Color c) => c.withValues(alpha: dark ? .14 : .1);

  static Pal of(BuildContext c) => c.dependOnInheritedWidgetOfExactType<_Look>()!.pal;

  static Pal pick() {
    final s = Settings.i;
    final dark = switch (s.themeMode) {
      'dark' => true,
      'light' => false,
      _ => PlatformDispatcher.instance.platformBrightness == Brightness.dark,
    };
    final a = accents[s.accent] ?? accents['ember']!;
    if (!dark) {
      return Pal(
        dark: false,
        bg: const Color(0xFFF7F7F5),
        surface: const Color(0xFFFFFFFF),
        raised: const Color(0xFFFFFFFF),
        fill: const Color(0xFFEEEEEB),
        fill2: const Color(0xFFE3E3DF),
        line: const Color(0x14000000),
        text: const Color(0xFF161618),
        text2: const Color(0xFF5C5C64),
        text3: const Color(0xFF8E8E97),
        accent: a.$3,
        good: const Color(0xFF15875A),
        warn: const Color(0xFFB26A00),
        bad: const Color(0xFFD13438),
      );
    }
    final black = s.black;
    return Pal(
      dark: true,
      bg: black ? const Color(0xFF000000) : const Color(0xFF0C0C0E),
      surface: black ? const Color(0xFF0E0E10) : const Color(0xFF151518),
      raised: black ? const Color(0xFF131316) : const Color(0xFF1A1A1E),
      fill: black ? const Color(0xFF18181B) : const Color(0xFF1F1F24),
      fill2: const Color(0xFF2B2B32),
      line: const Color(0x13FFFFFF),
      text: const Color(0xFFF4F4F6),
      text2: const Color(0xFFA6A6B1),
      text3: const Color(0xFF73737F),
      accent: a.$2,
      good: const Color(0xFF45C98A),
      warn: const Color(0xFFF0B24A),
      bad: const Color(0xFFFF6B6B),
    );
  }

  static Pal lerp(Pal a, Pal b, double t) {
    Color c(Color x, Color y) => Color.lerp(x, y, t)!;
    return Pal(
      dark: t < .5 ? a.dark : b.dark,
      bg: c(a.bg, b.bg),
      surface: c(a.surface, b.surface),
      raised: c(a.raised, b.raised),
      fill: c(a.fill, b.fill),
      fill2: c(a.fill2, b.fill2),
      line: c(a.line, b.line),
      text: c(a.text, b.text),
      text2: c(a.text2, b.text2),
      text3: c(a.text3, b.text3),
      accent: c(a.accent, b.accent),
      good: c(a.good, b.good),
      warn: c(a.warn, b.warn),
      bad: c(a.bad, b.bad),
    );
  }

  @override
  bool operator ==(Object other) =>
      other is Pal && other.dark == dark && other.bg == bg && other.surface == surface && other.accent == accent && other.text == text && other.fill == fill && other.raised == raised;
  @override
  int get hashCode => Object.hash(dark, bg, surface, accent, text);
}

extension Ctx on BuildContext {
  Pal get p => Pal.of(this);
}

class _Look extends InheritedWidget {
  const _Look({required this.pal, required super.child});
  final Pal pal;
  @override
  bool updateShouldNotify(_Look old) => old.pal != pal;
}

/// Gives every screen the palette, and fades from one to the next when it changes.
class Look extends ImplicitlyAnimatedWidget {
  const Look({super.key, required this.pal, required this.child}) : super(duration: const Duration(milliseconds: 320), curve: Curves.easeOutCubic);
  final Pal pal;
  final Widget child;
  @override
  AnimatedWidgetBaseState<Look> createState() => _LookState();
}

class _PalTween extends Tween<Pal> {
  _PalTween({super.begin});
  @override
  Pal lerp(double t) => Pal.lerp(begin!, end!, t);
}

class _LookState extends AnimatedWidgetBaseState<Look> {
  _PalTween? _t;
  @override
  void forEachTween(TweenVisitor<dynamic> visitor) => _t = visitor(_t, widget.pal, (v) => _PalTween(begin: v as Pal)) as _PalTween?;
  @override
  Widget build(BuildContext context) {
    final pal = _t!.evaluate(animation);
    return _Look(
      pal: pal,
      child: AnnotatedRegion<SystemUiOverlayStyle>(value: overlay(pal), child: widget.child),
    );
  }
}

SystemUiOverlayStyle overlay(Pal p) => SystemUiOverlayStyle(
  statusBarColor: Colors.transparent,
  systemNavigationBarColor: Colors.transparent,
  systemNavigationBarContrastEnforced: false,
  statusBarIconBrightness: p.dark ? Brightness.light : Brightness.dark,
  statusBarBrightness: p.dark ? Brightness.dark : Brightness.light,
  systemNavigationBarIconBrightness: p.dark ? Brightness.light : Brightness.dark,
);

// ---- type ----

const mono = 'GeistMono';
const _fallback = ['PlexArabic'];

TextStyle _s(double size, FontWeight w, {double h = 1.3, double ls = 0}) =>
    TextStyle(fontFamily: arabic ? 'PlexArabic' : 'Geist', fontFamilyFallback: arabic ? const ['Geist'] : _fallback, fontSize: size, fontWeight: w, height: h, letterSpacing: arabic ? 0 : ls);

class T {
  static TextStyle get display => _s(32, FontWeight.w600, h: 1.12, ls: -1.1);
  static TextStyle get title => _s(24, FontWeight.w600, h: 1.2, ls: -.6);
  static TextStyle get h1 => _s(20, FontWeight.w600, h: 1.25, ls: -.4);
  static TextStyle get h2 => _s(17, FontWeight.w600, h: 1.3, ls: -.25);
  static TextStyle get h3 => _s(15.5, FontWeight.w600, h: 1.3, ls: -.15);
  static TextStyle get body => _s(16, FontWeight.w400, h: 1.55, ls: -.1);
  static TextStyle get row => _s(15.5, FontWeight.w500, h: 1.3, ls: -.12);
  static TextStyle get sub => _s(14, FontWeight.w400, h: 1.45, ls: -.05);
  static TextStyle get small => _s(13, FontWeight.w400, h: 1.4);
  static TextStyle get label => _s(13, FontWeight.w500, h: 1.3);
  static TextStyle get tiny => _s(11.5, FontWeight.w500, h: 1.3);
  static TextStyle get btn => _s(15.5, FontWeight.w600, h: 1.2, ls: -.1);
  static TextStyle get code => const TextStyle(fontFamily: mono, fontFamilyFallback: _fallback, fontSize: 13, height: 1.55, letterSpacing: -.2);
}

ThemeData themeData(Pal p) {
  final base = ThemeData(
    useMaterial3: true,
    brightness: p.dark ? Brightness.dark : Brightness.light,
    colorScheme: ColorScheme.fromSeed(
      seedColor: p.accent,
      brightness: p.dark ? Brightness.dark : Brightness.light,
    ).copyWith(primary: p.accent, surface: p.bg, onSurface: p.text, error: p.bad),
    scaffoldBackgroundColor: p.bg,
    canvasColor: p.bg,
    splashFactory: NoSplash.splashFactory,
    highlightColor: Colors.transparent,
    splashColor: Colors.transparent,
    hoverColor: Colors.transparent,
    fontFamily: arabic ? 'PlexArabic' : 'Geist',
    fontFamilyFallback: arabic ? const ['Geist'] : _fallback,
    pageTransitionsTheme: const PageTransitionsTheme(
      builders: {TargetPlatform.android: _SharedAxis(), TargetPlatform.iOS: CupertinoPageTransitionsBuilder()},
    ),
    textSelectionTheme: TextSelectionThemeData(cursorColor: p.accent, selectionColor: p.accent.withValues(alpha: .28), selectionHandleColor: p.accent),
  );
  return base.copyWith(
    textTheme: base.textTheme.apply(bodyColor: p.text, displayColor: p.text),
    sliderTheme: SliderThemeData(trackHeight: 4, tickMarkShape: SliderTickMarkShape.noTickMark, thumbColor: Colors.white, overlayColor: p.accent.withValues(alpha: .12), thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 10, elevation: 3)),
    scrollbarTheme: ScrollbarThemeData(thumbColor: WidgetStatePropertyAll(p.text3.withValues(alpha: .4)), thickness: const WidgetStatePropertyAll(3), radius: const Radius.circular(3)),
  );
}

/// Screens slide in along x while the one behind steps back and dims (Android; iPhone keeps its own).
class _SharedAxis extends PageTransitionsBuilder {
  const _SharedAxis();
  @override
  Duration get transitionDuration => const Duration(milliseconds: 380);
  @override
  Duration get reverseTransitionDuration => const Duration(milliseconds: 280);
  @override
  Widget buildTransitions<R>(PageRoute<R> route, BuildContext context, Animation<double> a, Animation<double> b, Widget child) {
    if (route.fullscreenDialog) {
      final c = CurvedAnimation(parent: a, curve: Curves.easeOutQuint, reverseCurve: Curves.easeInCubic);
      return SlideTransition(
        position: Tween(begin: const Offset(0, .12), end: Offset.zero).animate(c),
        child: FadeTransition(opacity: CurvedAnimation(parent: a, curve: const Interval(0, .5, curve: Curves.easeOut)), child: child),
      );
    }
    final back = Directionality.of(context) == TextDirection.rtl ? -1.0 : 1.0;
    final inn = CurvedAnimation(parent: a, curve: Curves.easeOutQuint, reverseCurve: Curves.easeInCubic);
    final out = CurvedAnimation(parent: b, curve: Curves.easeOutQuint, reverseCurve: Curves.easeInCubic);
    return SlideTransition(
      position: Tween(begin: Offset.zero, end: Offset(-.1 * back, 0)).animate(out),
      child: FadeTransition(
        opacity: Tween(begin: 1.0, end: .35).animate(out),
        child: SlideTransition(
          position: Tween(begin: Offset(.16 * back, 0), end: Offset.zero).animate(inn),
          child: FadeTransition(opacity: CurvedAnimation(parent: a, curve: const Interval(0, .45, curve: Curves.easeOut)), child: child),
        ),
      ),
    );
  }
}

Future<R?> go<R>(BuildContext context, Widget page, {bool over = false}) =>
    Navigator.of(context).push<R>(MaterialPageRoute(builder: (_) => page, fullscreenDialog: over));
