// Shared building blocks of the Studio look: buttons, grouped rows, section labels, status dots,
// sheets and dialogs, empty states and toasts. Everything reads its colours from Afh (theme.dart).
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../theme.dart';

/// Gives a little under the finger and settles back; a light haptic on tap.
class Pressable extends StatefulWidget {
  const Pressable({super.key, required this.child, this.onTap, this.onLongPress, this.scale = 0.97, this.haptic = true});
  final Widget child;
  final VoidCallback? onTap;
  final VoidCallback? onLongPress;
  final double scale;
  final bool haptic;
  @override
  State<Pressable> createState() => _PressableState();
}

class _PressableState extends State<Pressable> {
  bool _down = false;
  @override
  Widget build(BuildContext context) {
    final on = widget.onTap != null || widget.onLongPress != null;
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTapDown: on ? (_) => setState(() => _down = true) : null,
      onTapUp: on ? (_) => setState(() => _down = false) : null,
      onTapCancel: () => setState(() => _down = false),
      onTap: widget.onTap == null
          ? null
          : () {
              if (widget.haptic) HapticFeedback.selectionClick();
              widget.onTap!();
            },
      onLongPress: widget.onLongPress == null
          ? null
          : () {
              HapticFeedback.mediumImpact();
              setState(() => _down = false);
              widget.onLongPress!();
            },
      child: AnimatedScale(
        scale: _down ? widget.scale : 1,
        duration: Duration(milliseconds: _down ? 80 : 300),
        curve: _down ? Curves.easeOut : Curves.easeOutBack,
        child: AnimatedOpacity(opacity: _down ? 0.82 : 1, duration: const Duration(milliseconds: 120), child: widget.child),
      ),
    );
  }
}

/// The main action: a solid accent button.
class PrimaryButton extends StatelessWidget {
  const PrimaryButton({super.key, required this.label, this.onTap, this.icon, this.busy = false, this.height = 50, this.expand = true});
  final String label;
  final VoidCallback? onTap;
  final IconData? icon;
  final bool busy;
  final double height;
  final bool expand;
  @override
  Widget build(BuildContext context) {
    final enabled = onTap != null && !busy;
    final fg = Afh.onAccent;
    return Pressable(
      onTap: enabled ? onTap : null,
      child: AnimatedContainer(
        duration: Afh.fast,
        height: height,
        width: expand ? double.infinity : null,
        padding: const EdgeInsets.symmetric(horizontal: 20),
        decoration: BoxDecoration(
          color: enabled || busy ? Afh.accent : Afh.surface3,
          borderRadius: BorderRadius.circular(Afh.r),
        ),
        alignment: Alignment.center,
        child: AnimatedSwitcher(
          duration: Afh.fast,
          child: busy
              ? SizedBox(key: const ValueKey('busy'), width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2.2, color: fg))
              : Row(
                  key: const ValueKey('label'),
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (icon != null) ...[Icon(icon, size: 18, color: enabled ? fg : Afh.text3), const SizedBox(width: 8)],
                    Text(
                      label,
                      style: TextStyle(fontFamily: Afh.body, fontWeight: FontWeight.w600, fontSize: 15.5, color: enabled ? fg : Afh.text3),
                    ),
                  ],
                ),
        ),
      ),
    );
  }
}

/// A quiet button: surface fill and a hairline border.
class SecondaryButton extends StatelessWidget {
  const SecondaryButton({super.key, required this.label, this.onTap, this.icon, this.danger = false, this.height = 44, this.expand = false});
  final String label;
  final VoidCallback? onTap;
  final IconData? icon;
  final bool danger;
  final double height;
  final bool expand;
  @override
  Widget build(BuildContext context) {
    final c = danger ? Afh.bad : Afh.text;
    return Pressable(
      onTap: onTap,
      child: Container(
        height: height,
        width: expand ? double.infinity : null,
        padding: const EdgeInsets.symmetric(horizontal: 16),
        decoration: BoxDecoration(color: Afh.surface, borderRadius: BorderRadius.circular(Afh.r), border: Border.all(color: Afh.line)),
        child: Row(
          mainAxisSize: expand ? MainAxisSize.max : MainAxisSize.min,
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            if (icon != null) ...[Icon(icon, size: 17, color: danger ? Afh.bad : Afh.text2), const SizedBox(width: 8)],
            Text(label, style: TextStyle(fontWeight: FontWeight.w600, fontSize: 14.5, color: onTap == null ? Afh.text3 : c)),
          ],
        ),
      ),
    );
  }
}

