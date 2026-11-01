// One computer: its threads across every project, live. Tap a thread to take over, or start a new
// one with the button.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../remote.dart';
import '../theme.dart';
import '../widgets/common.dart';
import 'session.dart';

class ThreadsScreen extends StatefulWidget {
  const ThreadsScreen({super.key, required this.computer});
  final Computer computer;
  @override
  State<ThreadsScreen> createState() => _ThreadsScreenState();
}

class _ThreadsScreenState extends State<ThreadsScreen> {
  late final Pc _pc = Pc(widget.computer);
  final _search = TextEditingController();
  List<Map<String, dynamic>>? _sessions;
  List<String> _projects = [];
  ApiError? _error;
  String _filter = '';
  String _query = '';
  String _live = 'connecting';
  // approvals / questions seen on the live stream while this screen is open: session id → request ids
  final Map<String, Set<String>> _asking = {};
  StreamSubscription? _sub;
  Timer? _soon, _retry;

  @override
  void initState() {
    super.initState();
    _load();
    _sub = _pc.events(onState: (s) => mounted ? setState(() => _live = s) : null).listen(_onEvent);
  }

  @override
  void dispose() {
    _sub?.cancel();
    _soon?.cancel();
    _retry?.cancel();
    _search.dispose();
    super.dispose();
  }

  void _onEvent(Map<String, dynamic> ev) {
    final t = ev['type'] as String? ?? '';
    _track(t, ev['data']);
    if (t.startsWith('session.execution.') || t == 'session.created' || t == 'session.renamed' || t.startsWith('permission.')) {
      _soon?.cancel();
      _soon = Timer(const Duration(milliseconds: 400), _load);
    }
  }

  // Remembers which threads are waiting on an approval or an answer, for the "Needs you" label.
  void _track(String type, dynamic data) {
    if (data is! Map) return;
    final sid = data['sessionID'];
    final rid = data['id'];
    if (sid is! String || rid is! String) return;
    if (type == 'permission.asked') {
      _asking.putIfAbsent(sid, () => {}).add(rid);
    } else if (type == 'permission.replied') {
      _asking[sid]?.remove(rid);
      if (_asking[sid]?.isEmpty ?? false) _asking.remove(sid);
    }
  }

  bool _needsYou(Map s) {
    // (a session's own 'permissions' field is its rule set, not what's waiting)
    final pending = s['pending'];
    if (pending is List && pending.isNotEmpty) return true;
    if (pending is num && pending > 0) return true;
    return _asking[s['id']]?.isNotEmpty ?? false;
  }

  Future<void> _load() async {
    try {
      if (_projects.isEmpty) {
        final settings = await _pc.get('/api/settings');
        _projects = [
          for (final p in (settings['projects'] as List? ?? []))
            if (p is String && p.isNotEmpty) p,
        ];
      }
      List list;
      try {
        list = await _pc.get('/api/sessions?limit=120') as List;
      } on ApiError catch (e) {
        if (e.status != 422) rethrow;
        // AFH before 1.9.1 lists one project at a time
        final per = await Future.wait(
          _projects.take(12).map((d) => _pc.get('/api/sessions?directory=${Uri.encodeComponent(d)}').then((v) => v as List).catchError((_) => <dynamic>[])),
        );
        list = per.expand((x) => x).toList()..sort((a, b) => ((b['time']?['updated'] ?? 0) as num).compareTo((a['time']?['updated'] ?? 0) as num));
      }
      _sessions = [for (final s in list) Map<String, dynamic>.from(s as Map)];
      // a thread can only be waiting on you while it runs: ask those few what they're waiting for
      for (final s in _sessions!) {
        if (s['running'] != true) _asking.remove(s['id']);
      }
      final running = _sessions!.where((s) => s['running'] == true).take(8).toList();
      final waiting = await Future.wait(
        running.map((s) => _pc.get('/api/sessions/${s['id']}/permissions').then((v) => v is List && v.isNotEmpty).catchError((_) => false)),
      );
      for (final (i, s) in running.indexed) {
        if (waiting[i]) {
          _asking.putIfAbsent(s['id'] as String, () => {}).add('loaded');
        } else {
          _asking.remove(s['id']);
        }
      }
      _error = null;
    } on ApiError catch (e) {
      _error = e;
      _retry?.cancel();
      if (e.offline) _retry = Timer(const Duration(seconds: 8), () => mounted ? _load() : null);
    }
    if (mounted) setState(() {});
  }

