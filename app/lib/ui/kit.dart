// The building blocks every screen is made of.
import 'dart:async';
import 'dart:ui';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../core/l10n.dart';
import 'look.dart';
import 'motion.dart';

export 'package:lucide_icons_flutter/lucide_icons.dart' show LucideIcons;

const gutter = 20.0;

/// A round icon button.
class Ic extends StatelessWidget {
  const Ic(this.icon, {super.key, this.onTap, this.size = 40, this.icon_ = 20, this.color, this.fill, this.tip, this.border = false, this.badge = 0});
  final IconData icon;
  final VoidCallback? onTap;
  final double size, icon_;
  final Color? color, fill;
  final String? tip;
  final bool border;
  final int badge;

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    return Press(
      onTap: onTap,
      scale: .88,
      label: tip,
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          Container(
            width: size,
            height: size,
            alignment: Alignment.center,
            decoration: BoxDecoration(color: fill, shape: BoxShape.circle, border: border ? Border.all(color: p.line) : null),
            child: Icon(icon, size: icon_, color: onTap == null ? p.text3 : color ?? p.text),
          ),
          if (badge > 0) PositionedDirectional(top: 4, end: 2, child: Count(badge)),
        ],
      ),
    );
  }
}

class Count extends StatelessWidget {
  const Count(this.n, {super.key, this.color});
  final int n;
  final Color? color;
  @override
  Widget build(BuildContext context) => Container(
    constraints: const BoxConstraints(minWidth: 17),
    height: 17,
    padding: const EdgeInsets.symmetric(horizontal: 4.5),
    alignment: Alignment.center,
    decoration: BoxDecoration(color: color ?? context.p.accent, borderRadius: BorderRadius.circular(9)),
    child: Text('$n', style: T.tiny.copyWith(fontSize: 10.5, height: 1, color: context.p.onAccent, fontWeight: FontWeight.w700)),
  );
}

enum Kind { main, soft, ghost, danger }

class Btn extends StatelessWidget {
  const Btn(this.label, {super.key, this.onTap, this.icon, this.kind = Kind.main, this.wide = true, this.busy = false, this.small = false, this.accent = false});
  final String label;
  final VoidCallback? onTap;
  final IconData? icon;
  final Kind kind;
  final bool wide, busy, small, accent;

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final (bg, fg) = switch (kind) {
      Kind.main => accent ? (p.accent, p.onAccent) : (p.inv, p.onInv),
      Kind.soft => (p.fill, p.text),
      Kind.ghost => (Colors.transparent, p.text2),
      Kind.danger => (p.tint(p.bad), p.bad),
    };
    final off = onTap == null || busy;
    return Press(
      onTap: off ? null : onTap,
      child: AnimatedOpacity(
        opacity: onTap == null && !busy ? .45 : 1,
        duration: quick,
        child: Container(
          height: small ? 40 : 52,
          width: wide ? double.infinity : null,
          padding: EdgeInsets.symmetric(horizontal: small ? 14 : 20),
          alignment: Alignment.center,
          decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(small ? 13 : 17)),
          child: Swap(
            child: busy
                ? Pulse(key: const ValueKey('b'), size: small ? 14 : 16)
                : Row(
                    key: const ValueKey('l'),
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      if (icon != null) ...[Icon(icon, size: small ? 16 : 18, color: fg), SizedBox(width: small ? 7 : 9)],
                      Flexible(
                        child: Text(
                          label,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: T.btn.copyWith(color: fg, fontSize: small ? 14 : 15.5),
                        ),
                      ),
                    ],
                  ),
          ),
        ),
      ),
    );
  }
}

