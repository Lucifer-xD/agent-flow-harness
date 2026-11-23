// Talking: it listens, thinks, answers out loud, and listens again.
import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../core/ai.dart';
import '../core/l10n.dart';
import '../core/runs.dart';
import '../core/store.dart';
import '../core/voice.dart';
import '../ui/kit.dart';
import '../ui/look.dart';
import '../ui/motion.dart';
import 'chat.dart';

class TalkScreen extends StatefulWidget {
  const TalkScreen(this.chat, {super.key});
  final Chat chat;
  @override
  State<TalkScreen> createState() => _TalkScreenState();
}

enum _S { idle, listening, thinking, speaking }

class _TalkScreenState extends State<TalkScreen> with SingleTickerProviderStateMixin {
  _S _s = _S.idle;
  String _said = '', _answer = '';
  String? _error;
  bool _over = false;
  int _silent = 0; // times in a row nothing was heard
  late final _wave = AnimationController(vsync: this, duration: const Duration(seconds: 3));
  Chat get c => widget.chat;

  @override
  void initState() {
    super.initState();
    Voice.i.addListener(_redraw);
    _listen();
  }

  void _redraw() => mounted ? setState(() {}) : null;

  @override
  void dispose() {
    _over = true;
    Voice.i.removeListener(_redraw);
    Voice.i.stopListening(cancel: true);
    Voice.i.hush();
    _wave.dispose();
    super.dispose();
  }

  void _set(_S s) {
    if (!mounted) return;
    setState(() => _s = s);
    s == _S.idle ? _wave.stop() : (_wave.isAnimating ? null : _wave.repeat());
  }

  Future<void> _listen() async {
    if (firstModel() == null) return setState(() => _error = t('Add a model first: You → Models.'));
    if (c.provider.isEmpty) {
      final m = firstModel()!;
      c.provider = m.$1;
      c.model = m.$2;
    }
    _error = null;
    _said = '';
    _set(_S.listening);
    final ok = await Voice.i.listen(onText: (s) => _said = s, onDone: _heard, pause: const Duration(seconds: 2));
    if (!ok && mounted) {
      _error = Voice.i.error;
      _set(_S.idle);
    }
  }

  Future<void> _heard(String text) async {
    if (_over || !mounted) return;
    if (text.trim().isEmpty) {
      if (Voice.i.error == null && ++_silent < 3) {
        // the phone gives up early on silence: keep listening a little longer
        await Future<void>.delayed(const Duration(milliseconds: 400));
        if (!_over && mounted && _s == _S.listening) return _listen();
        return;
      }
      _silent = 0;
      _error = Voice.i.error == null ? t('Nothing heard.') : t('The microphone stopped. Try again.');
      return _set(_S.idle);
    }
    _silent = 0;
    _said = text.trim();
    _answer = '';
    _set(_S.thinking);
    sendTo(c, _said, []);
    final run = Runs.i.of(c.id);
    if (run == null) return;
    void on() {
      if (!mounted) return;
      setState(() => _answer = run.msg.text);
    }

    run.addListener(on);
    while (!run.done && !_over) {
      await Future<void>.delayed(const Duration(milliseconds: 120));
    }
    run.removeListener(on);
    if (_over || !mounted) return;
    if (run.msg.error != null || run.msg.text.isEmpty) {
      _error = run.msg.error;
      return _set(_S.idle);
    }
    _answer = run.msg.text;
    _set(_S.speaking);
    await Voice.i.speak('talk', _answer);
    if (_over || !mounted || _s != _S.speaking) return;
    _listen();
  }

