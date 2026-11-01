// Shared building blocks: the slowly moving aurora behind screens, glass panels, a press-to-shrink
// wrapper, gradient buttons, pulsing status dots and empty states.
import 'dart:math' as math;
import 'dart:ui';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_animate/flutter_animate.dart';

import '../theme.dart';

/// Soft blobs of the AFH colours drifting behind a screen.
class Aurora extends StatefulWidget {
  const Aurora({super.key, this.intensity = 1});
  final double intensity;
  @override
  State<Aurora> createState() => _AuroraState();
}

class _AuroraState extends State<Aurora> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(seconds: 18))..repeat();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: RepaintBoundary(
        child: AnimatedBuilder(
          animation: _c,
          builder: (_, _) => CustomPaint(painter: _AuroraPainter(_c.value * 2 * math.pi, widget.intensity), size: Size.infinite),
        ),
      ),
    );
  }
}

class _AuroraPainter extends CustomPainter {
  _AuroraPainter(this.a, this.k);
  final double a, k;
  @override
  void paint(Canvas canvas, Size size) {
    void blob(double x, double y, double r, Color c) {
      final center = Offset(size.width * x, size.height * y);
      canvas.drawCircle(
        center,
        r,
        Paint()
          ..shader = RadialGradient(
            colors: [
              c.withValues(alpha: c.a * k),
              c.withValues(alpha: 0),
            ],
          ).createShader(Rect.fromCircle(center: center, radius: r)),
      );
    }

    final w = size.width;
    blob(0.85 + 0.08 * math.sin(a), -0.02 + 0.05 * math.cos(a * 1.3), w * 0.95, const Color(0x40FF3D8A));
    blob(0.05 + 0.1 * math.cos(a * 0.8), 0.12 + 0.06 * math.sin(a), w * 0.8, const Color(0x33FFB11F));
    blob(0.6 + 0.15 * math.sin(a * 0.6 + 1), 0.55 + 0.08 * math.cos(a * 0.9), w * 0.7, const Color(0x1FFF6A2A));
  }

  @override
  bool shouldRepaint(_AuroraPainter old) => old.a != a;
}

/// A frosted panel.
class Glass extends StatelessWidget {
  const Glass({super.key, required this.child, this.radius = 24, this.padding = EdgeInsets.zero, this.blur = 18, this.color});
  final Widget child;
  final double radius;
  final EdgeInsets padding;
  final double blur;
  final Color? color;
  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(radius),
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: blur, sigmaY: blur),
        child: Container(
          padding: padding,
          decoration: BoxDecoration(
            color: color ?? Afh.surface.withValues(alpha: 0.72),
            borderRadius: BorderRadius.circular(radius),
            border: Border.all(color: Afh.line),
          ),
          child: child,
        ),
      ),
    );
  }
}

/// Shrinks a little under the finger and springs back; a light haptic on tap.
class Pressable extends StatefulWidget {
  const Pressable({super.key, required this.child, this.onTap, this.onLongPress, this.scale = 0.965});
  final Widget child;
  final VoidCallback? onTap;
  final VoidCallback? onLongPress;
  final double scale;
  @override
  State<Pressable> createState() => _PressableState();
}

class _PressableState extends State<Pressable> {
  bool _down = false;
  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTapDown: widget.onTap == null ? null : (_) => setState(() => _down = true),
      onTapUp: widget.onTap == null ? null : (_) => setState(() => _down = false),
      onTapCancel: () => setState(() => _down = false),
      onTap: widget.onTap == null
          ? null
          : () {
              HapticFeedback.selectionClick();
              widget.onTap!();
            },
      onLongPress: widget.onLongPress == null
          ? null
          : () {
              HapticFeedback.mediumImpact();
              widget.onLongPress!();
            },
      child: AnimatedScale(
        scale: _down ? widget.scale : 1,
        duration: Duration(milliseconds: _down ? 90 : 380),
        curve: _down ? Curves.easeOut : Afh.spring,
        child: widget.child,
      ),
    );
  }
}