/// A round icon button with a generous touch target.
class IconBtn extends StatelessWidget {
  const IconBtn(this.icon, {super.key, this.onTap, this.tooltip, this.size = 40, this.iconSize = 21, this.color, this.filled = false});
  final IconData icon;
  final VoidCallback? onTap;
  final String? tooltip;
  final double size, iconSize;
  final Color? color;
  final bool filled;
  @override
  Widget build(BuildContext context) {
    Widget b = Pressable(
      onTap: onTap,
      scale: 0.9,
      child: Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: filled ? Afh.surface2 : Colors.transparent,
          border: filled ? Border.all(color: Afh.line) : null,
        ),
        child: Icon(icon, size: iconSize, color: onTap == null ? Afh.text3.withValues(alpha: 0.5) : (color ?? Afh.text)),
      ),
    );
    if (tooltip != null) b = Tooltip(message: tooltip!, child: b);
    return Semantics(button: true, label: tooltip, child: b);
  }
}

/// A rounded group of rows with hairline dividers, like an iOS settings section.
class Group extends StatelessWidget {
  const Group({super.key, required this.children, this.margin = EdgeInsets.zero, this.inset = 52});
  final List<Widget> children;
  final EdgeInsets margin;
  final double inset; // where the divider starts, to line up with the row text
  @override
  Widget build(BuildContext context) {
    return Container(
      margin: margin,
      decoration: BoxDecoration(color: Afh.surface, borderRadius: BorderRadius.circular(Afh.r), border: Border.all(color: Afh.line)),
      clipBehavior: Clip.antiAlias,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          for (var i = 0; i < children.length; i++) ...[
            if (i > 0) Padding(padding: EdgeInsets.only(left: inset), child: Divider(height: 1, color: Afh.line)),
            children[i],
          ],
        ],
      ),
    );
  }
}

/// One row: an icon, a title with an optional subtitle, and a trailing widget or chevron.
class Tile extends StatelessWidget {
  const Tile({
    super.key,
    this.icon,
    this.leading,
    required this.title,
    this.subtitle,
    this.trailing,
    this.onTap,
    this.onLongPress,
    this.danger = false,
    this.chevron,
    this.dense = false,
  });
  final IconData? icon;
  final Widget? leading;
  final String title;
  final String? subtitle;
  final Widget? trailing;
  final VoidCallback? onTap;
  final VoidCallback? onLongPress;
  final bool danger;
  final bool? chevron;
  final bool dense;
  @override
  Widget build(BuildContext context) {
    final color = danger ? Afh.bad : Afh.text;
    final showChevron = chevron ?? (onTap != null && trailing == null && !danger);
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap == null
            ? null
            : () {
                HapticFeedback.selectionClick();
                onTap!();
              },
        onLongPress: onLongPress,
        child: ConstrainedBox(
          constraints: BoxConstraints(minHeight: dense ? 44 : 52),
          child: Padding(
            padding: EdgeInsets.symmetric(horizontal: 16, vertical: dense ? 8 : 11),
            child: Row(
              children: [
                if (leading != null) ...[leading!, const SizedBox(width: 14)] else if (icon != null) ...[
                  Icon(icon, size: 20, color: danger ? Afh.bad : Afh.text2),
                  const SizedBox(width: 16),
                ],
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(title, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w500, color: color, height: 1.25)),
                      if (subtitle != null && subtitle!.isNotEmpty) ...[
                        const SizedBox(height: 2),
                        Text(subtitle!, maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 13, color: Afh.text3, height: 1.3)),
                      ],
                    ],
                  ),
                ),
                if (trailing != null) ...[const SizedBox(width: 10), trailing!],
                if (showChevron) ...[const SizedBox(width: 6), Icon(LucideIcons.chevronRight, size: 18, color: Afh.text3)],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// A small uppercase label above a group.
class SectionLabel extends StatelessWidget {
  const SectionLabel(this.text, {super.key, this.padding = const EdgeInsets.fromLTRB(4, 22, 4, 8), this.trailing});
  final String text;
  final EdgeInsets padding;
  final Widget? trailing;
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: padding,
      child: Row(
        children: [
          Expanded(child: Text(text.toUpperCase(), style: Afh.label)),
          ?trailing,
        ],
      ),
    );
  }
}

