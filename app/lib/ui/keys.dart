// Putting the keyboard away. Return writes a new line in the message box and an iPhone has no back key, so a tap
// anywhere outside a text box closes the keyboard, and so does swiping down.
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';

import '../core/native.dart';

/// Close the keyboard, whatever holds it open.
void hideKeyboard() {
  FocusManager.instance.primaryFocus?.unfocus();
  SystemChannels.textInput.invokeMethod<void>('TextInput.hide').catchError((_) {});
  endEditing();
}

/// Wraps the whole app. What sits in a [TextFieldTapRegion] (a text box, its menu, the composer's buttons) keeps the
/// keyboard up.
class KeyboardAway extends StatefulWidget {
  const KeyboardAway({super.key, required this.child});
  final Widget child;
  @override
  State<KeyboardAway> createState() => _KeyboardAwayState();
}

class _KeyboardAwayState extends State<KeyboardAway> {
  int? _pointer;
  Offset _from = Offset.zero;
  bool _typing = false, _editable = false, _moved = false;

  bool get _up => View.of(context).viewInsets.bottom > 0;

  void _down(PointerDownEvent e) {
    if (_pointer != null || !_up) {
      _pointer = null; // a second finger: neither a tap nor a swipe
      return;
    }
    final hit = HitTestResult();
    WidgetsBinding.instance.hitTestInView(hit, e.position, e.viewId);
    _pointer = e.pointer;
    _from = e.position;
    _moved = false;
    _typing = _editable = false;
    for (final x in hit.path) {
      final o = x.target;
      if (o is RenderEditable) _editable = true;
      if (o is RenderTapRegion && o.groupId == EditableText) _typing = true;
    }
  }

  void _move(PointerMoveEvent e) {
    if (e.pointer != _pointer) return;
    final d = e.position - _from;
    if (d.distance > kTouchSlop) _moved = true;
    // in the text itself a drag moves the caret or scrolls
    if (!_editable && d.dy > 44 && d.dy > d.dx.abs() * 1.6) {
      _pointer = null;
      if (_up) hideKeyboard();
    }
  }

  void _lift(PointerUpEvent e) {
    if (e.pointer != _pointer) return;
    _pointer = null;
    if (!_moved && !_typing && _up) hideKeyboard(); // before the tap's own handler, which may open it again
  }

  @override
  Widget build(BuildContext context) => Listener(
    behavior: HitTestBehavior.translucent,
    onPointerDown: _down,
    onPointerMove: _move,
    onPointerUp: _lift,
    onPointerCancel: (e) => _pointer = null,
    child: widget.child,
  );
}