/// A small pill: a choice, a filter, or a fact.
class Pill extends StatelessWidget {
  const Pill(this.label, {super.key, this.icon, this.lead, this.on = false, this.onTap, this.onLong, this.color, this.caret = false, this.close, this.dense = false, this.max = 180});
  final String label;
  final IconData? icon;
  final Widget? lead;
  final bool on, caret, dense;
  final VoidCallback? onTap, onLong, close;
  final Color? color;
  final double max;

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final fg = color ?? (on ? p.onInv : p.text2);
    final body = AnimatedContainer(
      duration: med,
      curve: Curves.easeOutCubic,
      height: dense ? 26 : 34,
      padding: EdgeInsets.symmetric(horizontal: dense ? 9 : 12),
      decoration: BoxDecoration(
        color: color != null ? p.tint(color!) : (on ? p.inv : p.fill),
        borderRadius: BorderRadius.circular(dense ? 9 : 12),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (lead != null) ...[lead!, const SizedBox(width: 7)],
          if (icon != null) ...[Icon(icon, size: dense ? 13 : 15, color: fg), const SizedBox(width: 6)],
          ConstrainedBox(
            constraints: BoxConstraints(maxWidth: max),
            child: Text(
              label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: T.label.copyWith(color: color ?? (on ? p.onInv : p.text), fontSize: dense ? 11.5 : 13.5),
            ),
          ),
          if (caret) ...[const SizedBox(width: 4), Icon(LucideIcons.chevronDown, size: 13, color: on ? p.onInv : p.text3)],
          if (close != null)
            Press(
              onTap: close,
              child: Padding(
                padding: const EdgeInsetsDirectional.only(start: 6),
                child: Icon(LucideIcons.x, size: 14, color: fg),
              ),
            ),
        ],
      ),
    );
    return onTap == null && onLong == null ? body : Press(onTap: onTap, onLong: onLong, scale: .94, child: body);
  }
}

class Panel extends StatelessWidget {
  const Panel({super.key, required this.child, this.pad = const EdgeInsets.all(16), this.onTap, this.onLong, this.color, this.border, this.r = 20});
  final Widget child;
  final EdgeInsetsGeometry pad;
  final VoidCallback? onTap, onLong;
  final Color? color, border;
  final double r;
  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final c = Container(
      width: double.infinity,
      padding: pad,
      decoration: BoxDecoration(
        color: color ?? p.surface,
        borderRadius: BorderRadius.circular(r),
        border: Border.all(color: border ?? p.line),
      ),
      child: child,
    );
    return onTap == null && onLong == null ? c : Press(onTap: onTap, onLong: onLong, scale: .98, dim: false, child: c);
  }
}

/// Rows in one card, with a small heading and a note under it.
class Group extends StatelessWidget {
  const Group({super.key, required this.children, this.title, this.note, this.trailing});
  final List<Widget> children;
  final String? title, note;
  final Widget? trailing;
  @override
  Widget build(BuildContext context) {
    final p = context.p;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (title != null) Head(title!, trailing: trailing),
        Container(
          clipBehavior: Clip.antiAlias,
          decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(20), border: Border.all(color: p.line)),
          child: Column(
            children: [
              for (final (i, c) in children.indexed) ...[
                if (i > 0)
                  Padding(
                    padding: const EdgeInsetsDirectional.only(start: 16),
                    child: Container(height: 1, color: p.line),
                  ),
                c,
              ],
            ],
          ),
        ),
        if (note != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 9, 16, 0),
            child: Text(note!, style: T.small.copyWith(color: p.text3)),
          ),
      ],
    );
  }
}

class Head extends StatelessWidget {
  const Head(this.text, {super.key, this.trailing, this.top = 26, this.count});
  final String text;
  final Widget? trailing;
  final double top;
  final int? count;
  @override
  Widget build(BuildContext context) => Padding(
    padding: EdgeInsetsDirectional.fromSTEB(4, top, 4, 10),
    child: Row(
      children: [
        Text(text, style: T.label.copyWith(color: context.p.text2)),
        if (count != null) ...[const SizedBox(width: 7), Text('$count', style: T.label.copyWith(color: context.p.text3))],
        const Spacer(),
        ?trailing,
      ],
    ),
  );
}

