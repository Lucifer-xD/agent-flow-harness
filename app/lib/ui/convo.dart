// The parts of a conversation, shared by chats on the phone and threads on a computer.
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

import '../core/l10n.dart';
import '../core/store.dart';
import 'kit.dart';
import 'look.dart';
import 'media.dart';
import 'md.dart';
import 'motion.dart';

/// Keeps what you're reading where it is when the reply under it grows.
class _Keep extends ScrollPhysics {
  const _Keep({super.parent});
  @override
  _Keep applyTo(ScrollPhysics? ancestor) => _Keep(parent: buildParent(ancestor));
  @override
  double adjustPositionForNewDimensions({required ScrollMetrics oldPosition, required ScrollMetrics newPosition, required bool isScrolling, required double velocity}) {
    final grown = newPosition.maxScrollExtent - oldPosition.maxScrollExtent;
    if (oldPosition.pixels > 60 && grown != 0 && oldPosition.viewportDimension == newPosition.viewportDimension && ConvoScroll.holding) {
      return (newPosition.pixels + grown).clamp(0, newPosition.maxScrollExtent);
    }
    return super.adjustPositionForNewDimensions(oldPosition: oldPosition, newPosition: newPosition, isScrolling: isScrolling, velocity: velocity);
  }
}

/// A conversation: starts at the top, sticks to the end, and older messages come in as you scroll up.
class ConvoScroll extends StatefulWidget {
  const ConvoScroll({super.key, required this.count, required this.builder, this.top = 0, this.bottom = 0, this.tail, this.empty, required this.controller, this.live = false});
  final int count;
  final Widget Function(int i) builder;
  final double top, bottom;
  final Widget? tail, empty;
  final ScrollController controller;
  final bool live;
  static bool holding = false; // set while older messages are not being added

  @override
  State<ConvoScroll> createState() => _ConvoScrollState();
}

class _ConvoScrollState extends State<ConvoScroll> {
  int _show = 24;

  @override
  void initState() {
    super.initState();
    ConvoScroll.holding = true;
    widget.controller.addListener(_on);
  }

  void _on() {
    final c = widget.controller;
    if (!c.hasClients || _show >= widget.count) return;
    if (c.offset > c.position.maxScrollExtent - 900) {
      ConvoScroll.holding = false; // growth is at the far end now: nothing to hold
      setState(() => _show += 20);
      WidgetsBinding.instance.addPostFrameCallback((_) => ConvoScroll.holding = true);
    }
  }

