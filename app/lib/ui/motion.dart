// How things move: one press feel, one way to arrive, and the strand line that shows work is alive.
// Nothing here moves on its own unless something is really happening.
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/store.dart';
import 'look.dart';

class Tap {
  static void _do(Future<void> Function() f) {
    if (Settings.i.haptics) f();
  }

  static void tick() => _do(HapticFeedback.selectionClick);
  static void light() => _do(HapticFeedback.lightImpact);
  static void mid() => _do(HapticFeedback.mediumImpact);
  static void heavy() => _do(HapticFeedback.heavyImpact);
}

bool calmOf(BuildContext c) => Settings.i.calm || MediaQuery.disableAnimationsOf(c);

/// A soft spring that settles with a small overshoot.
class Spring extends Curve {
  const Spring([this.damping = .72, this.freq = 9]);
  final double damping, freq;
  @override
  double transformInternal(double t) {
    final wd = freq * math.sqrt(1 - damping * damping);
    final e = math.exp(-damping * freq * t);
    return 1 - e * (math.cos(wd * t) + damping * freq / wd * math.sin(wd * t));
  }
}

const spring = Spring();
const springy = Spring(.55, 10);
const quick = Duration(milliseconds: 160);
const med = Duration(milliseconds: 280);
const slow = Duration(milliseconds: 460);

/// Sinks a little under the finger and springs back.
class Press extends StatefulWidget {
  const Press({super.key, required this.child, this.onTap, this.onLong, this.scale = .965, this.haptic = true, this.label, this.dim = true});
  final Widget child;
  final VoidCallback? onTap, onLong;
  final double scale;
  final bool haptic, dim;
  final String? label;

  @override
  State<Press> createState() => _PressState();
}

class _PressState extends State<Press> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 90), reverseDuration: const Duration(milliseconds: 380));
  bool _down = false;

  void _set(bool v) {
    if (_down == v || !mounted) return;
    _down = v;
    v ? _c.forward() : _c.reverse();
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final off = widget.onTap == null && widget.onLong == null;
    final child = AnimatedBuilder(
      animation: _c,
      child: widget.child,
      builder: (_, child) {
        final v = _down ? Curves.easeOut.transform(_c.value) : 1 - springy.transform(1 - _c.value);
        return Transform.scale(
          scale: 1 - (1 - widget.scale) * v,
          child: widget.dim ? Opacity(opacity: (1 - .22 * v).clamp(0, 1), child: child) : child,
        );
      },
    );
    if (off) return widget.child;
    return Semantics(
      button: true,
      label: widget.label,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTapDown: (_) => _set(true),
        onTapUp: (_) => _set(false),
        onTapCancel: () => _set(false),
        onTap: widget.onTap == null
            ? null
            : () {
                if (widget.haptic) Tap.tick();
                widget.onTap!();
              },
        onLongPress: widget.onLong == null
            ? null
            : () {
                _set(false);
                Tap.mid();
                widget.onLong!();
              },
        child: widget.label == null ? child : ExcludeSemantics(child: child),
      ),
    );
  }
}

/// Arrives once: rises a little and fades in, each one a beat after the one before.
class Rise extends StatefulWidget {
  const Rise(this.i, {super.key, required this.child, this.dy = 14});
  final int i;
  final Widget child;
  final double dy;
  @override
  State<Rise> createState() => _RiseState();
}