/// One row: icon, words, something at the end.
class Tile extends StatelessWidget {
  const Tile(this.title, {super.key, this.sub, this.icon, this.lead, this.trail, this.onTap, this.onLong, this.value, this.arrow = false, this.danger = false, this.subMax = 2, this.color, this.titleMax = 1, this.inset = 16});
  final String title;
  final double inset;
  final String? sub, value;
  final IconData? icon;
  final Widget? lead, trail;
  final VoidCallback? onTap, onLong;
  final bool arrow, danger;
  final int subMax, titleMax;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final fg = danger ? p.bad : p.text;
    final row = Padding(
      padding: EdgeInsets.symmetric(horizontal: inset, vertical: 13),
      child: Row(
        children: [
          if (lead != null) ...[lead!, const SizedBox(width: 13)],
          if (icon != null) ...[Icon(icon, size: 20, color: color ?? (danger ? p.bad : p.text2)), const SizedBox(width: 14)],
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, maxLines: titleMax, overflow: TextOverflow.ellipsis, style: T.row.copyWith(color: fg)),
                if (sub != null && sub!.isNotEmpty) ...[
                  const SizedBox(height: 2),
                  Text(sub!, maxLines: subMax, overflow: TextOverflow.ellipsis, style: T.small.copyWith(color: p.text3)),
                ],
              ],
            ),
          ),
          if (value != null) ...[
            const SizedBox(width: 12),
            ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 150),
              child: Text(value!, maxLines: 1, overflow: TextOverflow.ellipsis, style: T.sub.copyWith(color: p.text3)),
            ),
          ],
          if (trail != null) ...[const SizedBox(width: 10), trail!],
          if (arrow) ...[const SizedBox(width: 6), Icon(Directionality.of(context) == TextDirection.rtl ? LucideIcons.chevronLeft : LucideIcons.chevronRight, size: 17, color: p.text3)],
        ],
      ),
    );
    if (onTap == null && onLong == null) return row;
    return Press(onTap: onTap, onLong: onLong, scale: .985, child: row);
  }
}