/// A status dot; while `live` a soft ring breathes out of it.
class PulseDot extends StatelessWidget {
  const PulseDot({super.key, required this.color, this.live = true, this.size = 8});
  final Color color;
  final bool live;
  final double size;
  @override
  Widget build(BuildContext context) {
    final dot = Container(width: size, height: size, decoration: BoxDecoration(color: color, shape: BoxShape.circle));
    if (!live) return SizedBox(width: size * 2, height: size * 2, child: Center(child: dot));
    return SizedBox(
      width: size * 2,
      height: size * 2,
      child: Stack(
        alignment: Alignment.center,
        children: [
          Container(width: size, height: size, decoration: BoxDecoration(color: color.withValues(alpha: 0.45), shape: BoxShape.circle))
              .animate(onPlay: (c) => c.repeat())
              .scale(begin: const Offset(1, 1), end: const Offset(2.4, 2.4), duration: 1800.ms, curve: Curves.easeOut)
              .fadeOut(duration: 1800.ms),
          dot,
        ],
      ),
    );
  }
}

/// A small rounded label, e.g. "Working" or "Needs you".
class Pill extends StatelessWidget {
  const Pill(this.text, {super.key, this.color, this.icon});
  final String text;
  final Color? color;
  final IconData? icon;
  @override
  Widget build(BuildContext context) {
    final c = color ?? Afh.text2;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(color: c.withValues(alpha: Afh.p.dark ? 0.14 : 0.11), borderRadius: BorderRadius.circular(7)),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[Icon(icon, size: 12, color: c), const SizedBox(width: 4)],
          Text(text, style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w600, color: c, height: 1.2)),
        ],
      ),
    );
  }
}

/// Three dots fading in turn while a reply is on its way.
class TypingDots extends StatelessWidget {
  const TypingDots({super.key, this.color});
  final Color? color;
  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        for (var i = 0; i < 3; i++)
          Container(
                width: 6,
                height: 6,
                margin: const EdgeInsets.symmetric(horizontal: 2.5),
                decoration: BoxDecoration(color: color ?? Afh.text2, shape: BoxShape.circle),
              )
              .animate(onPlay: (c) => c.repeat(), delay: (i * 160).ms)
              .fade(begin: 0.25, end: 1, duration: 420.ms, curve: Curves.easeOut)
              .then()
              .fade(begin: 1, end: 0.25, duration: 420.ms, curve: Curves.easeIn)
              .then(delay: 220.ms),
      ],
    );
  }
}

/// A flat square holding an icon.
class IconTile extends StatelessWidget {
  const IconTile(this.icon, {super.key, this.size = 40, this.active = false, this.color});
  final IconData icon;
  final double size;
  final bool active;
  final Color? color;
  @override
  Widget build(BuildContext context) {
    final c = color ?? (active ? Afh.accent : Afh.text2);
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: color != null ? c.withValues(alpha: 0.13) : (active ? Afh.tint : Afh.surface2),
        borderRadius: BorderRadius.circular(size * 0.3),
      ),
      child: Icon(icon, size: size * 0.48, color: c),
    );
  }
}

/// A round letter avatar.
class Avatar extends StatelessWidget {
  const Avatar(this.text, {super.key, this.size = 34, this.color});
  final String text;
  final double size;
  final Color? color;
  @override
  Widget build(BuildContext context) {
    final c = color ?? Afh.accent;
    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(shape: BoxShape.circle, color: c.withValues(alpha: Afh.p.dark ? 0.18 : 0.14)),
      child: Text(
        text.isEmpty ? '?' : text.characters.first.toUpperCase(),
        style: TextStyle(fontWeight: FontWeight.w600, fontSize: size * 0.4, color: c),
      ),
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
      padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 36),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          art ??
              Container(
                width: 56,
                height: 56,
                decoration: BoxDecoration(color: Afh.surface2, shape: BoxShape.circle, border: Border.all(color: Afh.line)),
                child: Icon(icon, size: 24, color: Afh.text2),
              ).animate().scale(begin: const Offset(0.85, 0.85), duration: 400.ms, curve: Curves.easeOutBack).fadeIn(),
          const SizedBox(height: 18),
          Text(title, textAlign: TextAlign.center, style: Afh.h3()).animate().fadeIn(delay: 80.ms),
          const SizedBox(height: 6),
          Text(text, textAlign: TextAlign.center, style: TextStyle(color: Afh.text2, fontSize: 14, height: 1.45)).animate().fadeIn(delay: 140.ms),
          if (action != null) ...[const SizedBox(height: 20), action!.animate().fadeIn(delay: 200.ms)],
        ],
      ),
    );
  }
}

