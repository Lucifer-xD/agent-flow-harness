// What a thread needs from you: permission for a step, an answer, or a choice between designs.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';

import '../core/hub.dart';
import '../core/l10n.dart';
import '../core/relay.dart';
import '../ui/diff.dart';
import '../ui/kit.dart';
import '../ui/look.dart';
import '../ui/motion.dart';

/// What it wants to do, in a few words, with an icon.
(IconData, String) askTitle(Ask a) {
  if (a.isQuestion) return (LucideIcons.messageCircleQuestionMark, t('A question for you'));
  if (a.isDesign) return (LucideIcons.palette, '${a.meta['title'] ?? t('Choose a design')}');
  final d = '${a.meta['description'] ?? a.meta['title'] ?? ''}'.trim();
  return switch (a.action) {
    'shell' => (LucideIcons.terminal, d.isEmpty ? t('Run a command') : d),
    'edit' || 'write' => (LucideIcons.filePen, asList(a.meta['files']).length > 1 ? t('Change {} files', asList(a.meta['files']).length) : t('Change {}', baseName(a.resources.firstOrNull ?? ''))),
    'read' => (LucideIcons.fileText, t('Read {}', baseName(a.resources.firstOrNull ?? ''))),
    'web' => (LucideIcons.globe, t('Open {}', Uri.tryParse(a.resources.firstOrNull ?? '')?.host ?? t('a page'))),
    'chrome' => (LucideIcons.globe, t('Use {} in Chrome', a.resources.firstOrNull ?? '')),
    'computer' => (LucideIcons.mouse, t('Use the computer')),
    'mcp' => (LucideIcons.plug, t('Use {}', a.resources.firstOrNull ?? '')),
    'skill' => (LucideIcons.sparkles, t('Use the skill {}', a.resources.firstOrNull ?? '')),
    'subagent' => (LucideIcons.users, d.isEmpty ? t('Start a subagent') : d),
    'threads' => (LucideIcons.messagesSquare, t('Read another thread')),
    _ => (LucideIcons.shield, d.isEmpty ? a.action : d),
  };
}

class AskCard extends StatefulWidget {
  const AskCard(this.ask, {super.key, this.showThread = false, this.onOpen});
  final Ask ask;
  final bool showThread;
  final VoidCallback? onOpen;
  @override
  State<AskCard> createState() => _AskCardState();
}

class _AskCardState extends State<AskCard> {
  Ask get a => widget.ask;
  bool _busy = false;
  late final _qs = asList(a.meta['questions']);
  late final List<Set<String>> _sel = [for (final _ in _qs) <String>{}];
  late final List<TextEditingController> _other = [for (final _ in _qs) TextEditingController()];
  int _at = 0;

