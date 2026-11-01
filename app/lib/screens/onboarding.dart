// First launch: three pages that show what the app does, each with its own small animation.
import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../store.dart';
import '../theme.dart';
import '../widgets/common.dart';
import '../widgets/logo.dart';
import 'home.dart';

class Onboarding extends StatefulWidget {
  const Onboarding({super.key});
  @override
  State<Onboarding> createState() => _OnboardingState();
}

class _OnboardingState extends State<Onboarding> {
  final _pages = PageController();
  double _page = 0;

  static const _copy = [
    ('AFH in your pocket', 'Chat with the best models from your phone, and take AFH on your computer with you wherever you go.'),
    ('Chat with any model', 'Sign in with ChatGPT or GitHub Copilot, or bring a key for any of 200+ providers. Your keys and your chats stay on this phone.'),
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
        transitionDuration: const Duration(milliseconds: 500),
        pageBuilder: (_, _, _) => const Home(),
        transitionsBuilder: (_, a, _, child) => FadeTransition(opacity: CurvedAnimation(parent: a, curve: Curves.easeOut), child: child),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final last = _page > 1.5;
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            SizedBox(
              height: 52,
              child: Align(
                alignment: Alignment.centerRight,
                child: AnimatedOpacity(
                  opacity: last ? 0 : 1,
                  duration: Afh.fast,
                  child: TextButton(
                    onPressed: last ? null : _finish,
                    child: Text('Skip', style: TextStyle(color: Afh.text2, fontWeight: FontWeight.w500)),
                  ),
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
                    opacity: (1 - off.abs() * 0.9).clamp(0.0, 1.0),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 28),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Expanded(
                            child: Center(
                              child: Transform.translate(offset: Offset(off * -50, 0), child: [const _Intro(), const _ChatArt(), const _RemoteArt()][i]),
                            ),
                          ),
                          Transform.translate(
                            offset: Offset(off * 30, 0),
                            child: Text(_copy[i].$1, style: Afh.h1().copyWith(fontSize: 32)),
                          ),
                          const SizedBox(height: 12),
                          Text(_copy[i].$2, style: TextStyle(fontSize: 16, height: 1.5, color: Afh.text2)),
                          const SizedBox(height: 28),
                        ],
                      ),
                    ),
                  );
                },
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(28, 0, 28, 0),
              child: Row(
                children: [
                  for (var i = 0; i < 3; i++)
                    AnimatedContainer(
                      duration: Afh.med,
                      curve: Afh.ease,
                      margin: const EdgeInsets.only(right: 6),
                      width: (_page.round() == i) ? 22 : 6,
                      height: 6,
                      decoration: BoxDecoration(color: _page.round() == i ? Afh.accent : Afh.line2, borderRadius: BorderRadius.circular(3)),
                    ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 22, 24, 16),
              child: PrimaryButton(
                label: last ? 'Get started' : 'Continue',
                icon: last ? LucideIcons.arrowRight : null,
                onTap: () => last ? _finish() : _pages.nextPage(duration: const Duration(milliseconds: 450), curve: Afh.ease),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Intro extends StatelessWidget {
  const _Intro();
  @override
  Widget build(BuildContext context) => const AfhLogo(width: 200, working: true);
}

/// A short chat that writes itself, one message after another.
class _ChatArt extends StatelessWidget {
  const _ChatArt();
  @override
  Widget build(BuildContext context) {
    Widget bubble(String text, bool me, int i) {
      final w = me
          ? Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              constraints: const BoxConstraints(maxWidth: 230),
              decoration: BoxDecoration(
                color: Afh.p.bubble,
                borderRadius: const BorderRadius.only(
                  topLeft: Radius.circular(18),
                  topRight: Radius.circular(18),
                  bottomLeft: Radius.circular(18),
                  bottomRight: Radius.circular(6),
                ),
              ),
              child: Text(text, style: TextStyle(color: Afh.text, fontSize: 14.5)),
            )
          : Container(
              constraints: const BoxConstraints(maxWidth: 260),
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Text(text, style: TextStyle(color: Afh.text2, fontSize: 14.5, height: 1.45)),
            );
      return Align(
        alignment: me ? Alignment.centerRight : Alignment.centerLeft,
        child: Padding(padding: const EdgeInsets.symmetric(vertical: 6), child: w),
      ).animate(delay: (300 + i * 600).ms).fadeIn(duration: 300.ms).moveY(begin: 10, end: 0, curve: Afh.ease, duration: 450.ms);
    }

    const colors = [Color(0xFF10A37F), Color(0xFFD97757), Color(0xFF4F8DF7), Color(0xFF8B7CF6)];
    const letters = ['O', 'A', 'G', 'R'];
    return SizedBox(
      width: 320,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              for (var i = 0; i < 4; i++)
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 5),
                  child: Avatar(letters[i], size: 36, color: colors[i]),
                ).animate(delay: (i * 80).ms).fadeIn().scale(begin: const Offset(0.8, 0.8), curve: Curves.easeOutBack),
            ],
          ),
          const SizedBox(height: 26),
          bubble('Explain black holes like I\'m five', true, 0),
          bubble('Imagine a vacuum cleaner so strong that even light can\'t escape it…', false, 1),
          bubble('Now in one sentence', true, 2),
        ],
      ),
    );
  }
}