/// Fades a page's content in and lifts it a few pixels: the one entrance animation used everywhere.
extension Enter on Widget {
  Widget enter([int i = 0]) {
    final d = (35 * i.clamp(0, 10)).ms;
    return animate().fadeIn(delay: d, duration: 280.ms).moveY(begin: 8, end: 0, delay: d, duration: 380.ms, curve: Afh.ease);
  }
}

class SheetAction<T> {
  const SheetAction(this.icon, this.label, this.value, {this.danger = false, this.subtitle});
  final IconData icon;
  final String label;
  final T value;
  final bool danger;
  final String? subtitle;
}

/// A bottom sheet with a title and a list of actions; returns the picked value.
Future<T?> showActions<T>(BuildContext context, {String? title, required List<SheetAction<T>> actions}) {
  HapticFeedback.selectionClick();
  return showModalBottomSheet<T>(
    context: context,
    builder: (ctx) => SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 0, 12, 10),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (title != null)
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
                child: Text(title, maxLines: 2, overflow: TextOverflow.ellipsis, style: Afh.h3()),
              ),
            Group(
              children: [
                for (final a in actions)
                  Tile(icon: a.icon, title: a.label, subtitle: a.subtitle, danger: a.danger, chevron: false, onTap: () => Navigator.pop(ctx, a.value)),
              ],
            ),
          ],
        ),
      ),
    ),
  );
}

/// A yes/no dialog; true when confirmed.
Future<bool> confirm(BuildContext context, {required String title, String? text, String action = 'OK', bool danger = false}) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(title),
      content: text == null ? null : Text(text),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text('Cancel', style: TextStyle(color: Afh.text2))),
        TextButton(
          onPressed: () => Navigator.pop(ctx, true),
          child: Text(action, style: TextStyle(color: danger ? Afh.bad : Afh.accent, fontWeight: FontWeight.w600)),
        ),
      ],
    ),
  );
  return ok == true;
}

/// A small dialog with one text field.
Future<String?> promptText(BuildContext context, {required String title, String initial = '', String hint = '', int lines = 1, String action = 'Save'}) {
  final ctl = TextEditingController(text: initial);
  return showDialog<String>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(title),
      content: TextField(
        controller: ctl,
        autofocus: true,
        minLines: lines,
        maxLines: lines == 1 ? 1 : 10,
        textCapitalization: TextCapitalization.sentences,
        decoration: InputDecoration(hintText: hint),
        onSubmitted: lines == 1 ? (v) => Navigator.pop(ctx, v) : null,
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx), child: Text('Cancel', style: TextStyle(color: Afh.text2))),
        TextButton(
          onPressed: () => Navigator.pop(ctx, ctl.text),
          child: Text(action, style: TextStyle(color: Afh.accent, fontWeight: FontWeight.w600)),
        ),
      ],
    ),
  );
}

/// The height of the phone's home indicator / navigation bar, read from the window itself because
/// nested Scaffolds strip it from MediaQuery.
double safeBottom(BuildContext context) {
  final v = View.of(context);
  return v.padding.bottom / v.devicePixelRatio;
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

/// "Today", "Yesterday", "Previous 7 days", "Previous 30 days" or the month, for grouping lists.
String dayGroup(DateTime t) {
  final now = DateTime.now();
  final days = DateTime(now.year, now.month, now.day).difference(DateTime(t.year, t.month, t.day)).inDays;
  if (days <= 0) return 'Today';
  if (days == 1) return 'Yesterday';
  if (days < 7) return 'Previous 7 days';
  if (days < 30) return 'Previous 30 days';
  const months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  return t.year == now.year ? months[t.month - 1] : '${months[t.month - 1]} ${t.year}';
}

void showToast(BuildContext context, String message, {bool error = false}) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(
      SnackBar(
        content: Row(
          children: [
            Icon(error ? LucideIcons.circleAlert : LucideIcons.circleCheck, color: error ? Afh.bad : Afh.good, size: 18),
            const SizedBox(width: 10),
            Expanded(child: Text(message)),
          ],
        ),
        duration: Duration(milliseconds: error ? 4200 : 2400),
      ),
    );
}