class _RiseState extends State<Rise> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 520));
  late final _pos = CurvedAnimation(parent: _c, curve: Curves.easeOutQuint);
  late final _op = CurvedAnimation(parent: _c, curve: const Interval(0, .6, curve: Curves.easeOut));

  @override
  void initState() {
    super.initState();
    if (Settings.i.calm) {
      _c.value = 1;
    } else {
      Future.delayed(Duration(milliseconds: 34 * math.min(widget.i, 10)), () => mounted ? _c.forward() : null);
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => FadeTransition(
    opacity: _op,
    child: AnimatedBuilder(
      animation: _pos,
      child: widget.child,
      builder: (_, child) => Transform.translate(offset: Offset(0, widget.dy * (1 - _pos.value)), child: child),
    ),
  );
}

/// Opens and closes with its content clipped, the height easing.
class Fold extends StatelessWidget {
  const Fold({super.key, required this.open, required this.child});
  final bool open;
  final Widget child;
  @override
  Widget build(BuildContext context) => AnimatedCrossFade(
    duration: med,
    firstCurve: Curves.easeOutQuint,
    secondCurve: Curves.easeOutQuint,
    sizeCurve: Curves.easeOutQuint,
    crossFadeState: open ? CrossFadeState.showSecond : CrossFadeState.showFirst,
    firstChild: const SizedBox(width: double.infinity),
    secondChild: child,
    layoutBuilder: (top, topKey, bottom, bottomKey) => Stack(
      clipBehavior: Clip.none,
      children: [
        Positioned(key: bottomKey, left: 0, right: 0, top: 0, child: bottom),
        Positioned(key: topKey, child: top),
      ],
    ),
  );
}

/// Swaps one thing for another: the old one sinks out, the new one rises in.
class Swap extends StatelessWidget {
  const Swap({super.key, required this.child, this.dy = .35, this.align = Alignment.center});
  final Widget child;
  final double dy;
  final Alignment align;
  @override
  Widget build(BuildContext context) => AnimatedSwitcher(
    duration: const Duration(milliseconds: 260),
    switchInCurve: Curves.easeOutCubic,
    switchOutCurve: Curves.easeInCubic,
    layoutBuilder: (cur, prev) => Stack(alignment: align, children: [...prev, ?cur]),
    transitionBuilder: (c, a) => FadeTransition(
      opacity: a,
      child: SlideTransition(position: Tween(begin: Offset(0, dy), end: Offset.zero).animate(a), child: c),
    ),
    child: child,
  );
}

/// The sign of life: the three strands running along a thin line. Only shown while work runs.
class StrandLine extends StatefulWidget {
  const StrandLine({super.key, this.height = 2, this.width});
  final double height;
  final double? width;
  @override
  State<StrandLine> createState() => _StrandLineState();
}

class _StrandLineState extends State<StrandLine> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 2200))..repeat();
  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => RepaintBoundary(
    child: SizedBox(
      height: widget.height,
      width: widget.width ?? double.infinity,
      child: CustomPaint(painter: _LinePainter(_c, context.p.fill2)),
    ),
  );
}

class _LinePainter extends CustomPainter {
  _LinePainter(this.t, this.track) : super(repaint: t);
  final Animation<double> t;
  final Color track;
  @override
  void paint(Canvas canvas, Size s) {
    final r = Radius.circular(s.height);
    canvas.drawRRect(RRect.fromRectAndRadius(Offset.zero & s, r), Paint()..color = track);
    canvas.clipRRect(RRect.fromRectAndRadius(Offset.zero & s, r));
    for (var i = 0; i < 3; i++) {
      final at = (t.value + i * .33) % 1.0;
      final w = s.width * (.22 + .1 * math.sin(at * math.pi));
      final x = -w + (s.width + w * 2) * Curves.easeInOutSine.transform(at) - w;
      final rect = Rect.fromLTWH(x, 0, w, s.height);
      canvas.drawRRect(
        RRect.fromRectAndRadius(rect, r),
        Paint()..shader = LinearGradient(colors: [strands[i].withValues(alpha: 0), strands[i], strands[i].withValues(alpha: 0)]).createShader(rect),
      );
    }
  }

  @override
  bool shouldRepaint(_LinePainter old) => old.track != track;
}

/// Three small strands, breathing one after another: "thinking", next to a word.
class Pulse extends StatefulWidget {
  const Pulse({super.key, this.size = 14});
  final double size;
  @override
  State<Pulse> createState() => _PulseState();
}

class _PulseState extends State<Pulse> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1300))..repeat();
  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => RepaintBoundary(
    child: CustomPaint(size: Size(widget.size, widget.size), painter: _PulsePainter(_c)),
  );
}

