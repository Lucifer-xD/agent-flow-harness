// The AFH mark, drawn from the same three strands as the app icon. It can draw itself in, and
// while `working` light runs along the strands.
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

class AfhLogo extends StatefulWidget {
  const AfhLogo({super.key, this.width = 96, this.intro = true, this.working = false});
  final double width;
  final bool intro;
  final bool working;

  @override
  State<AfhLogo> createState() => _AfhLogoState();
}

class _AfhLogoState extends State<AfhLogo> with TickerProviderStateMixin {
  late final AnimationController _draw = AnimationController(vsync: this, duration: const Duration(milliseconds: 1400));
  late final AnimationController _flow = AnimationController(vsync: this, duration: const Duration(milliseconds: 1600));

  @override
  void initState() {
    super.initState();
    if (widget.intro) {
      _draw.forward();
    } else {
      _draw.value = 1;
    }
    if (widget.working) _flow.repeat();
  }

  @override
  void didUpdateWidget(AfhLogo old) {
    super.didUpdateWidget(old);
    if (widget.working && !_flow.isAnimating) _flow.repeat();
    if (!widget.working && _flow.isAnimating) _flow.stop();
  }

  @override
  void dispose() {
    _draw.dispose();
    _flow.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return RepaintBoundary(
      child: AnimatedBuilder(
        animation: Listenable.merge([_draw, _flow]),
        builder: (_, _) => CustomPaint(
          size: Size(widget.width, widget.width * 140 / 240),
          painter: _MarkPainter(Curves.easeInOutCubic.transform(_draw.value), widget.working ? _flow.value : -1),
        ),
      ),
    );
  }
}

class _Strand {
  const _Strand(this.path, this.from, this.to, this.dotA, this.dotB);
  final List<double> path; // M x y, then C x1 y1 x2 y2 x y ...
  final Color from, to, dotA, dotB;
}

const _strands = [
  _Strand([46, 112, 108, 112, 116, 66, 146, 66, 172, 66, 170, 112, 194, 112], Color(0xFFFF3D8A), Color(0xFFE0169A), Color(0xFFFF3D8A), Color(0xFFE0169A)),
  _Strand([46, 70, 92, 70, 98, 58, 120, 60, 150, 63, 152, 82, 194, 70], Color(0xFFFF7747), Color(0xFFFF4A68), Color(0xFFFF7747), Color(0xFFFF4A68)),
  _Strand([46, 28, 104, 28, 108, 74, 134, 74, 160, 74, 164, 28, 194, 28], Color(0xFFFFB11F), Color(0xFFFF7A3D), Color(0xFFFFB11F), Color(0xFFFF7A3D)),
];

class _MarkPainter extends CustomPainter {
  _MarkPainter(this.t, this.flow);
  final double t;
  final double flow;

  @override
  void paint(Canvas canvas, Size size) {
    final s = size.width / 240;
    canvas.scale(s);
    for (var i = 0; i < _strands.length; i++) {
      final st = _strands[i];
      final p = st.path;
      final path = Path()..moveTo(p[0], p[1]);
      for (var k = 2; k + 5 < p.length; k += 6) {
        path.cubicTo(p[k], p[k + 1], p[k + 2], p[k + 3], p[k + 4], p[k + 5]);
      }
      // each strand starts a little after the one before
      final local = ((t * 1.35) - i * 0.12).clamp(0.0, 1.0);
      final metric = path.computeMetrics().first;
      final drawn = metric.extractPath(0, metric.length * local);
      final paint = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 14
        ..strokeCap = StrokeCap.round
        ..shader = ui.Gradient.linear(const Offset(46, 0), const Offset(194, 0), [st.from, st.to]);
      canvas.drawPath(drawn, paint);
      if (flow >= 0) {
        // a soft light travelling along the strand
        final at = ((flow + i * 0.22) % 1.0) * metric.length;
        final glow = metric.extractPath(math.max(0, at - 26), math.min(metric.length, at + 26));
        canvas.drawPath(
          glow,
          Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = 8
            ..strokeCap = StrokeCap.round
            ..color = Colors.white.withValues(alpha: 0.55)
            ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 4),
        );
      }
      final dotIn = Curves.easeOutBack.transform(((t * 3) - i * 0.25).clamp(0.0, 1.0));
      canvas.drawCircle(Offset(p[0], p[1]), 15 * dotIn, Paint()..color = st.dotA);
      final endIn = Curves.easeOutBack.transform(((local - 0.85) / 0.15).clamp(0.0, 1.0));
      canvas.drawCircle(Offset(p[p.length - 2], p[p.length - 1]), 15 * endIn, Paint()..color = st.dotB);
    }
  }

  @override
  bool shouldRepaint(_MarkPainter old) => old.t != t || old.flow != flow;
}