  String _projectOf(Map s) => (s['project'] ?? s['location']?['directory'] ?? '') as String;

  void _open(Map<String, dynamic> s) {
    Navigator.of(context)
        .push(
          MaterialPageRoute(
            builder: (_) => SessionScreen(computer: widget.computer, session: s),
          ),
        )
        .then((_) => _load());
  }

  Future<void> _newThread() async {
    final projects = _projects.isNotEmpty ? _projects : {...?_sessions?.map(_projectOf).where((p) => p.isNotEmpty)}.toList();
    if (projects.isEmpty) {
      showToast(context, 'Open a project folder in AFH on your computer first.', error: true);
      return;
    }
    final got = await showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => _NewThreadSheet(pc: _pc, projects: projects, initial: _filter.isNotEmpty ? _filter : projects.first),
    );
    if (got != null && mounted) {
      _open(got);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.computer;
    final bottom = MediaQuery.paddingOf(context).bottom;
    return Scaffold(
      appBar: AppBar(
        title: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(c.name, maxLines: 1, overflow: TextOverflow.ellipsis),
            _LiveLabel(state: _error?.offline == true ? 'offline' : _live),
          ],
        ),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 6),
            child: IconBtn(LucideIcons.squarePen, tooltip: 'New thread', iconSize: 20, onTap: _sessions == null ? null : _newThread),
          ),
        ],
      ),
      bottomNavigationBar: _sessions == null
          ? null
          : Container(
              padding: EdgeInsets.fromLTRB(16, 10, 16, 10 + bottom),
              decoration: BoxDecoration(
                color: Afh.bg,
                border: Border(top: BorderSide(color: Afh.line)),
              ),
              child: PrimaryButton(label: 'New thread', icon: LucideIcons.plus, onTap: _newThread),
            ),
      body: RefreshIndicator(color: Afh.accent, backgroundColor: Afh.surface2, onRefresh: _load, child: _body()),
    );
  }

  Widget _body() {
    final c = widget.computer;
    if (_sessions == null && _error != null) {
      final off = _error!.offline;
      return ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        children: [
          const SizedBox(height: 60),
          EmptyState(
            icon: off ? LucideIcons.moon : LucideIcons.cloudOff,
            title: off ? '${c.name} is offline' : 'Couldn\'t load threads',
            text: off ? 'Open AFH on that computer and keep it signed in. This screen reconnects by itself.' : _error!.message,
            action: SecondaryButton(label: 'Try again', icon: LucideIcons.refreshCw, onTap: _load),
          ),
        ],
      );
    }
    if (_sessions == null) {
      return ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
        children: [
          Container(
            height: 40,
            margin: const EdgeInsets.only(bottom: 22),
            decoration: BoxDecoration(color: Afh.surface, borderRadius: BorderRadius.circular(12)),
          ),
          for (var i = 0; i < 6; i++)
            Container(
              height: 62,
              margin: const EdgeInsets.only(bottom: 8),
              decoration: BoxDecoration(color: Afh.surface, borderRadius: BorderRadius.circular(Afh.r), border: Border.all(color: Afh.line)),
            ).animate(onPlay: (c) => c.repeat()).shimmer(duration: 1300.ms, delay: (i * 80).ms, color: Afh.text.withValues(alpha: 0.04)),
        ],
      );
    }
    final used = {..._sessions!.map(_projectOf).where((p) => p.isNotEmpty)};
    final projects = {...used, ..._projects}.toList();
    final q = _query.toLowerCase();
    final shown = _sessions!
        .where((s) => (_filter.isEmpty || _projectOf(s) == _filter) && (q.isEmpty || '${s['title'] ?? ''}'.toLowerCase().contains(q)))
        .toList();
    final running = shown.where((s) => s['running'] == true).toList();
    final rest = shown.where((s) => s['running'] != true).take(80).toList();

    // the rest grouped by day, like the chat history
    final groups = <(String, List<Map<String, dynamic>>)>[];
    for (final s in rest) {
      final when = _when(s);
      final g = when == null ? 'Recent' : dayGroup(when);
      if (groups.isEmpty || groups.last.$1 != g) groups.add((g, []));
      groups.last.$2.add(s);
    }

    var section = 1;
    Widget group(String label, List<Map<String, dynamic>> items) => Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SectionLabel(label, padding: const EdgeInsets.fromLTRB(4, 18, 4, 8)),
          Group(
            inset: 16,
            children: [
              for (final s in items)
                _ThreadRow(
                  session: s,
                  project: _projectOf(s),
                  when: _when(s),
                  needsYou: _needsYou(s),
                  onTap: () => _open(s),
                ),
            ],
          ),
        ],
      ),
    ).enter(section++);

    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
      padding: const EdgeInsets.fromLTRB(0, 8, 0, 24),
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: SizedBox(
            height: 40,
            child: TextField(
              controller: _search,
              onChanged: (v) => setState(() => _query = v),
              textInputAction: TextInputAction.search,
              style: const TextStyle(fontSize: 15),
              decoration: InputDecoration(
                hintText: 'Search threads',
                isDense: true,
                fillColor: Afh.surface,
                prefixIcon: Icon(LucideIcons.search, size: 17, color: Afh.text3),
                prefixIconConstraints: const BoxConstraints(minWidth: 40),
                suffixIcon: _query.isEmpty
                    ? null
                    : IconBtn(
                        LucideIcons.x,
                        size: 36,
                        iconSize: 16,
                        color: Afh.text3,
                        onTap: () => setState(() {
                          _search.clear();
                          _query = '';
                        }),
                      ),
                contentPadding: const EdgeInsets.symmetric(vertical: 10),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
                enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
                focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: Afh.line2)),
              ),
            ),
          ),
        ).enter(0),
        if (projects.length > 1)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: SizedBox(
              height: 32,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 16),
                itemCount: projects.length + 1,
                separatorBuilder: (_, _) => const SizedBox(width: 8),
                itemBuilder: (_, i) {
                  final p = i == 0 ? '' : projects[i - 1];
                  return _Chip(
                    label: p.isEmpty ? 'All' : baseName(p),
                    selected: _filter == p,
                    onTap: () => setState(() => _filter = p),
                  );
                },
              ),
            ),
          ).enter(0),
        if (shown.isEmpty)
          EmptyState(
            icon: LucideIcons.messagesSquare,
            title: q.isEmpty ? 'No threads yet' : 'No matching threads',
            text: q.isEmpty ? 'Start one with New thread — AFH works on it on your computer.' : 'Try another word.',
          ),
        if (running.isNotEmpty) group('Working now', running),
        for (final (label, items) in groups) group(label, items),
      ],
    );
  }

  static DateTime? _when(Map s) {
    final updated = s['time']?['updated'];
    return updated is num ? DateTime.fromMillisecondsSinceEpoch(updated.toInt() < 1e12 ? updated.toInt() * 1000 : updated.toInt()) : null;
  }
}

