// The box you write in: text, photos, files, voice; "/" commands and "@" files where they mean something.
import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';

import '../core/l10n.dart';
import '../core/store.dart';
import '../core/voice.dart';
import 'kit.dart';
import 'look.dart';
import 'media.dart';
import 'motion.dart';

/// Something to finish the word being typed with.
class Hint {
  const Hint(this.insert, this.title, {this.sub = '', this.icon = LucideIcons.slash});
  final String insert, title, sub;
  final IconData icon;
}

class Composer extends StatefulWidget {
  const Composer({
    super.key,
    required this.onSend,
    this.hint = '',
    this.draft,
    this.running = false,
    this.onStop,
    this.chips = const [],
    this.suggest,
    this.focus,
    this.auto = false,
    this.controller,
    this.files,
    this.above,
    this.extra = const [],
    this.busy = false,
    this.canSend = true,
    this.onVoice,
  });

  /// True: sent, so the box stays empty.
  final FutureOr<bool> Function(String text, List<Att> files) onSend;
  final String hint;
  final String? draft; // where an unfinished message is kept
  final bool running, auto, busy, canSend;
  final VoidCallback? onStop, onVoice;
  final List<Widget> chips, extra;
  final Future<List<Hint>> Function(String sign, String word)? suggest;
  final FocusNode? focus;
  final TextEditingController? controller;
  final List<Att>? files;
  final Widget? above;

  @override
  State<Composer> createState() => _ComposerState();
}

class _ComposerState extends State<Composer> {
  late final TextEditingController _c = widget.controller ?? TextEditingController();
  late final FocusNode _f = widget.focus ?? FocusNode();
  late final List<Att> _files = widget.files ?? [];
  List<Hint> _hints = const [];
  String _sign = '';
  int _ask = 0;
  Timer? _save;
  bool _dictating = false;
  String _before = '';

  @override
  void initState() {
    super.initState();
    if (widget.draft != null && _c.text.isEmpty) _c.text = Settings.i.str('draft.${widget.draft}');
    _c.addListener(_typed);
    _f.addListener(_redraw);
    Voice.i.addListener(_voice);
  }

  void _redraw() => mounted ? setState(() {}) : null;
  void _keep() => Settings.i.put('draft.${widget.draft}', _c.text.isEmpty ? null : _c.text, quiet: true);

  @override
  void dispose() {
    _save?.cancel();
    if (widget.draft != null) _keep();
    if (_dictating) Voice.i.stopListening(cancel: true);
    Voice.i.removeListener(_voice);
    _c.removeListener(_typed);
    _f.removeListener(_redraw);
    if (widget.controller == null) _c.dispose();
    if (widget.focus == null) _f.dispose();
    super.dispose();
  }

  void _voice() {
    if (!mounted) return;
    if (_dictating && !Voice.i.listening) _dictating = false;
    setState(() {});
  }

  void _typed() {
    setState(() {});
    if (widget.draft != null) {
      _save?.cancel();
      _save = Timer(const Duration(milliseconds: 700), _keep);
    }
    if (widget.suggest == null) return;
    final at = _c.selection.baseOffset;
    final text = at >= 0 && at <= _c.text.length ? _c.text.substring(0, at) : _c.text;
    final m = RegExp(r'(?:^|\s)([@/])([^\s]*)$').firstMatch(text);
    if (m == null || (m[1] == '/' && m.start != 0)) {
      if (_hints.isNotEmpty) setState(() => _hints = const []);
      _ask++;
      return;
    }
    final n = ++_ask;
    _sign = m[1]!;
    Future.delayed(Duration(milliseconds: _sign == '@' ? 160 : 0), () async {
      if (n != _ask) return;
      final got = await widget.suggest!(m[1]!, m[2]!);
      if (n == _ask && mounted) setState(() => _hints = got);
    });
  }

  void _take(Hint h) {
    final at = _c.selection.baseOffset < 0 ? _c.text.length : _c.selection.baseOffset;
    final from = _c.text.substring(0, at).lastIndexOf(_sign);
    final text = '${_c.text.substring(0, from)}${h.insert} ${_c.text.substring(at)}';
    _c.value = TextEditingValue(text: text, selection: TextSelection.collapsed(offset: from + h.insert.length + 1));
    setState(() => _hints = const []);
  }

