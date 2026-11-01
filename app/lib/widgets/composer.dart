// The message box at the bottom of a chat: grows with the text, and its send button turns into a
// stop button while a reply is running.
import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';

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
  });
  final TextEditingController controller;
  final FocusNode focus;
  final bool busy;
  final VoidCallback onSend, onStop;
  final double bottom;
  final String hint;
  final bool sendWhileBusy; // remote runs take more messages while they work
  final Widget? top; // shown above the box (approvals in a remote thread)

  @override
  Widget build(BuildContext context) {
    final keyboard = MediaQuery.viewInsetsOf(context).bottom > 0;
    final has = controller.text.trim().isNotEmpty;
    final stop = busy && !(sendWhileBusy && has);
    return Padding(
      padding: EdgeInsets.fromLTRB(12, 6, 12, keyboard ? 10 : (bottom > 0 ? bottom : 12)),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          ?top,
          Glass(
            radius: 28,
            padding: const EdgeInsets.fromLTRB(18, 4, 6, 4),
            color: Afh.surface2.withValues(alpha: 0.85),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(
                  child: TextField(
                    controller: controller,
                    focusNode: focus,
                    minLines: 1,
                    maxLines: 6,
                    textCapitalization: TextCapitalization.sentences,
                    style: const TextStyle(fontSize: 16, height: 1.4),
                    decoration: InputDecoration(
                      hintText: hint,
                      hintMaxLines: 1,
                      filled: false,
                      border: InputBorder.none,
                      enabledBorder: InputBorder.none,
                      focusedBorder: InputBorder.none,
                      contentPadding: const EdgeInsets.symmetric(vertical: 14),
                    ),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.only(bottom: 4, left: 6),
                  child: AnimatedSwitcher(
                    duration: const Duration(milliseconds: 320),
                    switchInCurve: Afh.spring,
                    transitionBuilder: (c, a) => RotationTransition(
                      turns: Tween(begin: 0.6, end: 1.0).animate(a),
                      child: ScaleTransition(scale: a, child: c),
                    ),
                    child: stop
                        ? RoundButton(
                            key: const ValueKey('stop'),
                            onTap: onStop,
                            filled: false,
                            child: const Icon(Icons.stop_rounded, color: Afh.text, size: 22),
                          )
                        : RoundButton(
                            key: const ValueKey('send'),
                            onTap: has ? onSend : null,
                            filled: has,
                            child: Icon(Icons.arrow_upward_rounded, color: has ? const Color(0xFF1A0D05) : Afh.text3, size: 22),
                          ),
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

class RoundButton extends StatelessWidget {
  const RoundButton({super.key, required this.child, this.onTap, this.filled = true});
  final Widget child;
  final VoidCallback? onTap;
  final bool filled;
  @override
  Widget build(BuildContext context) {
    final stop = !filled && onTap != null;
    return Pressable(
      onTap: onTap,
      scale: 0.88,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 250),
        width: 44,
        height: 44,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: filled ? Afh.grad : null,
          color: filled ? null : Afh.surface3,
          border: stop ? Border.all(color: Afh.orange.withValues(alpha: 0.6), width: 1.5) : null,
          boxShadow: filled ? [BoxShadow(color: Afh.pink.withValues(alpha: 0.4), blurRadius: 16, spreadRadius: -4)] : null,
        ),
        child: Center(child: child),
      ),
    ).animate(target: stop ? 1 : 0, onPlay: (c) => stop ? c.repeat(reverse: true) : null).scaleXY(end: 1.06, duration: 700.ms);
  }
}