  @override
  void dispose() {
    for (final c in _other) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _reply(String decision, {String? message, List<J>? answers}) async {
    if (_busy) return;
    setState(() => _busy = true);
    decision == 'reject' ? Tap.heavy() : Tap.mid();
    try {
      await a.reply(decision, message: message, answers: answers);
    } catch (e) {
      if (mounted) {
        setState(() => _busy = false);
        toast(context, '$e', bad: true);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final (icon, title) = askTitle(a);
    return Container(
      decoration: BoxDecoration(
        color: p.raised,
        borderRadius: BorderRadius.circular(24),
        border: Border.all(color: p.accent.withValues(alpha: .32)),
        boxShadow: [
          BoxShadow(
            color: p.accent.withValues(alpha: p.dark ? .1 : .08),
            blurRadius: 30,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      padding: const EdgeInsets.all(16),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Press(
            onTap: widget.onOpen,
            scale: .985,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Square(icon, color: p.accent, size: 36),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Padding(
                        padding: EdgeInsets.only(top: widget.showThread ? 0 : 7),
                        child: Text(
                          title,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: T.h3.copyWith(color: p.text),
                        ),
                      ),
                      if (widget.showThread)
                        Text(
                          '${a.thread} · ${a.hub.computer.name}',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: T.small.copyWith(color: p.text3),
                        ),
                    ],
                  ),
                ),
                if (widget.onOpen != null) Icon(LucideIcons.arrowUpRight, size: 18, color: p.text3),
              ],
            ),
          ),
          if (a.isQuestion) ..._question() else if (a.isDesign) ..._design() else ..._permission(),
        ],
      ),
    );
  }

  // ---- permission ----

  List<Widget> _permission() {
    final p = context.p;
    final files = asList(a.meta['files']);
    final cmd = '${a.meta['command'] ?? a.meta['script'] ?? ''}'.trim();
    final url = a.action == 'web' ? '${a.meta['url'] ?? ''}' : '';
    return [
      if (cmd.isNotEmpty) ...[
        const SizedBox(height: 12),
        Container(
          constraints: const BoxConstraints(maxHeight: 130),
          width: double.infinity,
          decoration: BoxDecoration(
            color: p.code,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: p.line),
          ),
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(12),
            child: Directionality(
              textDirection: TextDirection.ltr,
              child: Text(cmd, style: T.code.copyWith(color: p.text)),
            ),
          ),
        ),
      ],
      if (url.isNotEmpty) ...[
        const SizedBox(height: 10),
        Text(
          url,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: T.code.copyWith(color: p.text2),
        ),
      ],
      if (files.isNotEmpty) ...[
        const SizedBox(height: 12),
        ConstrainedBox(
          constraints: const BoxConstraints(maxHeight: 280),
          child: SingleChildScrollView(
            child: Column(
              children: [
                for (final (i, f) in files.indexed)
                  Padding(
                    padding: EdgeInsets.only(top: i == 0 ? 0 : 8),
                    child: DiffFile(f, root: dirOf(a.hub.session(a.sid) ?? {}), open: files.length == 1),
                  ),
              ],
            ),
          ),
        ),
      ],
      const SizedBox(height: 14),
      Row(
        children: [
          Expanded(
            child: Btn(t('Deny'), kind: Kind.soft, small: true, onTap: _busy ? null : () => _reply('reject')),
          ),
          const SizedBox(width: 8),
          Expanded(
            flex: 2,
            child: Btn(t('Allow'), small: true, busy: _busy, onTap: () => _reply('once')),
          ),
          const SizedBox(width: 4),
          Ic(
            LucideIcons.ellipsis,
            color: p.text2,
            tip: t('More'),
            onTap: () => actions(context, [
              Act(t('Allow for the rest of this thread'), LucideIcons.checkCheck, () => _reply('always'), sub: t('Never asks for this kind of step again here')),
              Act(t('Deny and say why'), LucideIcons.messageSquareX, () async {
                final m = await askText(context, t('What should it do instead?'), lines: 3, action: t('Deny'));
                if (m != null) _reply('reject', message: m);
              }),
            ]),
          ),
        ],
      ),
    ];
  }

  // ---- question ----

  bool _done(int i) => _sel[i].isNotEmpty || _other[i].text.trim().isNotEmpty;

  void _send() => _reply(
    'answer',
    answers: [
      for (var i = 0; i < _qs.length; i++) {'selected': _sel[i].toList(), 'other': _other[i].text.trim()},
    ],
  );

  List<Widget> _question() {
    final p = context.p;
    if (_qs.isEmpty) return const [];
    final q = _qs[_at];
    final multi = q['multiple'] == true;
    return [
      const SizedBox(height: 14),
      Swap(
        align: Alignment.topLeft,
        child: Column(
          key: ValueKey(_at),
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              '${q['question'] ?? ''}',
              textDirection: isRtl('${q['question'] ?? ''}') ? TextDirection.rtl : TextDirection.ltr,
              style: T.body.copyWith(color: p.text, fontWeight: FontWeight.w500, height: 1.4),
            ),
            const SizedBox(height: 11),
            ConstrainedBox(
              constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(context).height * .34),
              child: SingleChildScrollView(
                child: Column(
                  children: [
                    for (final o in asList(q['options']))
                      Padding(
                        padding: const EdgeInsets.only(bottom: 7),
                        child: Press(
                          scale: .98,
                          onTap: () => setState(() {
                            final l = '${o['label']}';
                            if (multi) {
                              _sel[_at].contains(l) ? _sel[_at].remove(l) : _sel[_at].add(l);
                            } else {
                              _sel[_at]
                                ..clear()
                                ..add(l);
                              _other[_at].clear();
                              if (_at < _qs.length - 1) {
                                Future.delayed(const Duration(milliseconds: 220), () => mounted ? setState(() => _at++) : null);
                              }
                            }
                          }),
                          child: AnimatedContainer(
                            duration: med,
                            width: double.infinity,
                            padding: const EdgeInsets.fromLTRB(14, 11, 12, 11),
                            decoration: BoxDecoration(
                              color: _sel[_at].contains('${o['label']}') ? p.tint(p.accent) : p.fill,
                              borderRadius: BorderRadius.circular(15),
                              border: Border.all(color: _sel[_at].contains('${o['label']}') ? p.accent.withValues(alpha: .5) : Colors.transparent),
                            ),
                            child: Row(
                              children: [
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text('${o['label']}', style: T.row.copyWith(color: p.text)),
                                      if ('${o['description'] ?? ''}'.isNotEmpty) Text('${o['description']}', style: T.small.copyWith(color: p.text2)),
                                    ],
                                  ),
                                ),
                                if (_sel[_at].contains('${o['label']}')) Icon(LucideIcons.check, size: 17, color: p.accent),
                              ],
                            ),
                          ),
                        ),
                      ),
                    Field(
                      _other[_at],
                      hint: t('Something else…'),
                      maxLines: 4,
                      onChanged: (s) => setState(() {
                        if (!multi && s.trim().isNotEmpty) _sel[_at].clear();
                      }),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
      const SizedBox(height: 14),
      Row(
        children: [
          if (_qs.length > 1) ...[
            for (var i = 0; i < _qs.length; i++)
              Press(
                onTap: () => setState(() => _at = i),
                child: Padding(
                  padding: const EdgeInsets.all(4),
                  child: AnimatedContainer(
                    duration: med,
                    width: i == _at ? 20 : 8,
                    height: 8,
                    decoration: BoxDecoration(color: i == _at ? p.text : (_done(i) ? p.accent : p.fill2), borderRadius: BorderRadius.circular(4)),
                  ),
                ),
              ),
            const SizedBox(width: 8),
          ],
          const Spacer(),
          Btn(t('Skip'), kind: Kind.ghost, small: true, wide: false, onTap: _busy ? null : () => _reply('dismiss')),
          const SizedBox(width: 6),
          if (_at < _qs.length - 1)
            Btn(t('Next'), small: true, wide: false, onTap: _done(_at) ? () => setState(() => _at++) : null)
          else
            Btn(t('Answer'), small: true, wide: false, busy: _busy, onTap: [for (var i = 0; i < _qs.length; i++) _done(i)].every((x) => x) ? _send : null),
        ],
      ),
    ];
  }

  // ---- designs ----

  List<Widget> _design() {
    final opts = asList(asMap(a.meta['design'])['options']);
    return [
      const SizedBox(height: 14),
      SizedBox(
        height: 300,
        child: ListView.separated(
          scrollDirection: Axis.horizontal,
          clipBehavior: Clip.none,
          itemCount: opts.length,
          separatorBuilder: (_, _) => const SizedBox(width: 12),
          itemBuilder: (c, i) => _DesignThumb(a, opts[i], onTap: () => _designs(i)),
        ),
      ),
      const SizedBox(height: 14),
      Row(
        children: [
          Expanded(
            child: Btn(t('Look closer'), small: true, icon: LucideIcons.maximize2, onTap: () => _designs(0)),
          ),
          const SizedBox(width: 8),
          Btn(t('Skip'), small: true, wide: false, kind: Kind.ghost, onTap: () => _reply('dismiss')),
        ],
      ),
    ];
  }

  Future<void> _designs(int i) => go(context, DesignScreen(a, i, reply: _reply), over: true);
}

class _DesignThumb extends StatelessWidget {
  const _DesignThumb(this.a, this.o, {required this.onTap});
  final Ask a;
  final J o;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final s = asList(o['screens']).firstOrNull ?? const {};
    final wide = '${s['device']}' == 'desktop' || ((s['width'] as num?) ?? 390) > 700;
    return Press(
      onTap: onTap,
      child: SizedBox(
        width: wide ? 250 : 150,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Container(
                width: double.infinity,
                clipBehavior: Clip.antiAlias,
                decoration: BoxDecoration(borderRadius: BorderRadius.circular(18)),
                foregroundDecoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(18),
                  border: Border.all(color: p.line),
                ),
                child: IgnorePointer(child: DesignView(a.hub.pc, s)),
              ),
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                Text(
                  '${o['letter']}',
                  style: T.label.copyWith(color: p.accent, fontWeight: FontWeight.w700),
                ),
                const SizedBox(width: 7),
                Expanded(
                  child: Text(
                    '${o['name']}',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: T.label.copyWith(color: p.text),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// One screen of a design, drawn at its own size and fitted to the space.
class DesignView extends StatefulWidget {
  const DesignView(this.pc, this.screen, {super.key});
  final Pc pc;
  final J screen;
  @override
  State<DesignView> createState() => _DesignViewState();
}

class _DesignViewState extends State<DesignView> {
  late final WebViewController _c = WebViewController()
    ..setJavaScriptMode(JavaScriptMode.unrestricted)
    ..setBackgroundColor(Colors.white);
  bool _ok = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(DesignView old) {
    super.didUpdateWidget(old);
    if (old.screen['path'] != widget.screen['path']) _load();
  }

  Future<void> _load() async {
    setState(() {
      _ok = false;
      _error = null;
    });
    try {
      var html = '${asMap(await widget.pc.get('/api/design/file?path=${Uri.encodeQueryComponent('${widget.screen['path']}')}'))['html'] ?? ''}';
      final w = (widget.screen['width'] as num?)?.toInt() ?? 390;
      html = html.replaceAll(RegExp(r'<meta[^>]+viewport[^>]*>', caseSensitive: false), '');
      final meta = '<meta name="viewport" content="width=$w">';
      html = html.contains(RegExp('<head[^>]*>', caseSensitive: false)) ? html.replaceFirstMapped(RegExp('<head[^>]*>', caseSensitive: false), (m) => '${m[0]}$meta') : '$meta$html';
      // Android ignores the viewport's width unless told to (an iPhone fits it by itself)
      if (_c.platform case final AndroidWebViewController a) await a.setUseWideViewPort(true);
      await _c.loadHtmlString(html);
      if (mounted) setState(() => _ok = true);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  @override
  Widget build(BuildContext context) => _error != null
      ? Center(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Text(
              _error!,
              textAlign: TextAlign.center,
              style: T.small.copyWith(color: const Color(0xFF666666)),
            ),
          ),
        )
      : Stack(
          fit: StackFit.expand,
          children: [
            WebViewWidget(controller: _c),
            if (!_ok) const Center(child: Pulse(size: 22)),
          ],
        );
}

class DesignScreen extends StatefulWidget {
  const DesignScreen(this.ask, this.at, {super.key, required this.reply});
  final Ask ask;
  final int at;
  final Future<void> Function(String decision, {String? message, List<J>? answers}) reply;
  @override
  State<DesignScreen> createState() => _DesignScreenState();
}

class _DesignScreenState extends State<DesignScreen> {
  late int _at = widget.at;
  int _screen = 0;
  late final _page = PageController(initialPage: widget.at);

  @override
  void dispose() {
    _page.dispose();
    super.dispose();
  }

  Future<void> _answer(String choice) async {
    final notes = await askText(
      context,
      choice.isEmpty ? t('What should change?') : t('Anything to change in {}?', choice),
      lines: 3,
      hint: choice.isEmpty ? '' : t('Optional'),
      action: choice.isEmpty ? t('Make new options') : t('Use {}', choice),
    );
    if (notes == null || !mounted) return;
    Navigator.pop(context);
    unawaited(
      widget.reply(
        'answer',
        answers: [
          {'choice': choice, 'notes': notes},
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final opts = asList(asMap(widget.ask.meta['design'])['options']);
    final o = opts[_at];
    final screens = asList(o['screens']);
    final s = screens.isEmpty ? const <String, dynamic>{} : screens[_screen.clamp(0, screens.length - 1)];
    return Scaffold(
      backgroundColor: p.bg,
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
              child: Row(
                children: [
                  const BackBtn(icon: LucideIcons.x),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Seg(
                      [for (final x in opts) '${x['letter']}'],
                      _at,
                      (i) => setState(() {
                        _at = i;
                        _screen = 0;
                      }),
                    ),
                  ),
                  const SizedBox(width: 12),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(gutter, 8, gutter, 10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text('${o['name']}', style: T.h1.copyWith(color: p.text)),
                  if ('${o['summary'] ?? ''}'.isNotEmpty)
                    Text(
                      '${o['summary']}',
                      maxLines: 3,
                      overflow: TextOverflow.ellipsis,
                      style: T.sub.copyWith(color: p.text2),
                    ),
                ],
              ),
            ),
            if (screens.length > 1)
              SizedBox(
                height: 36,
                child: ListView.separated(
                  scrollDirection: Axis.horizontal,
                  padding: const EdgeInsets.symmetric(horizontal: gutter),
                  itemCount: screens.length,
                  separatorBuilder: (_, _) => const SizedBox(width: 7),
                  itemBuilder: (c, i) => Pill('${screens[i]['name'] ?? i + 1}', on: i == _screen, onTap: () => setState(() => _screen = i)),
                ),
              ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(gutter, 12, gutter, 12),
                child: Container(
                  clipBehavior: Clip.antiAlias,
                  decoration: BoxDecoration(borderRadius: BorderRadius.circular(24)),
                  foregroundDecoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(24),
                    border: Border.all(color: p.line),
                  ),
                  child: DesignView(widget.ask.hub.pc, s, key: ValueKey('${s['path']}')),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(gutter, 0, gutter, 12),
              child: Row(
                children: [
                  Expanded(
                    child: Btn(t('New options'), kind: Kind.soft, onTap: () => _answer('')),
                  ),
                  const SizedBox(width: 10),
                  Expanded(child: Btn(t('Use {}', '${o['letter']}'), accent: true, onTap: () => _answer('${o['letter']}'))),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
