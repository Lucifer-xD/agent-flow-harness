// A thread on a computer: the conversation, the work behind it, and what it changed.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:share_plus/share_plus.dart';

import '../core/hub.dart';
import '../core/l10n.dart';
import '../core/native.dart';
import '../core/relay.dart';
import '../core/store.dart';
import '../ui/badge.dart';
import '../ui/composer.dart';
import '../ui/convo.dart';
import '../ui/diff.dart';
import '../ui/kit.dart';
import '../ui/look.dart';
import '../ui/media.dart';
import '../ui/motion.dart';
import 'asks.dart';
import 'chat.dart' show ConvoBar;
import 'files.dart';
import 'pick.dart';
import 'turn.dart';
import 'work.dart';

void openThread(BuildContext context, Hub h, String sid) => go(context, ThreadScreen(h, sid));

Att2 toAtt2(Att a) => Att2(a.label, a.mime, () => a.file.readAsBytes(), local: a.name);

class ThreadScreen extends StatefulWidget {
  const ThreadScreen(this.hub, this.sid, {super.key, this.page = 0});
  final Hub hub;
  final String sid;
  final int page;
  @override
  State<ThreadScreen> createState() => _ThreadScreenState();
}

class _ThreadScreenState extends State<ThreadScreen> {
  Hub get h => widget.hub;
  late final ThreadStore s = h.thread(widget.sid);
  final _scroll = ScrollController();
  final _text = TextEditingController();
  late final _pages = PageController(initialPage: widget.page);
  late int _at = widget.page;
  List<J>? _commands;
  String? _revert; // a rewind waiting for "Keep"
  String? _prev;
  bool _askOpen = true;

  String get _key => '${h.computer.id}/${widget.sid}';

  @override
  void initState() {
    super.initState();
    _prev = Notify.openThread;
    Notify.openThread = _key;
    s.addListener(_redraw);
    h.addListener(_redraw);
    s.load();
    Settings.i.put('seen.${widget.sid}', '${DateTime.now().millisecondsSinceEpoch}', quiet: true);
  }

  void _redraw() => mounted ? setState(() {}) : null;

  @override
  void dispose() {
    Notify.openThread = _prev;
    final sid = widget.sid;
    Future(() => Settings.i.put('seen.$sid', '${DateTime.now().millisecondsSinceEpoch}'));
    s.removeListener(_redraw);
    h.removeListener(_redraw);
    _scroll.dispose();
    _text.dispose();
    _pages.dispose();
    super.dispose();
  }

  Future<void> _try(Future<void> Function() f, [String? done]) async {
    try {
      await f();
      if (done != null && mounted) toast(context, done);
    } catch (e) {
      if (mounted) toast(context, '$e', bad: true);
    }
  }

  // ---- sending ----

