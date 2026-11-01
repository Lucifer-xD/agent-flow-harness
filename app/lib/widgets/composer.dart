// The message box at the bottom of a chat: grows with the text, holds optional chips (like "Run on
// PC") under it, and its send button turns into a stop button while a reply is running.
import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../theme.dart';
import 'common.dart';

class Composer extends StatelessWidget {
  const Composer({
    super.key,
    required this.controller,
    required this.focus,
    required this.busy,
    required this.onSend,
    required this.onStop,
    required this.bottom,
    required this.hint,
    this.sendWhileBusy = false,
    this.top,
    this.tools = const [],
    this.attached = false,
  });
  final TextEditingController controller;
  final FocusNode focus;
  final bool busy;
  final VoidCallback onSend, onStop;
  final double bottom;
  final String hint;
  final bool sendWhileBusy; // remote runs take more messages while they work
  final Widget? top; // shown above the box (approvals in a remote thread)
  final List<Widget> tools; // chips along the bottom edge of the box
  final bool attached; // photos are attached: sending with no text is fine

  @override
  Widget build(BuildContext context) {
    final keyboard = MediaQuery.viewInsetsOf(context).bottom > 0;
    final has = controller.text.trim().isNotEmpty || attached;
    final stop = busy && !(sendWhileBusy && has);
    return Padding(
      padding: EdgeInsets.fromLTRB(12, 4, 12, keyboard ? 8 : (bottom > 0 ? bottom + 6 : 12)),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          ?top,
          ListenableBuilder(
            listenable: focus,
            builder: (context, _) => AnimatedContainer(
              duration: Afh.fast,
              decoration: BoxDecoration(
                color: Afh.surface,
                borderRadius: BorderRadius.circular(Afh.rLg),
                border: Border.all(color: focus.hasFocus ? Afh.line2 : Afh.line),
                boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: Afh.p.dark ? 0.25 : 0.05), blurRadius: 18, offset: const Offset(0, 6))],
              ),
              padding: const EdgeInsets.fromLTRB(16, 4, 8, 8),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  TextField(
                    controller: controller,
                    focusNode: focus,
                    minLines: 1,
                    maxLines: 7,
                    textCapitalization: TextCapitalization.sentences,
                    style: TextStyle(fontSize: 16, height: 1.4, color: Afh.text),
                    decoration: InputDecoration(
                      hintText: hint,
                      hintMaxLines: 1,
                      filled: false,
                      isDense: true,
                      border: InputBorder.none,
                      enabledBorder: InputBorder.none,
                      focusedBorder: InputBorder.none,
                      contentPadding: const EdgeInsets.fromLTRB(0, 12, 0, 8),
                    ),
                  ),
                  Row(
                    children: [
                      Expanded(
                        child: SingleChildScrollView(
                          scrollDirection: Axis.horizontal,
                          child: Row(children: [for (final t in tools) Padding(padding: const EdgeInsets.only(right: 6), child: t)]),
                        ),
                      ),
                      AnimatedSwitcher(
                        duration: Afh.fast,
                        transitionBuilder: (c, a) => ScaleTransition(scale: a, child: FadeTransition(opacity: a, child: c)),
                        child: stop
                            ? SendButton(key: const ValueKey('stop'), icon: LucideIcons.square, onTap: onStop, stop: true)
                            : SendButton(key: const ValueKey('send'), icon: LucideIcons.arrowUp, onTap: has ? onSend : null),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class SendButton extends StatelessWidget {
  const SendButton({super.key, required this.icon, this.onTap, this.stop = false});
  final IconData icon;
  final VoidCallback? onTap;
  final bool stop;
  @override
  Widget build(BuildContext context) {
    final on = onTap != null;
    final bg = stop ? Afh.text : (on ? Afh.accent : Afh.surface3);
    final fg = stop ? Afh.bg : (on ? Afh.onAccent : Afh.text3);
    return Semantics(
      button: true,
      label: stop ? 'Stop' : 'Send',
      child: Pressable(
        onTap: onTap,
        scale: 0.88,
        child: AnimatedContainer(
          duration: Afh.fast,
          width: 36,
          height: 36,
          decoration: BoxDecoration(shape: BoxShape.circle, color: bg),
          child: Icon(icon, size: stop ? 14 : 19, color: fg, fill: stop ? 1 : null),
        ),
      ),
    );
  }
}

/// A small toggle chip inside the composer.
class ComposerChip extends StatelessWidget {
  const ComposerChip({super.key, required this.icon, required this.label, this.on = false, this.onTap});
  final IconData icon;
  final String label;
  final bool on;
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) {
    return Pressable(
      onTap: onTap,
      child: AnimatedContainer(
        duration: Afh.fast,
        height: 32,
        padding: const EdgeInsets.symmetric(horizontal: 11),
        decoration: BoxDecoration(
          color: on ? Afh.tint : Colors.transparent,
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: on ? Afh.accent.withValues(alpha: 0.45) : Afh.line),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 15, color: on ? Afh.accent : Afh.text2),
            const SizedBox(width: 6),
            ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 170),
              child: Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: 13, fontWeight: FontWeight.w500, color: on ? Afh.accent : Afh.text2),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
