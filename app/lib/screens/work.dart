// The work behind a thread: its plan, goal, subagents, background jobs, worktree and what it has used.
import 'package:flutter/material.dart';

import '../core/hub.dart';
import '../core/l10n.dart';
import '../core/relay.dart';
import '../ui/kit.dart';
import '../ui/look.dart';
import '../ui/md.dart';
import '../ui/motion.dart';
import 'thread.dart' show openThread;

class WorkPage extends StatefulWidget {
  const WorkPage(this.s, {super.key, required this.top, required this.onGoal});
  final ThreadStore s;
  final double top;
  final VoidCallback onGoal;
  @override
  State<WorkPage> createState() => _WorkPageState();
}

class _WorkPageState extends State<WorkPage> {
  ThreadStore get s => widget.s;
  J? _tree;

  @override
  void initState() {
    super.initState();
    if (asMap(asMap(s.session['metadata'])['afh'])['worktree'] is Map) _worktree();
  }

  Future<void> _worktree() async {
    try {
      final w = asMap(await s.pc.get('/api/sessions/${s.sid}/worktree'));
      if (mounted) setState(() => _tree = w);
    } catch (_) {}
  }

  Future<void> _try(Future<void> Function() f, [String? done]) async {
    try {
      await f();
      if (done != null && mounted) toast(context, done);
    } catch (e) {
      if (mounted) toast(context, '$e', bad: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final done = s.todos.where((x) => x['status'] == 'completed').length;
    final g = s.goal;
    final blocks = <Widget>[
      if (g != null && '${g['text'] ?? ''}'.isNotEmpty) _goal(g),
      if (s.todos.isNotEmpty) ...[
        Head(
          t('Plan'),
          top: g == null ? 6 : 24,
          trailing: Row(
            mainAxisSize: MainAxisSize.min,
            children: [Ring(done / s.todos.length, size: 15), const SizedBox(width: 7), Text('$done / ${s.todos.length}', style: T.label.copyWith(color: p.text2))],
          ),
        ),
        Panel(
          pad: const EdgeInsets.symmetric(horizontal: 16, vertical: 7),
          child: Column(children: [for (final x in s.todos) _Todo(x)]),
        ),
      ],
      if (s.children.isNotEmpty)
        Group(
          title: t('Subagents'),
          children: [
            for (final c in s.children)
              Tile(
                '${c['title'] ?? c['agent'] ?? t('Subagent')}',
                sub: s.hub.modelName(c['model']),
                lead: Square(LucideIcons.bot, child: c['running'] == true ? const Pulse(size: 15) : null),
                arrow: true,
                onTap: () => openThread(context, s.hub, '${c['id']}'),
              ),
          ],
        ),
      if (s.jobs.isNotEmpty)
        Group(
          title: t('In the background'),
          children: [
            for (final j in s.jobs)
              Tile(
                '${j['description'] ?? ''}'.isEmpty ? '${j['command']}' : '${j['description']}',
                sub: j['running'] == true ? t('Working') : (j['stopped'] == true ? t('Stopped') : t('Ended with {}', '${j['exitCode']}')),
                lead: Square(LucideIcons.terminal, child: j['running'] == true ? const Pulse(size: 15) : null),
                arrow: true,
                onTap: () => _job(j),
              ),
          ],
        ),
      if (_tree != null) _treeCard(_tree!),
      if (s.usage != null) ..._usage(s.usage!),
    ];
    return RefreshIndicator(
      onRefresh: s.load,
      color: p.accent,
      backgroundColor: p.raised,
      edgeOffset: widget.top,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(parent: BouncingScrollPhysics()),
        padding: EdgeInsets.fromLTRB(gutter, widget.top, gutter, 30),
        children: [
          if (s.todos.isEmpty && g == null)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Panel(
                onTap: widget.onGoal,
                child: Row(
                  children: [
                    Square(LucideIcons.target, color: p.accent),
                    const SizedBox(width: 13),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(t('Set a goal'), style: T.row.copyWith(color: p.text)),
                          Text(t('It keeps working until the goal is done.'), style: T.small.copyWith(color: p.text3)),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          for (final (i, b) in blocks.indexed) Rise(i, child: b),
        ],
      ),
    );
  }

  Widget _goal(J g) {
    final p = context.p;
    final status = '${g['status'] ?? 'active'}';
    final turns = (g['turns'] as num?)?.toInt() ?? 0, max = (g['maxTurns'] as num?)?.toInt() ?? 0;
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Panel(
        border: status == 'active' ? p.accent.withValues(alpha: .35) : null,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(status == 'achieved' ? LucideIcons.circleCheck : LucideIcons.target, size: 18, color: status == 'achieved' ? p.good : p.accent),
                const SizedBox(width: 9),
                Expanded(
                  child: Text(
                    switch (status) {
                      'achieved' => t('Goal done'),
                      'blocked' => t('Goal is blocked'),
                      'paused' => t('Goal is paused'),
                      _ => t('Goal'),
                    },
                    style: T.label.copyWith(color: p.text2),
                  ),
                ),
                if (max > 0) Text(t('{} of {} turns', turns, max), style: T.tiny.copyWith(color: p.text3)),
              ],
            ),
            const SizedBox(height: 9),
            Text('${g['text']}', style: T.body.copyWith(color: p.text, height: 1.4)),
            const SizedBox(height: 13),
            Row(
              children: [
                Expanded(
                  child: status == 'active'
                      ? Btn(t('Pause'), small: true, kind: Kind.soft, onTap: () => _try(() async => s.goal = asMap(await s.pc.patch('/api/sessions/${s.sid}/goal', {'status': 'paused'}))).then((_) => setState(() {})))
                      : Btn(t('Change'), small: true, kind: Kind.soft, onTap: widget.onGoal),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Btn(
                    t('Remove'),
                    small: true,
                    kind: Kind.soft,
                    onTap: () => _try(() async {
                      await s.pc.delete('/api/sessions/${s.sid}/goal');
                      s.goal = null;
                      if (mounted) setState(() {});
                    }),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _treeCard(J w) {
    final p = context.p;
    final dirty = (w['dirty'] as List? ?? const []).length, ahead = (w['ahead'] as num?)?.toInt() ?? 0;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Head(t('Its own copy of the project')),
        Panel(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(LucideIcons.gitBranch, size: 17, color: p.text2),
                  const SizedBox(width: 9),
                  Expanded(child: Text('${w['branch']}', style: T.code.copyWith(color: p.text))),
                ],
              ),
              const SizedBox(height: 7),
              Text(w['merged'] == true ? t('Merged') : t('{} files changed, {} commits ahead', dirty, ahead), style: T.small.copyWith(color: p.text3)),
              const SizedBox(height: 13),
              Row(
                children: [
                  Expanded(
                    child: Btn(
                      t('Merge into {}', '${w['base'] ?? 'main'}'),
                      small: true,
                      onTap: s.running || (dirty == 0 && ahead == 0) || w['merged'] == true
                          ? null
                          : () => _try(() async {
                              await s.pc.post('/api/sessions/${s.sid}/worktree/merge');
                              await _worktree();
                            }, t('Merged')),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Btn(
                    t('Remove'),
                    small: true,
                    wide: false,
                    kind: Kind.danger,
                    onTap: () async {
                      if (!await confirm(context, t('Remove this copy?'), t('The branch and anything not merged are deleted.'), t('Remove'), danger: true)) return;
                      await _try(() async {
                        await s.pc.post('/api/sessions/${s.sid}/worktree/remove', {'force': true});
                        if (mounted) setState(() => _tree = null);
                      }, t('Removed'));
                    },
                  ),
                ],
              ),
            ],
          ),
        ),
      ],
    );
  }

  List<Widget> _usage(J u) {
    final p = context.p;
    final limit = (u['contextLimit'] as num?)?.toDouble() ?? 0, used = (u['lastInput'] as num?)?.toDouble() ?? 0;
    final tot = asMap(u['totals']);
    num n(String k) => tot[k] is num ? tot[k] as num : 0;
    final cache = tot['cache'] is Map ? ((asMap(tot['cache'])['read'] as num?) ?? 0) : n('cache');
    final cost = (u['cost'] as num?)?.toDouble();
    Widget stat(String l, String v) => Expanded(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(v, style: T.h2.copyWith(color: p.text, fontFeatures: const [FontFeature.tabularFigures()])),
          const SizedBox(height: 2),
          Text(l, style: T.tiny.copyWith(color: p.text3)),
        ],
      ),
    );
    return [
      Head(t('Used')),
      Panel(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (limit > 0) ...[
              Row(
                children: [
                  Text(t('Context'), style: T.label.copyWith(color: p.text2)),
                  const Spacer(),
                  Text('${count(used)} / ${count(limit)}', style: T.label.copyWith(color: p.text)),
                ],
              ),
              const SizedBox(height: 9),
              Bar(used / limit, color: used / limit > .8 ? p.warn : p.accent),
              const SizedBox(height: 18),
            ],
            Row(children: [stat(t('In'), count(n('input'))), stat(t('Out'), count(n('output'))), stat(t('From cache'), count(cache))]),
            if (cost != null && cost > 0) ...[
              const SizedBox(height: 14),
              Text(u['plan'] == true ? t('Worth {} at API prices; your plan covers it', money(cost)) : t('Cost so far: {}', money(cost)), style: T.small.copyWith(color: p.text2)),
            ],
          ],
        ),
      ),
    ];
  }