class Toggle extends StatelessWidget {
  const Toggle(this.value, {super.key, this.onChanged});
  final bool value;
  final ValueChanged<bool>? onChanged;
  @override
  Widget build(BuildContext context) {
    final p = context.p;
    return Semantics(
      toggled: value,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: onChanged == null
            ? null
            : () {
                Tap.light();
                onChanged!(!value);
              },
        child: AnimatedContainer(
          duration: med,
          curve: Curves.easeOutCubic,
          width: 46,
          height: 28,
          padding: const EdgeInsets.all(3),
          decoration: BoxDecoration(color: value ? p.accent : p.fill2, borderRadius: BorderRadius.circular(14)),
          child: AnimatedAlign(
            duration: const Duration(milliseconds: 420),
            curve: spring,
            alignment: value ? AlignmentDirectional.centerEnd : AlignmentDirectional.centerStart,
            child: Container(
              width: 22,
              height: 22,
              decoration: BoxDecoration(
                color: value ? p.onAccent : Colors.white,
                shape: BoxShape.circle,
                boxShadow: const [BoxShadow(color: Color(0x30000000), blurRadius: 4, offset: Offset(0, 1))],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// A row that switches something on and off.
class ToggleTile extends StatelessWidget {
  const ToggleTile(this.title, this.value, this.onChanged, {super.key, this.sub, this.icon});
  final String title;
  final String? sub;
  final IconData? icon;
  final bool value;
  final ValueChanged<bool> onChanged;
  @override
  Widget build(BuildContext context) => Tile(title, sub: sub, subMax: 4, icon: icon, trail: Toggle(value, onChanged: onChanged), onTap: () => onChanged(!value));
}

/// Two to four choices side by side; the thumb slides to the chosen one.
class Seg extends StatelessWidget {
  const Seg(this.labels, this.at, this.onPick, {super.key, this.icons, this.height = 40, this.badges});
  final List<String> labels;
  final int at;
  final ValueChanged<int> onPick;
  final List<IconData>? icons;
  final List<int>? badges;
  final double height;

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final n = labels.length;
    return Container(
      height: height,
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(color: p.fill, borderRadius: BorderRadius.circular(height / 2.9)),
      child: Stack(
        children: [
          AnimatedAlign(
            duration: const Duration(milliseconds: 460),
            curve: spring,
            alignment: AlignmentDirectional(n == 1 ? 0 : -1 + 2 * at / (n - 1), 0),
            child: FractionallySizedBox(
              widthFactor: 1 / n,
              heightFactor: 1,
              child: Container(
                decoration: BoxDecoration(
                  color: p.dark ? p.fill2 : p.surface,
                  borderRadius: BorderRadius.circular(height / 3.6),
                  boxShadow: p.dark ? null : const [BoxShadow(color: Color(0x14000000), blurRadius: 6, offset: Offset(0, 1))],
                ),
              ),
            ),
          ),
          Row(
            children: [
              for (var i = 0; i < n; i++)
                Expanded(
                  child: GestureDetector(
                    behavior: HitTestBehavior.opaque,
                    onTap: () {
                      if (i != at) Tap.tick();
                      onPick(i);
                    },
                    child: Center(
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          if (icons != null) ...[Icon(icons![i], size: 15, color: i == at ? p.text : p.text3), const SizedBox(width: 6)],
                          Flexible(
                            child: AnimatedDefaultTextStyle(
                              duration: quick,
                              style: T.label.copyWith(color: i == at ? p.text : p.text2, fontSize: 13.5),
                              child: Text(labels[i], maxLines: 1, overflow: TextOverflow.ellipsis),
                            ),
                          ),
                          if (badges != null && badges![i] > 0) ...[const SizedBox(width: 6), Text('${badges![i]}', style: T.tiny.copyWith(color: p.text3))],
                        ],
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class Field extends StatelessWidget {
  const Field(this.c, {super.key, this.hint, this.label, this.icon, this.lines = 1, this.maxLines, this.type, this.secret = false, this.trail, this.onDone, this.onChanged, this.focus, this.auto = false, this.code = false, this.hints});
  final TextEditingController c;
  final String? hint, label;
  final IconData? icon;
  final int lines;
  final int? maxLines;
  final TextInputType? type;
  final bool secret, auto, code;
  final Widget? trail;
  final VoidCallback? onDone;
  final ValueChanged<String>? onChanged;
  final FocusNode? focus;
  final Iterable<String>? hints;

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final style = code ? T.code.copyWith(color: p.text, fontSize: 14) : T.body.copyWith(color: p.text, height: 1.4);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (label != null)
          Padding(
            padding: const EdgeInsetsDirectional.only(start: 4, bottom: 8),
            child: Text(label!, style: T.label.copyWith(color: p.text2)),
          ),
        Container(
          constraints: const BoxConstraints(minHeight: 52),
          padding: const EdgeInsetsDirectional.only(start: 15, end: 6),
          decoration: BoxDecoration(color: p.fill, borderRadius: BorderRadius.circular(16)),
          child: Row(
            children: [
              if (icon != null) ...[Icon(icon, size: 18, color: p.text3), const SizedBox(width: 10)],
              Expanded(
                child: TextField(
                  controller: c,
                  focusNode: focus,
                  autofocus: auto,
                  obscureText: secret,
                  minLines: lines,
                  maxLines: secret ? 1 : (maxLines ?? lines),
                  keyboardType: type,
                  autofillHints: hints,
                  autocorrect: !secret && !code && type == null,
                  enableSuggestions: !secret && !code,
                  onChanged: onChanged,
                  onSubmitted: onDone == null ? null : (_) => onDone!(),
                  textInputAction: icon == LucideIcons.search ? TextInputAction.search : (onDone != null && lines == 1 ? TextInputAction.done : null),
                  style: style,
                  decoration: InputDecoration(
                    isDense: true,
                    border: InputBorder.none,
                    contentPadding: const EdgeInsets.symmetric(vertical: 15),
                    hintText: hint,
                    hintStyle: style.copyWith(color: p.text3),
                  ),
                ),
              ),
              ?trail,
            ],
          ),
        ),
      ],
    );
  }
}

class Empty extends StatelessWidget {
  const Empty(this.icon, this.title, this.text, {super.key, this.action, this.onTap});
  final IconData icon;
  final String title, text;
  final String? action;
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) {
    final p = context.p;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 36),
      child: Column(
        children: [
          Rise(
            0,
            child: Container(
              width: 60,
              height: 60,
              decoration: BoxDecoration(color: p.fill, borderRadius: BorderRadius.circular(20)),
              child: Icon(icon, size: 26, color: p.text2),
            ),
          ),
          const SizedBox(height: 18),
          Rise(1, child: Text(title, textAlign: TextAlign.center, style: T.h2.copyWith(color: p.text))),
          const SizedBox(height: 6),
          Rise(2, child: Text(text, textAlign: TextAlign.center, style: T.sub.copyWith(color: p.text2))),
          if (action != null) ...[
            const SizedBox(height: 20),
            Rise(3, child: Btn(action!, onTap: onTap, wide: false, small: true)),
          ],
        ],
      ),
    );
  }
}

/// A note in the flow of a page: something to know, or something wrong.
class Note extends StatelessWidget {
  const Note(this.text, {super.key, this.icon = LucideIcons.info, this.color, this.action, this.onTap});
  final String text;
  final IconData icon;
  final Color? color;
  final String? action;
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final c = color ?? p.text2;
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
      decoration: BoxDecoration(color: color == null ? p.fill : p.tint(c), borderRadius: BorderRadius.circular(16)),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 1.5),
            child: Icon(icon, size: 17, color: c),
          ),
          const SizedBox(width: 11),
          Expanded(child: Text(text, style: T.sub.copyWith(color: p.text))),
          if (action != null)
            Press(
              onTap: onTap,
              child: Padding(
                padding: const EdgeInsetsDirectional.only(start: 12),
                child: Text(action!, style: T.label.copyWith(color: p.accent)),
              ),
            ),
        ],
      ),
    );
  }
}

// ---- pages ----

/// A page with a large title that shrinks into the bar as you scroll.
class AppPage extends StatefulWidget {
  const AppPage({super.key, required this.title, required this.slivers, this.actions = const [], this.back = true, this.onRefresh, this.bottom = 40, this.sub, this.lead, this.footer, this.controller});
  final String title;
  final String? sub;
  final List<Widget> slivers, actions;
  final bool back;
  final Future<void> Function()? onRefresh;
  final double bottom;
  final Widget? lead, footer;
  final ScrollController? controller;

  @override
  State<AppPage> createState() => _PageState();
}

class _PageState extends State<AppPage> {
  late final ScrollController _c = widget.controller ?? ScrollController();
  final _off = ValueNotifier(0.0);

  @override
  void initState() {
    super.initState();
    _c.addListener(_on);
  }

  void _on() => _off.value = _c.hasClients ? _c.offset : 0;

  @override
  void dispose() {
    _c.removeListener(_on);
    if (widget.controller == null) _c.dispose();
    _off.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final pad = MediaQuery.paddingOf(context);
    const barH = 52.0;
    Widget list = CustomScrollView(
      controller: _c,
      physics: const AlwaysScrollableScrollPhysics(parent: BouncingScrollPhysics()),
      keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
      slivers: [
        SliverToBoxAdapter(child: SizedBox(height: pad.top + barH)),
        SliverToBoxAdapter(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(gutter, 4, gutter, 14),
            child: ValueListenableBuilder(
              valueListenable: _off,
              builder: (_, o, child) => Opacity(opacity: (1 - (o - 4) / 20).clamp(0, 1), child: child),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(widget.title, style: T.display.copyWith(color: p.text)),
                  if (widget.sub != null) ...[const SizedBox(height: 6), Text(widget.sub!, style: T.sub.copyWith(color: p.text2))],
                ],
              ),
            ),
          ),
        ),
        ...widget.slivers,
        SliverToBoxAdapter(child: SizedBox(height: widget.bottom + pad.bottom)),
      ],
    );
    if (widget.onRefresh != null) {
      list = RefreshIndicator(
        onRefresh: widget.onRefresh!,
        color: p.accent,
        backgroundColor: p.raised,
        edgeOffset: pad.top + barH,
        child: list,
      );
    }
    return Scaffold(
      backgroundColor: p.bg,
      body: Stack(
        children: [
          list,
          Positioned(
            top: 0,
            left: 0,
            right: 0,
            child: ValueListenableBuilder(
              valueListenable: _off,
              builder: (_, o, child) {
                final k = ((o - 26) / 26).clamp(0.0, 1.0);
                return Container(
                  padding: EdgeInsets.only(top: pad.top),
                  decoration: BoxDecoration(
                    color: p.bg.withValues(alpha: k),
                    border: Border(bottom: BorderSide(color: p.line.withValues(alpha: p.line.a * k))),
                  ),
                  child: SizedBox(
                    height: barH,
                    child: Padding(
                      padding: EdgeInsetsDirectional.only(start: widget.back || widget.lead != null ? 8 : gutter, end: 10),
                      child: Row(
                        children: [
                          if (widget.lead != null) widget.lead! else if (widget.back && Navigator.of(context).canPop()) const BackBtn(),
                          Expanded(
                            child: Opacity(
                              opacity: k,
                              child: Transform.translate(
                                offset: Offset(0, (1 - k) * 8),
                                child: Padding(
                                  padding: const EdgeInsetsDirectional.only(start: 6),
                                  child: Text(widget.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: T.h2.copyWith(color: p.text)),
                                ),
                              ),
                            ),
                          ),
                          ...widget.actions,
                        ],
                      ),
                    ),
                  ),
                );
              },
            ),
          ),
          if (widget.footer != null) Positioned(left: 0, right: 0, bottom: 0, child: widget.footer!),
        ],
      ),
    );
  }
}