/// The AFH gradient button.
class GradButton extends StatelessWidget {
  const GradButton({super.key, required this.label, this.onTap, this.icon, this.busy = false, this.height = 56});
  final String label;
  final VoidCallback? onTap;
  final IconData? icon;
  final bool busy;
  final double height;
  @override
  Widget build(BuildContext context) {
    final enabled = onTap != null && !busy;
    return Pressable(
      onTap: enabled ? onTap : null,
      child: AnimatedOpacity(
        duration: const Duration(milliseconds: 200),
        opacity: enabled || busy ? 1 : 0.45,
        child: Container(
          height: height,
          decoration: BoxDecoration(
            gradient: Afh.grad,
            borderRadius: BorderRadius.circular(height / 2),
            boxShadow: [BoxShadow(color: Afh.pink.withValues(alpha: 0.35), blurRadius: 28, offset: const Offset(0, 12), spreadRadius: -10)],
          ),
          alignment: Alignment.center,
          child: AnimatedSwitcher(
            duration: const Duration(milliseconds: 220),
            child: busy
                ? const SizedBox(
                    key: ValueKey('busy'),
                    width: 22,
                    height: 22,
                    child: CircularProgressIndicator(strokeWidth: 2.4, color: Color(0xFF1A0D05)),
                  )
                : Row(
                    key: const ValueKey('label'),
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      if (icon != null) ...[Icon(icon, size: 20, color: const Color(0xFF1A0D05)), const SizedBox(width: 8)],
                      Text(
                        label,
                        style: const TextStyle(fontFamily: Afh.display, fontWeight: FontWeight.w700, fontSize: 16.5, color: Color(0xFF1A0D05)),
                      ),
                    ],
                  ),
          ),
        ),
      ),
    );
  }
}

/// A quiet outlined button.
class GhostButton extends StatelessWidget {
  const GhostButton({super.key, required this.label, this.onTap, this.icon, this.color});
  final String label;
  final VoidCallback? onTap;
  final IconData? icon;
  final Color? color;
  @override
  Widget build(BuildContext context) {
    return Pressable(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
        decoration: BoxDecoration(
          color: Afh.surface2,
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: Afh.line2),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (icon != null) ...[Icon(icon, size: 18, color: color ?? Afh.text2), const SizedBox(width: 8)],
            Text(
              label,
              style: TextStyle(fontWeight: FontWeight.w600, color: color ?? Afh.text),
            ),
          ],
        ),
      ),
    );
  }
}

/// A status dot that breathes while something is live.
class PulseDot extends StatelessWidget {
  const PulseDot({super.key, required this.color, this.live = true, this.size = 9});
  final Color color;
  final bool live;
  final double size;
  @override
  Widget build(BuildContext context) {
    final dot = Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: color,
        shape: BoxShape.circle,
        boxShadow: live ? [BoxShadow(color: color.withValues(alpha: 0.7), blurRadius: 10)] : null,
      ),
    );
    if (!live) return dot;
    return Stack(
      alignment: Alignment.center,
      children: [
        Container(
              width: size,
              height: size,
              decoration: BoxDecoration(color: color.withValues(alpha: 0.5), shape: BoxShape.circle),
            )
            .animate(onPlay: (c) => c.repeat())
            .scale(begin: const Offset(1, 1), end: const Offset(2.6, 2.6), duration: 1600.ms, curve: Curves.easeOut)
            .fadeOut(duration: 1600.ms),
        dot,
      ],
    );
  }
}