  Future<void> _add() async {
    // iPhone: a keyboard that rises while Apple's picker is still closing is measured too small and covers the box,
    // so it goes down first and comes back once the picker is gone
    if (Platform.isIOS) _f.unfocus();
    final got = await addSheet(context, extra: widget.extra);
    if (got.isEmpty || !mounted) return;
    setState(() => _files.addAll(got));
    if (Platform.isIOS) await Future<void>.delayed(const Duration(milliseconds: 900));
    if (mounted) _f.requestFocus();
  }

  Future<void> _mic() async {
    if (_dictating) {
      await Voice.i.stopListening();
      return;
    }
    _before = _c.text.trim();
    _dictating = true;
    Tap.mid();
    final ok = await Voice.i.listen(
      onText: (s) {
        if (!_dictating || !mounted) return;
        final text = [_before, s].where((x) => x.isNotEmpty).join(' ');
        _c.value = TextEditingValue(text: text, selection: TextSelection.collapsed(offset: text.length));
      },
    );
    if (!ok) {
      _dictating = false;
      if (mounted && Voice.i.error != null) toast(context, Voice.i.error!, bad: true);
    }
    if (mounted) setState(() {});
  }

  Future<void> _send() async {
    final text = _c.text.trim();
    if (text.isEmpty && _files.isEmpty) return;
    if (_dictating) await Voice.i.stopListening();
    Tap.mid();
    final files = [..._files];
    final had = _c.text;
    setState(() {
      _c.clear();
      _files.clear();
      _hints = const [];
    });
    final ok = await widget.onSend(text, files);
    if (!ok && mounted) {
      setState(() {
        if (_c.text.isEmpty) _c.text = had;
        _files.insertAll(0, files);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final has = _c.text.trim().isNotEmpty || _files.isNotEmpty;
    final voiceMode = !has && !widget.running && widget.onVoice != null && !_dictating;
    final stop = !has && widget.running;
    final icon = voiceMode ? LucideIcons.audioLines : (stop ? LucideIcons.square : LucideIcons.arrowUp);
    final act = voiceMode ? widget.onVoice : (stop ? widget.onStop : (has && widget.canSend && !widget.busy ? _send : null));
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        AnimatedSize(
          duration: med,
          curve: Curves.easeOutQuint,
          alignment: Alignment.bottomCenter,
          child: _hints.isEmpty
              ? const SizedBox(width: double.infinity)
              : Container(
                  constraints: const BoxConstraints(maxHeight: 250),
                  margin: const EdgeInsets.only(bottom: 8),
                  clipBehavior: Clip.antiAlias,
                  decoration: BoxDecoration(
                    color: p.raised,
                    borderRadius: BorderRadius.circular(22),
                    border: Border.all(color: p.line),
                  ),
                  child: ListView(
                    shrinkWrap: true,
                    padding: const EdgeInsets.symmetric(vertical: 5),
                    children: [for (final h in _hints) Tile(h.title, sub: h.sub, subMax: 1, icon: h.icon, onTap: () => _take(h))],
                  ),
                ),
        ),
        ?widget.above,
        AnimatedContainer(
          duration: med,
          decoration: BoxDecoration(
            color: p.raised,
            borderRadius: BorderRadius.circular(26),
            border: Border.all(color: _f.hasFocus ? (p.dark ? const Color(0x2EFFFFFF) : const Color(0x24000000)) : p.line),
            boxShadow: [BoxShadow(color: Color(p.dark ? 0x66000000 : 0x12000000), blurRadius: 26, offset: const Offset(0, 8))],
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              AttStrip(_files, onRemove: (a) => setState(() => _files.remove(a))),
              Padding(
                padding: const EdgeInsets.fromLTRB(18, 4, 18, 0),
                child: TextField(
                  controller: _c,
                  focusNode: _f,
                  autofocus: widget.auto,
                  minLines: 1,
                  maxLines: 7,
                  textCapitalization: TextCapitalization.sentences,
                  keyboardType: TextInputType.multiline,
                  textDirection: _c.text.isEmpty ? null : (isRtl(_c.text) ? TextDirection.rtl : TextDirection.ltr),
                  style: T.body.copyWith(color: p.text, height: 1.4),
                  contentInsertionConfiguration: ContentInsertionConfiguration(
                    allowedMimeTypes: const ['image/png', 'image/jpeg', 'image/gif', 'image/webp'],
                    onContentInserted: (c) async {
                      if (!c.hasData) return;
                      final a = await Media.keepBytes(c.data!, 'pasted.${c.mimeType.split('/').last}');
                      if (mounted) setState(() => _files.add(a));
                    },
                  ),
                  decoration: InputDecoration(
                    isDense: true,
                    border: InputBorder.none,
                    contentPadding: const EdgeInsets.only(top: 13, bottom: 8),
                    hintText: _dictating ? t('Listening…') : widget.hint,
                    hintMaxLines: 1,
                    hintStyle: T.body.copyWith(color: p.text3, height: 1.4),
                  ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(7, 0, 7, 7),
                child: Row(
                  children: [
                    Ic(LucideIcons.plus, onTap: _add, size: 38, color: p.text2, tip: t('Add photos and files')),
                    Expanded(
                      child: SingleChildScrollView(
                        scrollDirection: Axis.horizontal,
                        padding: const EdgeInsets.symmetric(horizontal: 4),
                        child: Row(
                          children: [
                            for (final c in widget.chips) Padding(padding: const EdgeInsetsDirectional.only(end: 6), child: c),
                          ],
                        ),
                      ),
                    ),
                    MicBtn(on: _dictating, onTap: _mic),
                    const SizedBox(width: 3),
                    Press(
                      onTap: act,
                      scale: .86,
                      label: voiceMode ? t('Talk') : (stop ? t('Stop') : t('Send')),
                      child: AnimatedContainer(
                        duration: med,
                        curve: Curves.easeOutCubic,
                        width: 38,
                        height: 38,
                        alignment: Alignment.center,
                        decoration: BoxDecoration(color: act == null ? p.fill : p.inv, shape: BoxShape.circle),
                        child: Swap(
                          child: widget.busy
                              ? const Pulse(key: ValueKey('busy'))
                              : Icon(icon, key: ValueKey(icon.codePoint), size: stop ? 14 : 19, color: act == null ? p.text3 : p.onInv),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class MicBtn extends StatelessWidget {
  const MicBtn({super.key, required this.on, required this.onTap});
  final bool on;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final p = context.p;
    return Stack(
      alignment: Alignment.center,
      clipBehavior: Clip.none,
      children: [
        if (on)
          AnimatedContainer(
            duration: const Duration(milliseconds: 120),
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              boxShadow: [BoxShadow(color: p.accent.withValues(alpha: .28), spreadRadius: 9 * Voice.i.level)],
            ),
          ),
        Ic(
          on ? LucideIcons.square : LucideIcons.mic,
          onTap: onTap,
          size: 38,
          icon_: on ? 14 : 20,
          color: on ? p.onAccent : p.text2,
          fill: on ? p.accent : null,
          tip: on ? t('Stop dictating') : t('Dictate'),
        ),
      ],
    );
  }
}

/// A chip inside the composer.
class CChip extends StatelessWidget {
  const CChip(this.label, {super.key, this.icon, this.lead, this.onTap, this.on = false, this.max = 130});
  final String label;
  final IconData? icon;
  final Widget? lead;
  final VoidCallback? onTap;
  final bool on;
  final double max;
  @override
  Widget build(BuildContext context) {
    final p = context.p;
    return Press(
      onTap: onTap,
      scale: .93,
      child: Container(
        height: 32,
        padding: const EdgeInsets.symmetric(horizontal: 10),
        decoration: BoxDecoration(
          color: on ? p.tint(p.accent) : Colors.transparent,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: on ? Colors.transparent : p.line),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (lead != null) ...[lead!, if (label.isNotEmpty) const SizedBox(width: 6)],
            if (icon != null) ...[Icon(icon, size: 14, color: on ? p.accent : p.text2), if (label.isNotEmpty) const SizedBox(width: 6)],
            if (label.isNotEmpty)
              ConstrainedBox(
                constraints: BoxConstraints(maxWidth: max),
                child: Text(
                  label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: T.label.copyWith(color: on ? p.accent : p.text2),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