class BackBtn extends StatelessWidget {
  const BackBtn({super.key, this.icon});
  final IconData? icon;
  @override
  Widget build(BuildContext context) => Ic(
    icon ?? (Directionality.of(context) == TextDirection.rtl ? LucideIcons.arrowRight : LucideIcons.arrowLeft),
    tip: t('Back'),
    onTap: () => Navigator.of(context).maybePop(),
  );
}

/// Padding for a page's content.
SliverPadding pad(List<Widget> children, {bool rise = true}) => SliverPadding(
  padding: const EdgeInsets.symmetric(horizontal: gutter),
  sliver: SliverList.list(children: [for (final (i, c) in children.indexed) rise ? Rise(i, child: c) : c]),
);

// ---- over the page ----

Future<R?> sheet<R>(BuildContext context, Widget Function(BuildContext) builder, {bool full = false, String? title, Widget? trail}) {
  Tap.light();
  return showModalBottomSheet<R>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    backgroundColor: Colors.transparent,
    barrierColor: const Color(0x8C000000),
    sheetAnimationStyle: const AnimationStyle(duration: Duration(milliseconds: 380), reverseDuration: Duration(milliseconds: 240), curve: Curves.easeOutQuint),
    builder: (c) {
      final p = c.p;
      final kb = MediaQuery.viewInsetsOf(c).bottom;
      return Padding(
        padding: EdgeInsets.only(bottom: kb),
        child: Container(
          height: full ? MediaQuery.sizeOf(c).height * .93 - kb : null,
          constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(c).height * .93 - kb),
          decoration: BoxDecoration(
            color: p.raised,
            borderRadius: const BorderRadius.vertical(top: Radius.circular(28)),
            border: Border(top: BorderSide(color: p.line)),
          ),
          clipBehavior: Clip.antiAlias,
          child: Material(
            color: Colors.transparent,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Center(
                  child: Container(
                    margin: const EdgeInsets.only(top: 10, bottom: 8),
                    width: 34,
                    height: 4,
                    decoration: BoxDecoration(color: p.fill2, borderRadius: BorderRadius.circular(2)),
                  ),
                ),
                if (title != null)
                  Padding(
                    padding: const EdgeInsetsDirectional.fromSTEB(gutter, 6, 12, 10),
                    child: Row(
                      children: [
                        Expanded(child: Text(title, style: T.h1.copyWith(color: p.text))),
                        ?trail,
                      ],
                    ),
                  ),
                full ? Expanded(child: builder(c)) : Flexible(child: builder(c)),
              ],
            ),
          ),
        ),
      );
    },
  );
}