  @override
  void dispose() {
    widget.controller.removeListener(_on);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final from = math.max(0, widget.count - _show);
    return LayoutBuilder(
      builder: (c, box) => SingleChildScrollView(
        controller: widget.controller,
        reverse: true,
        physics: const _Keep(parent: AlwaysScrollableScrollPhysics(parent: BouncingScrollPhysics())),
        keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
        child: ConstrainedBox(
          constraints: BoxConstraints(minHeight: box.maxHeight),
          child: Padding(
            padding: EdgeInsets.only(top: widget.top, bottom: widget.bottom),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.start,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (widget.count == 0 && widget.empty != null)
                  ConstrainedBox(
                    constraints: BoxConstraints(minHeight: math.max(0, box.maxHeight - widget.top - widget.bottom)),
                    child: Center(child: widget.empty),
                  ),
                for (var i = from; i < widget.count; i++) RepaintBoundary(child: widget.builder(i)),
                ?widget.tail,
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// "Back to the end", shown when you've scrolled away from it.
class ToEnd extends StatelessWidget {
  const ToEnd(this.c, {super.key, this.live = false});
  final ScrollController c;
  final bool live;
  @override
  Widget build(BuildContext context) {
    final p = context.p;
    return ListenableBuilder(
      listenable: c,
      builder: (context, _) {
        final show = c.hasClients && c.offset > 320;
        return IgnorePointer(
          ignoring: !show,
          child: AnimatedOpacity(
            opacity: show ? 1 : 0,
            duration: quick,
            child: AnimatedScale(
              scale: show ? 1 : .7,
              duration: const Duration(milliseconds: 360),
              curve: spring,
              child: Press(
                onTap: () => c.animateTo(0, duration: slow, curve: Curves.easeOutQuint),
                label: t('To the end'),
                child: Glass(
                  r: BorderRadius.circular(20),
                  child: SizedBox(
                    width: 40,
                    height: 40,
                    child: Center(child: live ? const Pulse(size: 14) : Icon(LucideIcons.arrowDown, size: 18, color: p.text)),
                  ),
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}

/// Text that flows in at an even pace however unevenly it arrives.
class FlowText extends StatefulWidget {
  const FlowText(this.text, {super.key, required this.live, this.style});
  final String text;
  final bool live;
  final TextStyle? style;
  @override
  State<FlowText> createState() => _FlowState();
}

class _FlowState extends State<FlowText> with SingleTickerProviderStateMixin {
  late final Ticker _t = createTicker(_tick);
  late double _n = widget.live && widget.text.length > 60 ? widget.text.length.toDouble() : (widget.live ? 0 : widget.text.length.toDouble());
  Duration _last = Duration.zero;

  @override
  void initState() {
    super.initState();
    _sync();
  }

  @override
  void didUpdateWidget(FlowText old) {
    super.didUpdateWidget(old);
    _sync();
  }

  void _sync() {
    final behind = widget.text.length - _n;
    if (behind <= 0) {
      _n = widget.text.length.toDouble();
      if (_t.isActive) _t.stop();
    } else if (calmOf_() || (!widget.live && behind > 1200)) {
      _n = widget.text.length.toDouble();
    } else if (!_t.isActive) {
      _last = Duration.zero;
      _t.start();
    }
  }

  bool calmOf_() => Settings.i.calm || WidgetsBinding.instance.platformDispatcher.accessibilityFeatures.disableAnimations;

  void _tick(Duration now) {
    final dt = (now - _last).inMicroseconds / 1e6;
    if (dt < .03) return;
    _last = now;
    final behind = widget.text.length - _n;
    if (behind <= 0) {
      _t.stop();
      return;
    }
    // catches up in about half a second, and never crawls
    setState(() => _n = math.min(widget.text.length.toDouble(), _n + math.max(40, behind * (widget.live ? 2.4 : 6)) * math.min(dt, .1)));
  }

  @override
  void dispose() {
    _t.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    var n = math.min(_n.floor(), widget.text.length);
    // never half of a surrogate pair
    if (n > 0 && n < widget.text.length && (widget.text.codeUnitAt(n - 1) & 0xFC00) == 0xD800) n--;
    final done = n >= widget.text.length;
    return Md(done ? widget.text : widget.text.substring(0, n), live: widget.live || !done, style: widget.style);
  }
}

/// What you wrote.
class Mine extends StatelessWidget {
  const Mine(this.text, {super.key, this.shots = const [], this.onLong, this.waiting = false, this.note, this.pad});
  final String text;
  final EdgeInsetsGeometry? pad;
  final List<Shot> shots;
  final VoidCallback? onLong;
  final bool waiting;
  final String? note;

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    return Padding(
      padding: pad ?? const EdgeInsetsDirectional.fromSTEB(56, 18, gutter, 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          if (shots.isNotEmpty) Padding(padding: EdgeInsets.only(bottom: text.isEmpty ? 0 : 6), child: SentFiles(shots)),
          if (text.isNotEmpty)
            Press(
              onLong: onLong,
              scale: .985,
              dim: false,
              child: AnimatedOpacity(
                opacity: waiting ? .6 : 1,
                duration: med,
                child: Container(
                  padding: const EdgeInsets.fromLTRB(16, 11, 16, 11),
                  decoration: BoxDecoration(
                    color: p.fill,
                    borderRadius: const BorderRadiusDirectional.only(
                      topStart: Radius.circular(22),
                      topEnd: Radius.circular(22),
                      bottomStart: Radius.circular(22),
                      bottomEnd: Radius.circular(7),
                    ),
                  ),
                  child: Text(
                    text,
                    textDirection: isRtl(text) ? TextDirection.rtl : TextDirection.ltr,
                    style: T.body.copyWith(color: p.text, height: 1.45),
                  ),
                ),
              ),
            ),
          if (note != null)
            Padding(
              padding: const EdgeInsets.only(top: 6, right: 4, left: 4),
              child: Text(note!, style: T.tiny.copyWith(color: p.text3)),
            ),
        ],
      ),
    );
  }
}

/// One quiet line that stands for something to open: thinking, or a run of steps.
class QuietLine extends StatelessWidget {
  const QuietLine(this.label, {super.key, this.icon, this.live = false, this.onTap, this.trail, this.bad = false});
  final String label;
  final IconData? icon;
  final bool live, bad;
  final VoidCallback? onTap;
  final Widget? trail;
  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final s = T.sub.copyWith(color: bad ? p.bad : p.text2, fontWeight: FontWeight.w500);
    return Press(
      onTap: onTap,
      scale: .98,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 7),
        child: Row(
          children: [
            SizedBox(
              width: 22,
              child: Align(
                alignment: AlignmentDirectional.centerStart,
                child: live ? const Pulse(size: 14) : Icon(icon ?? LucideIcons.listChecks, size: 16, color: bad ? p.bad : p.text3),
              ),
            ),
            const SizedBox(width: 6),
            Flexible(
              child: Swap(
                align: Alignment.centerLeft,
                child: live ? Shine(label, key: ValueKey(label), style: s) : Text(label, key: ValueKey(label), maxLines: 1, overflow: TextOverflow.ellipsis, style: s),
              ),
            ),
            if (trail != null) ...[const SizedBox(width: 8), trail!],
            if (onTap != null && !live) ...[
              const SizedBox(width: 4),
              Icon(Directionality.of(context) == TextDirection.rtl ? LucideIcons.chevronLeft : LucideIcons.chevronRight, size: 14, color: p.text3),
            ],
          ],
        ),
      ),
    );
  }
}

/// A small action under a reply.
class ReplyBtn extends StatelessWidget {
  const ReplyBtn(this.icon, this.onTap, {super.key, this.tip, this.on = false});
  final IconData icon;
  final VoidCallback onTap;
  final String? tip;
  final bool on;
  @override
  Widget build(BuildContext context) => Ic(icon, onTap: onTap, size: 34, icon_: 16, color: on ? context.p.accent : context.p.text3, tip: tip);
}

/// Thinking, in full.
Future<void> thoughtSheet(BuildContext context, String text, {String? title}) => sheet(
  context,
  title: title ?? t('Thinking'),
  (c) => SingleChildScrollView(
    padding: EdgeInsets.fromLTRB(gutter, 0, gutter, 24 + MediaQuery.paddingOf(c).bottom),
    child: Md(text, style: T.sub.copyWith(color: c.p.text2, height: 1.55)),
  ),
);

/// The whole text, to select from.
Future<void> selectSheet(BuildContext context, String text) => sheet(
  context,
  full: true,
  title: t('Select text'),
  (c) => SingleChildScrollView(
    padding: EdgeInsets.fromLTRB(gutter, 0, gutter, 24 + MediaQuery.paddingOf(c).bottom),
    child: SelectableText(text, style: T.body.copyWith(color: c.p.text)),
  ),
);