class _LiveLabel extends StatelessWidget {
  const _LiveLabel({required this.state});
  final String state;
  @override
  Widget build(BuildContext context) {
    final (color, label) = switch (state) {
      'live' => (Afh.good, 'Live'),
      'offline' => (Afh.text3, 'Offline'),
      'reconnecting' => (Afh.warn, 'Reconnecting…'),
      _ => (Afh.warn, 'Connecting…'),
    };
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        PulseDot(color: color, live: state == 'live', size: 6),
        const SizedBox(width: 2),
        Text(
          label,
          style: TextStyle(fontSize: 12.5, color: Afh.text3, fontWeight: FontWeight.w400, fontFamily: Afh.body, height: 1.2),
        ),
      ],
    );
  }
}

/// A project filter chip: hairline outline, accent tint when picked.
class _Chip extends StatelessWidget {
  const _Chip({required this.label, required this.selected, required this.onTap, this.icon});
  final String label;
  final bool selected;
  final VoidCallback onTap;
  final IconData? icon;
  @override
  Widget build(BuildContext context) {
    final fg = selected ? Afh.accent : Afh.text2;
    return Pressable(
      onTap: onTap,
      child: AnimatedContainer(
        duration: Afh.fast,
        height: 32,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        decoration: BoxDecoration(
          color: selected ? Afh.tint : Colors.transparent,
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: selected ? Afh.accent : Afh.line),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (icon != null) ...[Icon(icon, size: 14, color: selected ? Afh.accent : Afh.text3), const SizedBox(width: 6)],
            ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 200),
              child: Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: 13, fontWeight: FontWeight.w500, color: fg),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ThreadRow extends StatelessWidget {
  const _ThreadRow({required this.session, required this.project, required this.when, required this.needsYou, required this.onTap});
  final Map<String, dynamic> session;
  final String project;
  final DateTime? when;
  final bool needsYou;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final running = session['running'] == true;
    final title = '${session['title'] ?? ''}'.isEmpty ? 'New thread' : '${session['title']}';
    final meta = [if (project.isNotEmpty) baseName(project), if (ago(when).isNotEmpty) ago(when)].join(' · ');
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: () {
          HapticFeedback.selectionClick();
          onTap();
        },
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 14, 12),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontWeight: FontWeight.w500, fontSize: 15, height: 1.3, color: Afh.text),
                    ),
                    if (meta.isNotEmpty) ...[
                      const SizedBox(height: 3),
                      Text(
                        meta,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontFamily: Afh.mono, fontSize: 12, color: Afh.text3, height: 1.3),
                      ),
                    ],
                  ],
                ),
              ),
              if (needsYou) ...[
                const SizedBox(width: 10),
                Pill('Needs you', color: Afh.warn),
              ] else if (running) ...[
                const SizedBox(width: 10),
                Pill('Working', color: Afh.good),
              ],
              const SizedBox(width: 6),
              Icon(LucideIcons.chevronRight, size: 18, color: Afh.text3),
            ],
          ),
        ),
      ),
    );
  }
}