  Future<bool> _send(String text, List<Att> files) async {
    try {
      if (text.startsWith('!') && text.length > 1 && files.isEmpty) {
        await h.pc.post('/api/sessions/${s.sid}/shell', {'command': text.substring(1).trim()});
        await s.load();
        return true;
      }
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scroll.hasClients) _scroll.animateTo(0, duration: slow, curve: Curves.easeOutQuint);
      });
      await s.send(text, files: [for (final f in files) toAtt2(f)]);
      unawaited(Notify.allowed());
      return true;
    } catch (e) {
      if (mounted) toast(context, '$e', bad: true);
      return false;
    }
  }

  Future<List<Hint>> _suggest(String sign, String word) async {
    final w = word.toLowerCase();
    if (sign == '/') {
      _commands ??= await h.pc.get('/api/commands?directory=${Uri.encodeQueryComponent(s.dir)}').then((v) => asList(v), onError: (_) => <J>[]);
      return [
        for (final c in _commands!)
          if ('${c['name']}'.toLowerCase().startsWith(w)) Hint('/${c['name']}', '/${c['name']}', sub: '${c['description'] ?? ''}'),
      ].take(12).toList();
    }
    try {
      final got = asMap(await h.pc.get('/api/files/search?directory=${Uri.encodeQueryComponent(s.dir)}&q=${Uri.encodeQueryComponent(word)}&limit=20'));
      return [
        for (final f in (got['files'] as List? ?? const [])) Hint('@$f', baseName('$f'), sub: '$f', icon: fileIcon('$f')),
      ];
    } catch (_) {
      return const [];
    }
  }

  // ---- what you can do with it ----

  Future<void> _rename() async {
    final n = await askText(context, t('Rename'), value: s.title);
    if (n != null && n.isNotEmpty) await _try(() => h.change(s.sid, {'title': n}));
    s.session['title'] = n?.isNotEmpty == true ? n : s.session['title'];
    _redraw();
  }

  Future<void> _model() async {
    final m = asMap(s.session['model']);
    final got = await pickModel(context, hubModels(h), current: '${m['providerID']}/${m['id']}', effort: m['variant'] as String?);
    if (got == null) return;
    setState(() => s.session['model'] = got.ref);
    await _try(() => h.change(s.sid, {'model': got.ref}));
  }

  Future<void> _mode() async {
    final got = await pickMode(context, modeOf(s.session));
    if (got == null) return;
    final meta = asMap(s.session['metadata']);
    setState(() => s.session['metadata'] = {...meta, 'afh': {...asMap(meta['afh']), 'mode': got}});
    await _try(() => h.change(s.sid, {'mode': got}));
  }

  Future<void> _agent() async {
    final got = await pickAgent(context, h, s.session['agent'] as String?);
    if (got == null) return;
    setState(() => s.session['agent'] = got);
    await _try(() => h.change(s.sid, {'agent': got}));
  }

  Future<void> _fork([String? before]) => _try(() async {
    final n = asMap(await h.pc.post('/api/sessions/${s.sid}/fork', {'before': ?before}));
    await h.load();
    if (mounted) unawaited(Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => ThreadScreen(h, '${n['id']}'))));
  });

  Future<void> _rewind(TMsg m, {bool files = true, bool chat = true}) => _try(() async {
    if (s.running) {
      await h.stop(s.sid);
      await Future<void>.delayed(const Duration(milliseconds: 700));
    }
    await h.pc.post('/api/sessions/${s.sid}/revert', {'messageId': m.id, 'files': files, 'messages': chat});
    await s.load();
    setState(() {
      _revert = chat && files ? t('Rewound the chat and the files') : (chat ? t('Rewound the chat') : t('Put the files back'));
      if (chat && _text.text.isEmpty) _text.text = '${m.d['text'] ?? ''}';
    });
  });

  Future<void> _menuMine(TMsg m) => actions(context, [
    Act(t('Copy'), LucideIcons.copy, () => copyText(context, '${m.d['text'] ?? ''}')),
    Act(t('Select text'), LucideIcons.textSelect, () => selectSheet(context, '${m.d['text'] ?? ''}')),
    Act(t('Fork from here'), LucideIcons.gitBranch, () => _fork(m.id), sub: t('A new thread with everything before this message')),
    null,
    Act(t('Rewind chat and files'), LucideIcons.undo2, () => _rewind(m), sub: t('Back to just before this message')),
    Act(t('Rewind the chat only'), LucideIcons.messageSquareOff, () => _rewind(m, files: false), sub: t('Your files stay as they are')),
    Act(t('Undo file changes only'), LucideIcons.fileX, () => _rewind(m, chat: false), sub: t('The chat stays as it is')),
  ]);

  Future<void> _goal() async {
    final text = await askText(context, t('Goal for this thread'), value: '${s.goal?['text'] ?? ''}', lines: 3, hint: t('It keeps working until this is done.'), action: t('Start'));
    if (text == null || text.isEmpty) return;
    await _try(() async {
      s.goal = asMap(await h.pc.put('/api/sessions/${s.sid}/goal', {'text': text, 'autopilot': true, 'start': true}));
    }, t('It is working toward the goal'));
  }

  Future<void> _menu() => actions(context, title: s.title, [
    Act(t('Rename'), LucideIcons.pencil, _rename),
    Act(t('Model'), LucideIcons.cpu, _model, sub: h.modelName(s.session['model'])),
    Act(t('What it may do'), LucideIcons.shield, _mode, sub: t(modeOf_(modeOf(s.session)).$2)),
    Act(t('Agent'), LucideIcons.bot, _agent, sub: s.session['agent'] == null ? null : '${s.session['agent']}'.replaceFirstMapped(RegExp('^.'), (m) => m[0]!.toUpperCase())),
    Act(t('Set a goal'), LucideIcons.target, _goal),
    Act(t('Files in the project'), LucideIcons.folderOpen, () => go(context, FilesScreen(h, s.dir))),
    null,
    Act(t('Fork'), LucideIcons.gitBranch, () => _fork()),
    Act(t('Share the conversation'), LucideIcons.share2, () => SharePlus.instance.share(ShareParams(text: transcript(s), subject: s.title))),
    Act(t('Compact the context'), LucideIcons.foldVertical, () => _try(() => h.pc.post('/api/sessions/${s.sid}/compact'), t('Compacted')), sub: t('Sums up the older part so there is room again')),
    Act(t('Archive'), LucideIcons.archive, () => _try(() async {
      await h.change(s.sid, {'archived': true});
      if (mounted) Navigator.pop(context);
    })),
    Act(t('Delete'), LucideIcons.trash2, () async {
      if (!await confirm(context, t('Delete this thread?'), t('It is removed from {} for good. The files it changed stay as they are.', h.computer.name), t('Delete'), danger: true)) return;
      await _try(() async {
        await h.remove(s.sid);
        if (mounted) Navigator.pop(context);
      });
    }, danger: true),
  ]);

  // ---- drawing ----

  /// The messages, a reply's many steps gathered under what was asked.
  List<(TMsg?, List<TMsg>)> _items() {
    final out = <(TMsg?, List<TMsg>)>[];
    for (final m in s.msgs) {
      if (m.type == 'assistant') {
        if (out.isEmpty || out.last.$1 != null) out.add((null, []));
        out.last.$2.add(m);
      } else if (m.type != 'system') {
        out.add((m, const []));
      }
    }
    return out;
  }

  Widget _statusLine() {
    final p = context.p;
    final (c, text) = switch (h.state) {
      'offline' => (p.text3, t('{} is offline', h.computer.name)),
      'reconnecting' || 'connecting' => (p.warn, t('Connecting to {}', h.computer.name)),
      _ => (s.running ? p.accent : p.good, '${h.computer.name} · ${baseName(s.dir)}'),
    };
    return Row(
      children: [
        Dot(c, size: 6),
        const SizedBox(width: 6),
        Flexible(
          child: Text(text, maxLines: 1, overflow: TextOverflow.ellipsis, style: T.tiny.copyWith(color: p.text3)),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final mq = MediaQuery.paddingOf(context);
    final kb = MediaQuery.viewInsetsOf(context).bottom;
    final items = _items();
    final asks = s.asks.toList();
    final changed = s.diff?.length ?? 0;
    final open = s.todos.where((x) => x['status'] != 'completed' && x['status'] != 'cancelled').length;
    final m = asMap(s.session['model']);
    final mode = modeOf_(modeOf(s.session));
    final limit = (s.usage?['contextLimit'] as num?)?.toDouble() ?? 0;
    final used = (s.usage?['lastInput'] as num?)?.toDouble() ?? 0;
    return Scaffold(
      backgroundColor: p.bg,
      body: Column(
        children: [
          Expanded(
            child: Stack(
              children: [
                PageView(
                  controller: _pages,
                  onPageChanged: (i) => setState(() => _at = i),
                  children: [
                    !s.loaded && s.msgs.isEmpty
                        ? (s.error != null
                              ? Center(child: Empty(LucideIcons.cloudOff, t('Couldn\'t open it'), s.error!, action: t('Try again'), onTap: s.load))
                              : const _Bones())
                        : ConvoScroll(
                            controller: _scroll,
                            top: mq.top + 108,
                            bottom: 14,
                            count: items.length + s.sending.length,
                            live: s.running,
                            empty: Empty(LucideIcons.messageSquare, t('Nothing here yet'), t('Say what you want done in {}.', baseName(s.dir))),
                            builder: (i) {
                              if (i >= items.length) {
                                final (text, files) = s.sending[i - items.length];
                                return Mine(text, shots: [for (final f in files) Shot.local(Att(name: f.local ?? '', label: f.name, mime: f.mime))], waiting: true, note: files.isEmpty ? t('Sending…') : t('Sending {} files…', files.length));
                              }
                              final (mine, turn) = items[i];
                              if (mine == null) {
                                return Turn(s, turn, key: ValueKey(turn.first.id), last: i == items.length - 1, onFork: () => _fork(), onChanges: () => _go(2));
                              }
                              return ListenableBuilder(listenable: mine, builder: (c, _) => OtherMsg(s, mine, onLong: () => _menuMine(mine)));
                            },
                            tail: Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                if (s.running && (items.isEmpty || items.last.$1 != null))
                                  Padding(
                                    padding: const EdgeInsets.fromLTRB(gutter, 12, gutter, 0),
                                    child: QuietLine(t('Starting'), live: true),
                                  ),
                                if (s.runError != null && !s.running)
                                  Padding(
                                    padding: const EdgeInsets.fromLTRB(gutter, 14, gutter, 0),
                                    child: Note(s.runError!, icon: LucideIcons.circleAlert, color: p.bad, action: t('Try again'), onTap: () => _send(t('Continue.'), [])),
                                  ),
                              ],
                            ),
                          ),
                    WorkPage(s, top: mq.top + 108, onGoal: _goal),
                    ChangesPage(s, top: mq.top + 108),
                  ],
                ),
                Positioned(
                  left: 0,
                  right: 0,
                  top: 0,
                  child: ConvoBar(
                    title: s.title,
                    subWidget: _statusLine(),
                    onTitle: _menu,
                    actions: [
                      Ic(LucideIcons.folderOpen, color: p.text2, tip: t('Files in the project'), onTap: () => go(context, FilesScreen(h, s.dir))),
                      Ic(LucideIcons.ellipsis, color: p.text2, tip: t('More'), onTap: _menu),
                    ],
                    under: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: gutter),
                      child: Seg([t('Conversation'), t('Work'), t('Changes')], _at, _go, height: 38, badges: [0, open, changed]),
                    ),
                  ),
                ),
                if (_at == 0) PositionedDirectional(end: gutter, bottom: 10, child: ToEnd(_scroll, live: s.running)),
              ],
            ),
          ),
          Padding(
            padding: EdgeInsets.fromLTRB(12, 0, 12, kb > 0 ? 8 : 10 + mq.bottom),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                AnimatedSize(
                  duration: const Duration(milliseconds: 380),
                  curve: Curves.easeOutQuint,
                  alignment: Alignment.bottomCenter,
                  child: asks.isEmpty
                      ? const SizedBox(width: double.infinity)
                      : Padding(
                          padding: const EdgeInsets.only(bottom: 10),
                          child: _askOpen
                              ? Stack(
                                  children: [
                                    ConstrainedBox(
                                      constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(context).height * (kb > 0 ? .42 : .64)),
                                      child: SingleChildScrollView(child: AskCard(asks.first, key: ValueKey(asks.first.id))),
                                    ),
                                    PositionedDirectional(
                                      top: 8,
                                      end: 8,
                                      child: Ic(LucideIcons.chevronDown, size: 36, icon_: 17, color: p.text3, tip: t('Hide'), onTap: () => setState(() => _askOpen = false)),
                                    ),
                                  ],
                                )
                              : Panel(
                                  onTap: () => setState(() => _askOpen = true),
                                  border: p.accent.withValues(alpha: .4),
                                  pad: const EdgeInsets.fromLTRB(16, 12, 16, 12),
                                  child: Row(
                                    children: [
                                      Icon(askTitle(asks.first).$1, size: 18, color: p.accent),
                                      const SizedBox(width: 12),
                                      Expanded(child: Text(askTitle(asks.first).$2, maxLines: 1, overflow: TextOverflow.ellipsis, style: T.row.copyWith(color: p.text))),
                                      Icon(LucideIcons.chevronUp, size: 17, color: p.text3),
                                    ],
                                  ),
                                ),
                        ),
                ),
                if (_revert != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: Container(
                      padding: const EdgeInsets.fromLTRB(14, 7, 7, 7),
                      decoration: BoxDecoration(color: p.fill, borderRadius: BorderRadius.circular(18)),
                      child: Row(
                        children: [
                          Icon(LucideIcons.undo2, size: 16, color: p.text2),
                          const SizedBox(width: 10),
                          Expanded(child: Text(_revert!, style: T.sub.copyWith(color: p.text))),
                          Btn(t('Put it back'), kind: Kind.ghost, small: true, wide: false, onTap: () => _try(() async {
                            await h.pc.post('/api/sessions/${s.sid}/revert/clear');
                            setState(() => _revert = null);
                            await s.load();
                          })),
                          Btn(t('Keep'), small: true, wide: false, onTap: () => _try(() async {
                            await h.pc.post('/api/sessions/${s.sid}/revert/commit');
                            setState(() => _revert = null);
                            await s.load();
                          })),
                        ],
                      ),
                    ),
                  ),
                AnimatedSize(
                  duration: med,
                  curve: Curves.easeOutQuint,
                  alignment: Alignment.bottomCenter,
                  child: s.running && asks.isEmpty ? LiveStrip(s, onTap: () => _go(1)) : const SizedBox(width: double.infinity),
                ),
                Composer(
                  controller: _text,
                  hint: s.running ? t('Add a note while it works') : t('What should it do next?'),
                  draft: s.sid,
                  running: s.running,
                  onStop: () => _try(() => h.stop(s.sid)),
                  onSend: _send,
                  canSend: h.state != 'offline',
                  suggest: _suggest,
                  chips: [
                    CChip(t(mode.$2), icon: mode.$1, onTap: _mode, on: modeOf(s.session) == 'full'),
                    CChip(
                      '${h.modelName(m)}${m['variant'] == null || m['variant'] == 'default' ? '' : ' · ${effortName('${m['variant']}')}'}',
                      lead: Logo('${m['providerID'] ?? ''}', name: h.providerNames['${m['providerID']}'] ?? '', model: '${m['id'] ?? ''}', size: 15, family: true),
                      onTap: _model,
                    ),
                    if (limit > 0 && used > 0) CChip('${(used / limit * 100).round()}%', lead: Ring(used / limit, size: 14, stroke: 2.2, color: used / limit > .8 ? p.warn : p.text2), onTap: () => _go(1)),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  void _go(int i) => _pages.animateToPage(i, duration: const Duration(milliseconds: 420), curve: Curves.easeOutQuint);
}

/// What it's doing this second, over the composer.
class LiveStrip extends StatefulWidget {
  const LiveStrip(this.s, {super.key, required this.onTap});
  final ThreadStore s;
  final VoidCallback onTap;
  @override
  State<LiveStrip> createState() => _LiveStripState();
}

class _LiveStripState extends State<LiveStrip> {
  late final _t = Timer.periodic(const Duration(seconds: 1), (_) => mounted ? setState(() {}) : null);
  @override
  void initState() {
    super.initState();
    _t.isActive;
  }

  @override
  void dispose() {
    _t.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final s = widget.s;
    final done = s.todos.where((x) => x['status'] == 'completed').length;
    final label = t(s.hub.now[s.sid] ?? 'Working');
    return Press(
      onTap: widget.onTap,
      scale: .99,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(8, 4, 8, 10),
        child: Column(
          children: [
            Row(
              children: [
                const Pulse(size: 13),
                const SizedBox(width: 10),
                Expanded(
                  child: Swap(
                    align: AlignmentDirectional.centerStart.resolve(Directionality.of(context)),
                    child: Text(label, key: ValueKey(label), maxLines: 1, overflow: TextOverflow.ellipsis, style: T.label.copyWith(color: p.text)),
                  ),
                ),
                if (s.todos.isNotEmpty) ...[
                  Ring(done / s.todos.length, size: 15),
                  const SizedBox(width: 6),
                  Text('$done/${s.todos.length}', style: T.tiny.copyWith(color: p.text2)),
                  const SizedBox(width: 10),
                ],
                if (s.startedAt != null) Text(took(DateTime.now().difference(s.startedAt!).inMilliseconds.clamp(1000, 1 << 40)), style: T.tiny.copyWith(color: p.text3, fontFeatures: const [FontFeature.tabularFigures()])),
              ],
            ),
            const SizedBox(height: 8),
            const StrandLine(),
          ],
        ),
      ),
    );
  }
}

class _Bones extends StatelessWidget {
  const _Bones();
  @override
  Widget build(BuildContext context) => const SingleChildScrollView(
    physics: NeverScrollableScrollPhysics(),
    padding: EdgeInsets.fromLTRB(gutter, 190, gutter, 0),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Align(alignment: Alignment.centerRight, child: Bone(w: 200, h: 44, r: 22)),
        SizedBox(height: 26),
        Bone(w: 130),
        SizedBox(height: 14),
        Bone(),
        SizedBox(height: 9),
        Bone(),
        SizedBox(height: 9),
        Bone(w: 220),
      ],
    ),
  );
}

/// What changed in this thread.
class ChangesPage extends StatelessWidget {
  const ChangesPage(this.s, {super.key, required this.top});
  final ThreadStore s;
  final double top;

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final d = s.diff;
    final add = (d ?? []).fold<int>(0, (n, x) => n + ((x['additions'] as num?)?.toInt() ?? 0));
    final del = (d ?? []).fold<int>(0, (n, x) => n + ((x['deletions'] as num?)?.toInt() ?? 0));
    return RefreshIndicator(
      onRefresh: s.load,
      color: p.accent,
      backgroundColor: p.raised,
      edgeOffset: top,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(parent: BouncingScrollPhysics()),
        padding: EdgeInsets.fromLTRB(gutter, top, gutter, 30),
        children: [
          if (d == null)
            for (var i = 0; i < 3; i++) const Padding(padding: EdgeInsets.only(bottom: 10), child: Bone(h: 60, r: 18))
          else if (d.isEmpty)
            Empty(LucideIcons.fileDiff, t('No changes'), t('Files this thread edits show up here, line by line.'))
          else ...[
            Padding(
              padding: const EdgeInsets.fromLTRB(4, 4, 4, 14),
              child: Row(
                children: [
                  Text(d.length == 1 ? t('1 file changed') : t('{} files changed', d.length), style: T.label.copyWith(color: p.text2)),
                  const Spacer(),
                  Plus(add, del),
                ],
              ),
            ),
            for (final (i, f) in d.indexed)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: Rise(
                  i,
                  child: DiffFile(f, key: ValueKey(f['file']), root: s.dir, open: d.length == 1, onOpen: () => go(context, FileScreen(s.hub, '${f['file']}', root: s.dir))),
                ),
              ),
          ],
        ],
      ),
    );
  }
}

String transcript(ThreadStore s) {
  final out = StringBuffer('# ${s.title}\n');
  for (final m in s.msgs) {
    if (m.type == 'user') out.write('\n## You\n\n${m.d['text']}\n');
    if (m.type == 'assistant') {
      final text = [for (final x in m.parts) if (x['type'] == 'text') '${x['text']}'.trim()].where((x) => x.isNotEmpty).join('\n\n');
      if (text.isNotEmpty) out.write('\n## ${s.hub.modelName(m.d['model'])}\n\n$text\n');
    }
  }
  return out.toString();
}