class Act {
  const Act(this.label, this.icon, this.run, {this.danger = false, this.sub, this.on = false});
  final String label;
  final String? sub;
  final IconData icon;
  final FutureOr<void> Function() run;
  final bool danger, on;
}

/// A list of things to do with something.
Future<void> actions(BuildContext context, List<Act?> acts, {String? title}) async {
  final picked = await sheet<Act>(
    context,
    title: title,
    (c) => ListView(
      shrinkWrap: true,
      padding: EdgeInsets.only(bottom: 12 + MediaQuery.paddingOf(c).bottom),
      children: [
        for (final a in acts)
          if (a == null)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: gutter, vertical: 5),
              child: Container(height: 1, color: c.p.line),
            )
          else
            Tile(
              a.label,
              inset: gutter,
              sub: a.sub,
              icon: a.icon,
              danger: a.danger,
              trail: a.on ? Icon(LucideIcons.check, size: 18, color: c.p.accent) : null,
              onTap: () => Navigator.pop(c, a),
            ),
      ],
    ),
  );
  await picked?.run();
}

Future<bool> confirm(BuildContext context, String title, String text, String action, {bool danger = false}) async =>
    await sheet<bool>(
      context,
      title: title,
      (c) => Padding(
        padding: EdgeInsets.fromLTRB(gutter, 0, gutter, 16 + MediaQuery.paddingOf(c).bottom),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Flexible(
              child: SingleChildScrollView(child: Text(text, style: T.body.copyWith(color: c.p.text2, fontSize: 15))),
            ),
            const SizedBox(height: 22),
            Row(
              children: [
                Expanded(child: Btn(t('Cancel'), kind: Kind.soft, onTap: () => Navigator.pop(c, false))),
                const SizedBox(width: 10),
                Expanded(
                  child: Btn(action, kind: danger ? Kind.danger : Kind.main, onTap: () => Navigator.pop(c, true)),
                ),
              ],
            ),
          ],
        ),
      ),
    ) ==
    true;