class _PulsePainter extends CustomPainter {
  _PulsePainter(this.t) : super(repaint: t);
  final Animation<double> t;
  @override
  void paint(Canvas canvas, Size s) {
    final w = s.width / 5;
    for (var i = 0; i < 3; i++) {
      final k = (math.sin((t.value * 2 - i * .28) * math.pi) + 1) / 2;
      final h = s.height * (.34 + .62 * k);
      canvas.drawRRect(
        RRect.fromRectAndRadius(Rect.fromCenter(center: Offset(w / 2 + i * w * 2, s.height / 2), width: w, height: h), Radius.circular(w)),
        Paint()..color = strands[i].withValues(alpha: .55 + .45 * k),
      );
    }
  }

  @override
  bool shouldRepaint(_PulsePainter old) => false;
}

/// Words with a light passing over them, while something is in progress.
class Shine extends StatefulWidget {
  const Shine(this.text, {super.key, required this.style, this.max = 1});
  final String text;
  final TextStyle style;
  final int max;
  @override
  State<Shine> createState() => _ShineState();
}

class _ShineState extends State<Shine> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1700))..repeat();
  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final txt = Text(widget.text, maxLines: widget.max, overflow: TextOverflow.ellipsis, style: widget.style.copyWith(color: Colors.white));
    return RepaintBoundary(
      child: AnimatedBuilder(
        animation: _c,
        child: txt,
        builder: (_, child) => ShaderMask(
          blendMode: BlendMode.srcIn,
          shaderCallback: (r) => LinearGradient(
            colors: [p.text3, p.text, p.text3],
            stops: const [.3, .5, .7],
            transform: _Slide(_c.value * 2.6 - 1.3),
          ).createShader(r),
          child: child,
        ),
      ),
    );
  }
}

class _Slide extends GradientTransform {
  const _Slide(this.x);
  final double x;
  @override
  Matrix4 transform(Rect b, {TextDirection? textDirection}) => Matrix4.translationValues(b.width * x, 0, 0);
}

/// A soft placeholder while something loads.
class Bone extends StatefulWidget {
  const Bone({super.key, this.w, this.h = 14, this.r = 8});
  final double? w;
  final double h, r;
  @override
  State<Bone> createState() => _BoneState();
}

class _BoneState extends State<Bone> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1100))..repeat(reverse: true);
  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => FadeTransition(
    opacity: Tween(begin: .45, end: 1.0).animate(CurvedAnimation(parent: _c, curve: Curves.easeInOut)),
    child: Container(
      width: widget.w,
      height: widget.h,
      decoration: BoxDecoration(color: context.p.fill, borderRadius: BorderRadius.circular(widget.r)),
    ),
  );
}

/// A ring that fills as steps of a plan get done.
class Ring extends StatelessWidget {
  const Ring(this.value, {super.key, this.size = 18, this.stroke = 2.4, this.color});
  final double value, size, stroke;
  final Color? color;
  @override
  Widget build(BuildContext context) => TweenAnimationBuilder<double>(
    tween: Tween(end: value.clamp(0, 1)),
    duration: slow,
    curve: Curves.easeOutCubic,
    builder: (c, v, _) => CustomPaint(size: Size.square(size), painter: _RingPainter(v, stroke, color ?? c.p.accent, c.p.fill2)),
  );
}

class _RingPainter extends CustomPainter {
  _RingPainter(this.v, this.w, this.color, this.track);
  final double v, w;
  final Color color, track;
  @override
  void paint(Canvas canvas, Size s) {
    final rect = Rect.fromLTWH(w / 2, w / 2, s.width - w, s.height - w);
    final p = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = w
      ..strokeCap = StrokeCap.round;
    canvas.drawArc(rect, 0, math.pi * 2, false, p..color = track);
    if (v > 0) canvas.drawArc(rect, -math.pi / 2, math.pi * 2 * v, false, p..color = color);
  }

  @override
  bool shouldRepaint(_RingPainter o) => o.v != v || o.color != color || o.track != track;
}