/// Three dots bouncing in the AFH colours.
class TypingDots extends StatelessWidget {
  const TypingDots({super.key});
  @override
  Widget build(BuildContext context) {
    const colors = [Afh.orange, Afh.coral, Afh.pink];
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        for (var i = 0; i < 3; i++)
          Container(
                width: 7,
                height: 7,
                margin: const EdgeInsets.symmetric(horizontal: 2.5),
                decoration: BoxDecoration(color: colors[i], shape: BoxShape.circle),
              )
              .animate(onPlay: (c) => c.repeat(), delay: (i * 140).ms)
              .moveY(begin: 0, end: -5, duration: 360.ms, curve: Curves.easeOut)
              .then()
              .moveY(begin: -5, end: 0, duration: 360.ms, curve: Curves.easeIn)
              .then(delay: 300.ms),
      ],
    );
  }
}

class EmptyState extends StatelessWidget {
  const EmptyState({super.key, required this.icon, required this.title, required this.text, this.action, this.art});
  final IconData icon;
  final String title;
  final String text;
  final Widget? action;
  final Widget? art;
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 40),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          art ??
              Container(
                width: 92,
                height: 92,
                decoration: BoxDecoration(
                  gradient: Afh.gradSoft,
                  borderRadius: BorderRadius.circular(30),
                  border: Border.all(color: Afh.orange.withValues(alpha: 0.25)),
                ),
                child: Icon(icon, size: 40, color: const Color(0xFFFFB48A)),
              ).animate().scale(begin: const Offset(0.6, 0.6), duration: 600.ms, curve: Afh.spring).fadeIn(),
          const SizedBox(height: 22),
          Text(title, textAlign: TextAlign.center, style: Afh.h2()).animate().fadeIn(delay: 120.ms).moveY(begin: 10, end: 0, curve: Afh.ease),
          const SizedBox(height: 10),
          Text(
            text,
            textAlign: TextAlign.center,
            style: const TextStyle(color: Afh.text2, fontSize: 15, height: 1.45),
          ).animate().fadeIn(delay: 200.ms),
          if (action != null) ...[const SizedBox(height: 22), action!.animate().fadeIn(delay: 300.ms).moveY(begin: 10, end: 0)],
        ],
      ),
    );
  }
}

/// A gradient-filled icon tile.
class IconTile extends StatelessWidget {
  const IconTile(this.icon, {super.key, this.size = 48, this.active = true});
  final IconData icon;
  final double size;
  final bool active;
  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        gradient: active ? Afh.gradSoft : null,
        color: active ? null : Colors.white.withValues(alpha: 0.05),
        borderRadius: BorderRadius.circular(size * 0.32),
        border: Border.all(color: active ? Afh.orange.withValues(alpha: 0.22) : Afh.line),
      ),
      child: Icon(icon, size: size * 0.5, color: active ? const Color(0xFFFFB48A) : Afh.text3),
    );
  }
}

/// Gradient text for big titles.
class GradText extends StatelessWidget {
  const GradText(this.text, {super.key, required this.style});
  final String text;
  final TextStyle style;
  @override
  Widget build(BuildContext context) {
    return ShaderMask(
      shaderCallback: (r) => Afh.grad.createShader(r),
      blendMode: BlendMode.srcIn,
      child: Text(text, style: style),
    );
  }
}

String ago(DateTime? t) {
  if (t == null) return '';
  final s = DateTime.now().difference(t).inSeconds;
  if (s < 45) return 'just now';
  if (s < 3600) return '${(s / 60).round()} min ago';
  if (s < 86400) return '${(s / 3600).round()} h ago';
  if (s < 7 * 86400) return '${(s / 86400).round()} d ago';
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return '${months[t.month - 1]} ${t.day}';
}

void showToast(BuildContext context, String message, {bool error = false}) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(
      SnackBar(
        content: Row(
          children: [
            Icon(error ? Icons.error_outline_rounded : Icons.check_circle_outline_rounded, color: error ? Afh.bad : Afh.good, size: 20),
            const SizedBox(width: 10),
            Expanded(child: Text(message)),
          ],
        ),
        duration: Duration(milliseconds: error ? 4200 : 2400),
      ),
    );
}
