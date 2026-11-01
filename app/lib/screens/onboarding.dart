// First launch: three pages that show what the app does, each with its own small animation.
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';

import '../store.dart';
import '../theme.dart';
import '../widgets/common.dart';
import '../widgets/logo.dart';
import 'shell.dart';

class Onboarding extends StatefulWidget {
  const Onboarding({super.key});
  @override
  State<Onboarding> createState() => _OnboardingState();
}

class _OnboardingState extends State<Onboarding> {
  final _pages = PageController();
  double _page = 0;

  static const _copy = [
    ('AFH in your pocket', 'Chat with the best models straight from your phone, and take AFH on your computer with you wherever you go.'),
    ('Chat with any model', 'Bring your own key for OpenAI, Anthropic, Gemini, OpenRouter and more. Your keys and your chats stay on this phone.'),
    ('Your PC, in your hand', 'Sign in with your AFH account to follow threads live, approve steps with a tap and start new tasks on your computer.'),
  ];

  @override
  void initState() {
    super.initState();
    _pages.addListener(() => setState(() => _page = _pages.page ?? 0));
  }

  @override
  void dispose() {
    _pages.dispose();
    super.dispose();
  }

  void _finish() {
    Settings.i.onboarded = true;
    Navigator.of(context).pushReplacement(
      PageRouteBuilder(
        transitionDuration: const Duration(milliseconds: 700),
        pageBuilder: (_, _, _) => const Shell(),
        transitionsBuilder: (_, a, _, child) => FadeTransition(
          opacity: CurvedAnimation(parent: a, curve: Curves.easeOut),
          child: ScaleTransition(
            scale: Tween(begin: 1.06, end: 1.0).animate(CurvedAnimation(parent: a, curve: Afh.ease)),
            child: child,
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final last = _page > 1.5;
    return Scaffold(
      body: Stack(
        children: [
          const Positioned.fill(child: Aurora(intensity: 1.2)),
          SafeArea(
            child: Column(
              children: [
                Align(
                  alignment: Alignment.centerRight,
                  child: AnimatedOpacity(
                    opacity: last ? 0 : 1,
                    duration: const Duration(milliseconds: 250),
                    child: TextButton(
                      onPressed: last ? null : _finish,
                      child: const Text('Skip', style: TextStyle(color: Afh.text2)),
                    ),
                  ),
                ),
                Expanded(
                  child: PageView.builder(
                    controller: _pages,
                    itemCount: 3,
                    itemBuilder: (_, i) {
                      final off = (_page - i).clamp(-1.0, 1.0);
                      return Opacity(
                        opacity: (1 - off.abs() * 0.8).clamp(0.0, 1.0),
                        child: Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 30),
                          child: Column(
                            children: [
                              Expanded(
                                child: Center(
                                  child: Transform.translate(
                                    offset: Offset(off * -60, 0),
                                    child: Transform.scale(scale: 1 - off.abs() * 0.15, child: [const _Intro(), const _ChatArt(), const _RemoteArt()][i]),
                                  ),
                                ),
                              ),
                              Transform.translate(
                                offset: Offset(off * 40, 0),
                                child: GradText(_copy[i].$1, style: Afh.h1().copyWith(fontSize: 36)),
                              ),
                              const SizedBox(height: 14),
                              Text(
                                _copy[i].$2,
                                textAlign: TextAlign.center,
                                style: const TextStyle(fontSize: 16, height: 1.5, color: Afh.text2),
                              ),
                              const SizedBox(height: 24),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
                ),
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    for (var i = 0; i < 3; i++)
                      AnimatedContainer(
                        duration: const Duration(milliseconds: 350),
                        curve: Afh.ease,
                        margin: const EdgeInsets.symmetric(horizontal: 4),
                        width: (_page.round() == i) ? 26 : 8,
                        height: 8,
                        decoration: BoxDecoration(
                          gradient: _page.round() == i ? Afh.grad : null,
                          color: _page.round() == i ? null : Afh.line2,
                          borderRadius: BorderRadius.circular(4),
                        ),
                      ),
                  ],
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(24, 26, 24, 20),
                  child: GradButton(
                    label: last ? 'Get started' : 'Next',
                    icon: last ? Icons.arrow_forward_rounded : null,
                    onTap: () => last ? _finish() : _pages.nextPage(duration: const Duration(milliseconds: 550), curve: Afh.ease),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _Intro extends StatelessWidget {
  const _Intro();
  @override
  Widget build(BuildContext context) {
    return Stack(
      alignment: Alignment.center,
      children: [
        Container(
              width: 230,
              height: 230,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                gradient: RadialGradient(colors: [Afh.pink.withValues(alpha: 0.28), Afh.pink.withValues(alpha: 0)]),
              ),
            )
            .animate(onPlay: (c) => c.repeat(reverse: true))
            .scale(begin: const Offset(0.85, 0.85), end: const Offset(1.1, 1.1), duration: 2600.ms, curve: Curves.easeInOut),
        const AfhLogo(width: 190, working: true),
      ],
    );
  }
}

/// Chat bubbles that pop in one after another, then start over.
class _ChatArt extends StatelessWidget {
  const _ChatArt();
  @override
  Widget build(BuildContext context) {
    Widget bubble(String text, bool me, int i) {
      return Align(
            alignment: me ? Alignment.centerRight : Alignment.centerLeft,
            child: Container(
              margin: const EdgeInsets.symmetric(vertical: 6),
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              constraints: const BoxConstraints(maxWidth: 240),
              decoration: BoxDecoration(
                gradient: me ? Afh.grad : null,
                color: me ? null : Afh.surface2,
                borderRadius: BorderRadius.only(
                  topLeft: const Radius.circular(20),
                  topRight: const Radius.circular(20),
                  bottomLeft: Radius.circular(me ? 20 : 6),
                  bottomRight: Radius.circular(me ? 6 : 20),
                ),
                border: me ? null : Border.all(color: Afh.line),
              ),
              child: Text(
                text,
                style: TextStyle(color: me ? const Color(0xFF1A0D05) : Afh.text, fontWeight: me ? FontWeight.w600 : FontWeight.w400, fontSize: 14.5),
              ),
            ),
          )
          .animate(delay: (i * 650).ms)
          .fadeIn(duration: 350.ms)
          .moveY(begin: 18, end: 0, curve: Afh.spring, duration: 600.ms)
          .scale(begin: const Offset(0.9, 0.9), curve: Afh.spring, duration: 600.ms);
    }

    return SizedBox(
      width: 320,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              for (final (i, c) in [(0, const Color(0xFF10A37F)), (1, const Color(0xFFD97757)), (2, const Color(0xFF4F8DF7)), (3, const Color(0xFF8B7CF6))])
                Container(
                  width: 38,
                  height: 38,
                  margin: const EdgeInsets.symmetric(horizontal: 5),
                  decoration: BoxDecoration(
                    color: c.withValues(alpha: 0.18),
                    shape: BoxShape.circle,
                    border: Border.all(color: c.withValues(alpha: 0.6)),
                  ),
                  child: Icon(Icons.auto_awesome_rounded, size: 18, color: c),
                ).animate(onPlay: (ctl) => ctl.repeat(reverse: true), delay: (i * 200).ms).moveY(begin: 0, end: -6, duration: 1200.ms, curve: Curves.easeInOut),
            ],
          ),
          const SizedBox(height: 22),
          bubble('Explain black holes like I\'m five', true, 0),
          bubble('Imagine a vacuum cleaner so strong that even light can\'t escape it…', false, 1),
          bubble('Now in one sentence 😄', true, 2),
        ],
      ),
    );
  }
}

/// A phone and a computer with light flowing between them.
class _RemoteArt extends StatefulWidget {
  const _RemoteArt();
  @override
  State<_RemoteArt> createState() => _RemoteArtState();
}

class _RemoteArtState extends State<_RemoteArt> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 2200))..repeat();
  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 320,
      height: 220,
      child: Stack(
        alignment: Alignment.center,
        children: [
          AnimatedBuilder(
            animation: _c,
            builder: (_, _) => CustomPaint(size: const Size(320, 220), painter: _FlowPainter(_c.value)),
          ),
          Positioned(
            left: 10,
            child: _device(Icons.phone_iphone_rounded, 'Phone', 80, 130).animate().fadeIn().moveX(begin: -20, end: 0, curve: Afh.ease, duration: 700.ms),
          ),
          Positioned(
            right: 0,
            child: _device(
              Icons.laptop_mac_rounded,
              'Your PC',
              120,
              100,
            ).animate().fadeIn(delay: 150.ms).moveX(begin: 20, end: 0, curve: Afh.ease, duration: 700.ms),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
            decoration: BoxDecoration(
              color: Afh.surface,
              borderRadius: BorderRadius.circular(999),
              border: Border.all(color: Afh.good.withValues(alpha: 0.4)),
            ),
            child: const Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                PulseDot(color: Afh.good, size: 7),
                SizedBox(width: 8),
                Text(
                  'Live',
                  style: TextStyle(fontWeight: FontWeight.w700, fontSize: 12.5, color: Afh.good),
                ),
              ],
            ),
          ).animate().scale(delay: 400.ms, curve: Afh.spring, duration: 600.ms),
        ],
      ),
    );
  }

  Widget _device(IconData icon, String label, double w, double h) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: w,
          height: h,
          decoration: BoxDecoration(
            gradient: Afh.gradSoft,
            borderRadius: BorderRadius.circular(22),
            border: Border.all(color: Afh.orange.withValues(alpha: 0.3)),
          ),
          child: Icon(icon, size: 44, color: const Color(0xFFFFB48A)),
        ),
        const SizedBox(height: 10),
        Text(
          label,
          style: const TextStyle(color: Afh.text2, fontWeight: FontWeight.w600),
        ),
      ],
    );
  }
}