class _NewThreadSheet extends StatefulWidget {
  const _NewThreadSheet({required this.pc, required this.projects, required this.initial});
  final Pc pc;
  final List<String> projects;
  final String initial;
  @override
  State<_NewThreadSheet> createState() => _NewThreadSheetState();
}

class _NewThreadSheetState extends State<_NewThreadSheet> {
  late String _dir = widget.initial;
  final _text = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  Future<void> _start() async {
    final prompt = _text.text.trim();
    if (prompt.isEmpty) return;
    setState(() => _busy = true);
    try {
      final s = Map<String, dynamic>.from(await widget.pc.post('/api/sessions', {'directory': _dir}) as Map);
      await widget.pc.post('/api/sessions/${s['id']}/prompt', {'text': prompt});
      HapticFeedback.mediumImpact();
      if (mounted) Navigator.pop(context, {...s, 'running': true});
    } on ApiError catch (e) {
      if (mounted) {
        showToast(context, e.message, error: true);
        setState(() => _busy = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: EdgeInsets.fromLTRB(16, 0, 16, 16 + MediaQuery.viewInsetsOf(context).bottom),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4),
            child: Text('New thread', style: Afh.h2()),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(4, 6, 4, 0),
            child: Text('AFH starts working on it on your computer right away.', style: Afh.small),
          ),
          const SectionLabel('Project', padding: EdgeInsets.fromLTRB(4, 20, 4, 8)),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final p in widget.projects)
                _Chip(
                  label: baseName(p),
                  icon: LucideIcons.folder,
                  selected: _dir == p,
                  onTap: () => setState(() => _dir = p),
                ),
            ],
          ),
          const SizedBox(height: 18),
          TextField(
            controller: _text,
            autofocus: true,
            minLines: 3,
            maxLines: 8,
            style: const TextStyle(fontSize: 15, height: 1.4),
            textCapitalization: TextCapitalization.sentences,
            decoration: const InputDecoration(hintText: 'What should AFH do?'),
            onChanged: (_) => setState(() {}),
          ),
          const SizedBox(height: 14),
          PrimaryButton(label: 'Start', icon: LucideIcons.arrowUp, busy: _busy, onTap: _text.text.trim().isEmpty ? null : _start),
        ],
      ),
    );
  }
}