  Future<void> _job(J j) => sheet(
    context,
    full: true,
    title: '${j['description'] ?? ''}'.isEmpty ? t('Job') : '${j['description']}',
    (c) => _JobView(s, j, onStop: () => _try(() => s.pc.post('/api/jobs/${j['id']}/stop'), t('Stopped'))),
  );
}

class Bar extends StatelessWidget {
  const Bar(this.v, {super.key, this.color, this.h = 6});
  final double v, h;
  final Color? color;
  @override
  Widget build(BuildContext context) {
    final p = context.p;
    return ClipRRect(
      borderRadius: BorderRadius.circular(h),
      child: SizedBox(
        height: h,
        child: Stack(
          children: [
            Container(color: p.fill2),
            TweenAnimationBuilder<double>(
              tween: Tween(begin: 0, end: v.clamp(0, 1)),
              duration: const Duration(milliseconds: 700),
              curve: Curves.easeOutQuint,
              builder: (_, x, _) => FractionallySizedBox(
                widthFactor: x,
                alignment: AlignmentDirectional.centerStart,
                child: Container(
                  decoration: BoxDecoration(color: color ?? p.accent, borderRadius: BorderRadius.circular(h)),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Todo extends StatelessWidget {
  const _Todo(this.x);
  final J x;
  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final st = '${x['status']}';
    final done = st == 'completed' || st == 'cancelled';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 20,
            height: 22,
            child: Center(
              child: Swap(
                child: st == 'in_progress'
                    ? const Pulse(key: ValueKey('p'), size: 14)
                    : Icon(
                        st == 'completed' ? LucideIcons.circleCheck : (st == 'cancelled' ? LucideIcons.circleSlash : LucideIcons.circle),
                        key: ValueKey(st),
                        size: 17,
                        color: st == 'completed' ? p.good : p.text3,
                      ),
              ),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: AnimatedDefaultTextStyle(
              duration: med,
              style: T.sub.copyWith(
                color: done ? p.text3 : p.text,
                fontSize: 15,
                fontWeight: st == 'in_progress' ? FontWeight.w500 : FontWeight.w400,
                decoration: st == 'cancelled' ? TextDecoration.lineThrough : null,
              ),
              child: Text('${x['content']}'),
            ),
          ),
        ],
      ),
    );
  }
}

class _JobView extends StatefulWidget {
  const _JobView(this.s, this.j, {required this.onStop});
  final ThreadStore s;
  final J j;
  final Future<void> Function() onStop;
  @override
  State<_JobView> createState() => _JobViewState();
}

class _JobViewState extends State<_JobView> {
  late J j = widget.j;
  bool _gone = false;

  @override
  void initState() {
    super.initState();
    _poll();
  }

  Future<void> _poll() async {
    while (!_gone) {
      try {
        final n = asMap(await widget.s.pc.get('/api/jobs/${j['id']}?tail=12000'));
        if (_gone || !mounted) return;
        setState(() => j = n);
        if (n['running'] != true) return;
      } catch (_) {}
      await Future<void>.delayed(const Duration(seconds: 2));
    }
  }

  @override
  void dispose() {
    _gone = true;
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Padding(
    padding: EdgeInsets.fromLTRB(gutter, 0, gutter, 14 + MediaQuery.paddingOf(context).bottom),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        CodeBox('${j['command']}', lang: 'bash', head: false),
        const SizedBox(height: 10),
        Expanded(
          child: SingleChildScrollView(
            reverse: true,
            child: SizedBox(
              width: double.infinity,
              child: SelectableText('${j['tail'] ?? ''}', textDirection: TextDirection.ltr, style: T.code.copyWith(color: context.p.text2, fontSize: 12)),
            ),
          ),
        ),
        if (j['running'] == true) ...[
          const SizedBox(height: 12),
          const StrandLine(),
          const SizedBox(height: 12),
          Btn(
            t('Stop it'),
            kind: Kind.danger,
            onTap: () async {
              await widget.onStop();
              _poll();
            },
          ),
        ],
      ],
    ),
  );
}