Future<String?> askText(BuildContext context, String title, {String value = '', String hint = '', String? action, int lines = 1}) {
  final c = TextEditingController(text: value)..selection = TextSelection(baseOffset: 0, extentOffset: value.length);
  return sheet<String>(
    context,
    title: title,
    (x) => Padding(
      padding: EdgeInsets.fromLTRB(gutter, 2, gutter, 16 + MediaQuery.paddingOf(x).bottom),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Field(c, hint: hint, auto: true, lines: lines, maxLines: lines == 1 ? 1 : 8, onDone: lines == 1 ? () => Navigator.pop(x, c.text.trim()) : null),
          const SizedBox(height: 14),
          Btn(action ?? t('Save'), onTap: () => Navigator.pop(x, c.text.trim())),
        ],
      ),
    ),
  );
}

OverlayEntry? _toast;

/// A short word at the top of the screen.
void toast(BuildContext context, String text, {IconData? icon, bool bad = false, String? action, VoidCallback? onTap}) {
  _toast?.remove();
  final overlay = Overlay.of(context, rootOverlay: true);
  late final OverlayEntry e;
  e = OverlayEntry(
    builder: (c) => _Toast(
      text: text,
      icon: icon ?? (bad ? LucideIcons.circleAlert : LucideIcons.check),
      bad: bad,
      action: action,
      onTap: onTap,
      gone: () {
        if (_toast == e) _toast = null;
        if (e.mounted) e.remove();
      },
    ),
  );
  _toast = e;
  overlay.insert(e);
  if (bad) Tap.mid();
}

class _Toast extends StatefulWidget {
  const _Toast({required this.text, required this.icon, required this.bad, required this.gone, this.action, this.onTap});
  final String text;
  final IconData icon;
  final bool bad;
  final String? action;
  final VoidCallback? onTap;
  final VoidCallback gone;
  @override
  State<_Toast> createState() => _ToastState();
}