class _FlowPainter extends CustomPainter {
  _FlowPainter(this.t);
  final double t;
  @override
  void paint(Canvas canvas, Size size) {
    final a = Offset(90, size.height / 2 - 14);
    final b = Offset(size.width - 120, size.height / 2 - 14);
    final path = Path()
      ..moveTo(a.dx, a.dy)
      ..cubicTo(a.dx + 50, a.dy - 50, b.dx - 50, b.dy - 50, b.dx, b.dy);
    canvas.drawPath(
      path,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2
        ..color = Afh.line2,
    );
    final back = Path()
      ..moveTo(b.dx, b.dy + 8)
      ..cubicTo(b.dx - 50, b.dy + 58, a.dx + 50, a.dy + 58, a.dx, a.dy + 8);
    canvas.drawPath(
      back,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2
        ..color = Afh.line2,
    );
    for (final (p, colors, shift) in [
      (path, [Afh.amber, Afh.orange], 0.0),
      (back, [Afh.pink, Afh.magenta], 0.5),
    ]) {
      final m = p.computeMetrics().first;
      for (var k = 0; k < 3; k++) {
        final at = ((t + shift + k / 3) % 1.0);
        final pos = m.getTangentForOffset(m.length * at)!.position;
        final r = 3.5 + 2 * math.sin(at * math.pi);
        canvas.drawCircle(pos, r * 2.4, Paint()..color = colors[0].withValues(alpha: 0.18));
        canvas.drawCircle(pos, r, Paint()..color = colors[k % 2]);
      }
    }
  }

  @override
  bool shouldRepaint(_FlowPainter old) => old.t != t;
}