/// A phone and a computer with a light running between them.
class _RemoteArt extends StatefulWidget {
  const _RemoteArt();
  @override
  State<_RemoteArt> createState() => _RemoteArtState();
}

class _RemoteArtState extends State<_RemoteArt> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1800))..repeat();
  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    Widget device(IconData icon, String label) => Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 76,
          height: 76,
          decoration: BoxDecoration(color: Afh.surface, borderRadius: BorderRadius.circular(22), border: Border.all(color: Afh.line)),
          child: Icon(icon, size: 32, color: Afh.text),
        ),
        const SizedBox(height: 10),
        Text(label, style: TextStyle(color: Afh.text2, fontWeight: FontWeight.w500, fontSize: 13.5)),
      ],
    );
    return SizedBox(
      width: 300,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              device(LucideIcons.smartphone, 'Phone'),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.only(bottom: 26),
                  child: SizedBox(
                    height: 12,
                    child: AnimatedBuilder(
                      animation: _c,
                      builder: (_, _) => CustomPaint(painter: _Link(_c.value, Afh.line2, Afh.accent)),
                    ),
                  ),
                ),
              ),
              device(LucideIcons.laptop, 'Your PC'),
            ],
          ),
          const SizedBox(height: 26),
          Container(
            width: 260,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: Afh.surface, borderRadius: BorderRadius.circular(14), border: Border.all(color: Afh.line)),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(child: Text('Fix website nav on mobile', style: TextStyle(fontWeight: FontWeight.w500, fontSize: 13.5, color: Afh.text))),
                    Pill('Needs you', color: Afh.warn),
                  ],
                ),
                const SizedBox(height: 6),
                Text('wants to run: npm test', style: TextStyle(fontFamily: Afh.mono, fontSize: 11.5, color: Afh.text3)),
                const SizedBox(height: 10),
                Row(
                  children: [
                    Container(
                      height: 28,
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      alignment: Alignment.center,
                      decoration: BoxDecoration(color: Afh.accent, borderRadius: BorderRadius.circular(8)),
                      child: Text('Allow', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: Afh.onAccent)),
                    ),
                    const SizedBox(width: 6),
                    Container(
                      height: 28,
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      alignment: Alignment.center,
                      decoration: BoxDecoration(borderRadius: BorderRadius.circular(8), border: Border.all(color: Afh.line2)),
                      child: Text('Deny', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w500, color: Afh.text)),
                    ),
                  ],
                ),
              ],
            ),
          ).animate(delay: 300.ms).fadeIn().moveY(begin: 10, end: 0, curve: Afh.ease),
        ],
      ),
    );
  }
}

class _Link extends CustomPainter {
  _Link(this.t, this.line, this.dot);
  final double t;
  final Color line, dot;
  @override
  void paint(Canvas canvas, Size size) {
    final y = size.height / 2;
    final dash = Paint()
      ..color = line
      ..strokeWidth = 1.5
      ..strokeCap = StrokeCap.round;
    for (var x = 10.0; x < size.width - 10; x += 8) {
      canvas.drawLine(Offset(x, y), Offset(x + 3, y), dash);
    }
    final x = 10 + (size.width - 20) * Curves.easeInOut.transform(t);
    canvas.drawCircle(Offset(x, y), 4, Paint()..color = dot);
  }

  @override
  bool shouldRepaint(_Link old) => old.t != t || old.dot != dot;
}