  Future<void> _tap() async {
    switch (_s) {
      case _S.idle:
        await _listen();
      case _S.listening:
        _silent = 9;
        await Voice.i.stopListening();
      case _S.thinking:
        Runs.i.of(c.id)?.stop();
        _set(_S.idle);
      case _S.speaking:
        _s = _S.idle;
        await Voice.i.hush();
        await _listen();
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final label = switch (_s) {
      _S.idle => t('Tap to talk'),
      _S.listening => t('Listening'),
      _S.thinking => t('Thinking'),
      _S.speaking => t('Tap to interrupt'),
    };
    final words = _s == _S.listening ? _said : (_answer.isEmpty ? _said : Voice.plain(_answer));
    return Scaffold(
      backgroundColor: p.bg,
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
              child: Row(
                children: [
                  const BackBtn(icon: LucideIcons.x),
                  Expanded(
                    child: Text(c.model.isEmpty ? '' : prettyModel(c.model), textAlign: TextAlign.center, style: T.label.copyWith(color: p.text2)),
                  ),
                  const SizedBox(width: 40),
                ],
              ),
            ),
            Expanded(
              child: Center(
                child: GestureDetector(
                  onTap: () {
                    Tap.mid();
                    _tap();
                  },
                  behavior: HitTestBehavior.opaque,
                  child: SizedBox(
                    width: 300,
                    height: 220,
                    child: CustomPaint(painter: _Strands(_wave, _s, Voice.i.level, p.fill2)),
                  ),
                ),
              ),
            ),
            SizedBox(
              height: 190,
              child: SingleChildScrollView(
                reverse: true,
                padding: const EdgeInsets.symmetric(horizontal: 30),
                child: Text(
                  _error ?? words,
                  textAlign: TextAlign.center,
                  textDirection: isRtl(words) ? TextDirection.rtl : TextDirection.ltr,
                  style: T.h2.copyWith(color: _error != null ? p.bad : (_s == _S.listening ? p.text : p.text2), fontWeight: FontWeight.w500, height: 1.45),
                ),
              ),
            ),
            const SizedBox(height: 20),
            Swap(
              child: Text(label, key: ValueKey(label), style: T.label.copyWith(color: p.text3)),
            ),
            const SizedBox(height: 18),
            Press(
              onTap: _tap,
              label: label,
              child: AnimatedContainer(
                duration: med,
                width: 68,
                height: 68,
                decoration: BoxDecoration(color: _s == _S.listening ? p.accent : p.inv, shape: BoxShape.circle),
                child: Swap(
                  child: Icon(
                    switch (_s) {
                      _S.idle => LucideIcons.mic,
                      _S.listening => LucideIcons.arrowUp,
                      _ => LucideIcons.square,
                    },
                    key: ValueKey(_s),
                    color: _s == _S.listening ? p.onAccent : p.onInv,
                    size: 26,
                  ),
                ),
              ),
            ),
            const SizedBox(height: 26),
          ],
        ),
      ),
    );
  }
}

/// The three strands: flat when idle, moving with your voice, braiding while it thinks and speaks.
class _Strands extends CustomPainter {
  _Strands(this.t, this.s, this.level, this.idle) : super(repaint: t);
  final Animation<double> t;
  final _S s;
  final double level;
  final Color idle;

  @override
  void paint(Canvas canvas, Size size) {
    final mid = size.height / 2;
    final amp = switch (s) {
      _S.idle => 0.0,
      _S.listening => 10 + 70 * level,
      _S.thinking => 26.0,
      _S.speaking => 46.0,
    };
    for (var i = 0; i < 3; i++) {
      final path = Path();
      for (var x = 0.0; x <= size.width; x += 3) {
        final k = x / size.width;
        final env = math.sin(k * math.pi);
        final ph = t.value * math.pi * 2 * (s == _S.thinking ? 2 : 3) + i * 2.1;
        final y = mid + (i - 1) * 11 * (1 - env * .6) + math.sin(k * math.pi * (s == _S.thinking ? 3 : 4) + ph) * amp * env * (1 - i * .16);
        x == 0 ? path.moveTo(x, y) : path.lineTo(x, y);
      }
      canvas.drawPath(
        path,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 5
          ..strokeCap = StrokeCap.round
          ..color = s == _S.idle ? Color.lerp(idle, strands[i], .35)! : strands[i].withValues(alpha: .92),
      );
    }
  }

  @override
  bool shouldRepaint(_Strands o) => true;
}