class _ToastState extends State<_Toast> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 520), reverseDuration: const Duration(milliseconds: 200))..forward();
  Timer? _t;
  @override
  void initState() {
    super.initState();
    _t = Timer(Duration(milliseconds: widget.action != null ? 4600 : (widget.bad ? 4200 : 2300)), _out);
  }

  Future<void> _out() async {
    if (!mounted) return;
    await _c.reverse();
    widget.gone();
  }

  @override
  void dispose() {
    _t?.cancel();
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    return Positioned(
      top: MediaQuery.paddingOf(context).top + 8,
      left: 16,
      right: 16,
      child: AnimatedBuilder(
        animation: _c,
        builder: (_, child) {
          final v = _c.status == AnimationStatus.reverse ? Curves.easeIn.transform(_c.value) : spring.transform(_c.value);
          return Opacity(
            opacity: _c.value.clamp(0, 1),
            child: Transform.translate(
              offset: Offset(0, -44 * (1 - v)),
              child: Transform.scale(scale: .92 + .08 * v, child: child),
            ),
          );
        },
        child: Center(
          child: GestureDetector(
            onVerticalDragEnd: (_) => _out(),
            onTap: _out,
            child: Material(
              color: Colors.transparent,
              child: Container(
                constraints: const BoxConstraints(maxWidth: 420),
                padding: const EdgeInsets.fromLTRB(14, 11, 16, 11),
                decoration: BoxDecoration(
                  color: p.dark ? p.fill2 : const Color(0xFF1A1A1D),
                  borderRadius: BorderRadius.circular(18),
                  boxShadow: const [BoxShadow(color: Color(0x40000000), blurRadius: 24, offset: Offset(0, 8))],
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(widget.icon, size: 17, color: widget.bad ? const Color(0xFFFF7B7B) : const Color(0xFF5BD79C)),
                    const SizedBox(width: 10),
                    Flexible(
                      child: Text(widget.text, maxLines: 4, overflow: TextOverflow.ellipsis, style: T.label.copyWith(color: Colors.white, fontSize: 14)),
                    ),
                    if (widget.action != null)
                      Press(
                        onTap: () {
                          widget.onTap?.call();
                          _out();
                        },
                        child: Padding(
                          padding: const EdgeInsetsDirectional.only(start: 14),
                          child: Text(widget.action!, style: T.label.copyWith(color: const Color(0xFFFFA77F), fontSize: 14)),
                        ),
                      ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

void copyText(BuildContext context, String text, [String? said]) {
  Clipboard.setData(ClipboardData(text: text));
  toast(context, said ?? t('Copied'), icon: LucideIcons.copy);
}

/// Frosted glass.
class Glass extends StatelessWidget {
  const Glass({super.key, required this.child, required this.r, this.alpha});
  final Widget child;
  final BorderRadius r;
  final double? alpha;
  @override
  Widget build(BuildContext context) {
    final p = context.p;
    return ClipRRect(
      borderRadius: r,
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 22, sigmaY: 22),
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: (p.dark ? p.raised : p.surface).withValues(alpha: alpha ?? (p.dark ? .78 : .82)),
            borderRadius: r,
            border: Border.all(color: p.dark ? const Color(0x1CFFFFFF) : const Color(0x12000000)),
          ),
          child: child,
        ),
      ),
    );
  }
}

/// A dot that says how a computer is doing.
class Dot extends StatelessWidget {
  const Dot(this.color, {super.key, this.size = 8});
  final Color color;
  final double size;
  @override
  Widget build(BuildContext context) => AnimatedContainer(
    duration: med,
    width: size,
    height: size,
    decoration: BoxDecoration(color: color, shape: BoxShape.circle),
  );
}

/// A square with an icon in it, for lists.
class Square extends StatelessWidget {
  const Square(this.icon, {super.key, this.color, this.size = 38, this.child});
  final IconData? icon;
  final Color? color;
  final double size;
  final Widget? child;
  @override
  Widget build(BuildContext context) {
    final p = context.p;
    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(color: color == null ? p.fill : p.tint(color!), borderRadius: BorderRadius.circular(size * .32)),
      child: child ?? Icon(icon, size: size * .47, color: color ?? p.text2),
    );
  }
}

/// Swipe a row for its actions: start side keeps, end side removes.
class SwipeRow extends StatelessWidget {
  const SwipeRow({super.key, required this.id, required this.child, this.onStart, this.onEnd, this.startIcon = LucideIcons.pin, this.endIcon = LucideIcons.archive, this.startLabel = '', this.endLabel = '', this.endBad = false});
  final String id;
  final Widget child;
  final FutureOr<bool> Function()? onStart, onEnd; // true: the row leaves the list
  final IconData startIcon, endIcon;
  final String startLabel, endLabel;
  final bool endBad;

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    Widget back(AlignmentDirectional a, IconData i, String l, Color c) => Container(
      alignment: a,
      padding: const EdgeInsets.symmetric(horizontal: 26),
      color: p.tint(c),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [Icon(i, size: 19, color: c), const SizedBox(width: 8), Text(l, style: T.label.copyWith(color: c))],
      ),
    );
    return Dismissible(
      key: ValueKey(id),
      direction: onStart == null ? (onEnd == null ? DismissDirection.none : DismissDirection.endToStart) : (onEnd == null ? DismissDirection.startToEnd : DismissDirection.horizontal),
      background: back(AlignmentDirectional.centerStart, startIcon, startLabel, p.accent),
      secondaryBackground: back(AlignmentDirectional.centerEnd, endIcon, endLabel, endBad ? p.bad : p.warn),
      dismissThresholds: const {DismissDirection.startToEnd: .28, DismissDirection.endToStart: .34},
      onUpdate: (d) {
        if (d.reached && !d.previousReached) Tap.mid();
      },
      confirmDismiss: (d) async => d == DismissDirection.startToEnd ? await onStart!() : await onEnd!(),
      child: child,
    );
  }
}
