// One computer: its threads across every project, live. Tap a thread to take over, or start a new
// one with the button.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_animate/flutter_animate.dart';

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
  List<Map<String, dynamic>>? _sessions;
  List<String> _projects = [];
  ApiError? _error;
  String _filter = '';
  String _query = '';
  String _live = 'connecting';
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
    super.dispose();
  }

  void _onEvent(Map<String, dynamic> ev) {
    final t = ev['type'] as String? ?? '';
    if (t.startsWith('session.execution.') || t == 'session.created' || t == 'session.renamed' || t.startsWith('permission.')) {
      _soon?.cancel();
      _soon = Timer(const Duration(milliseconds: 400), _load);
    }
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
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 0,
        title: Row(
          children: [
            Hero(
              tag: 'pc-${c.id}',
              child: Container(
                width: 38,
                height: 38,
                decoration: BoxDecoration(
                  gradient: Afh.gradSoft,
                  borderRadius: BorderRadius.circular(13),
                  border: Border.all(color: Afh.orange.withValues(alpha: 0.3)),
                ),
                child: const Icon(Icons.laptop_chromebook_rounded, size: 20, color: Color(0xFFFFB48A)),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(c.name, maxLines: 1, overflow: TextOverflow.ellipsis),
                  const SizedBox(height: 2),
                  _LiveLabel(state: _error?.offline == true ? 'offline' : _live),
                ],
              ),
            ),
          ],
        ),
        actions: [IconButton(tooltip: 'New thread', onPressed: _sessions == null ? null : _newThread, icon: const Icon(Icons.add_comment_rounded))],
      ),
      floatingActionButton: _sessions == null
          ? null
          : Padding(
              padding: EdgeInsets.only(bottom: MediaQuery.paddingOf(context).bottom > 0 ? 0 : 8),
              child: Pressable(
                onTap: _newThread,
                child: Container(
                  height: 56,
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                  decoration: BoxDecoration(
                    gradient: Afh.grad,
                    borderRadius: BorderRadius.circular(28),
                    boxShadow: [BoxShadow(color: Afh.pink.withValues(alpha: 0.45), blurRadius: 24, offset: const Offset(0, 10), spreadRadius: -6)],
                  ),
                  child: const Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.add_rounded, color: Color(0xFF1A0D05)),
                      SizedBox(width: 6),
                      Text(
                        'New thread',
                        style: TextStyle(fontFamily: Afh.display, fontWeight: FontWeight.w700, fontSize: 16, color: Color(0xFF1A0D05)),
                      ),
                    ],
                  ),
                ),
              ).animate().scale(curve: Afh.spring, duration: 550.ms, begin: const Offset(0.5, 0.5)),
            ),
      body: RefreshIndicator(color: Afh.orange, backgroundColor: Afh.surface2, onRefresh: _load, child: _body()),
    );
  }

  Widget _body() {
    final c = widget.computer;
    if (_sessions == null && _error != null) {
      final off = _error!.offline;
      return ListView(
        children: [
          const SizedBox(height: 60),
          EmptyState(
            icon: off ? Icons.bedtime_rounded : Icons.cloud_off_rounded,
            title: off ? '${c.name} is offline' : 'Couldn\'t load threads',
            text: off ? 'Open AFH on that computer and keep it signed in. This screen reconnects by itself.' : _error!.message,
            action: GhostButton(label: 'Try again', icon: Icons.refresh_rounded, onTap: _load),
          ),
        ],
      );
    }
    if (_sessions == null) {
      return ListView(
        padding: const EdgeInsets.all(16),
        children: [
          for (var i = 0; i < 6; i++)
            Container(
              height: 72,
              margin: const EdgeInsets.only(bottom: 10),
              decoration: BoxDecoration(color: Afh.surface, borderRadius: BorderRadius.circular(20)),
            ).animate(onPlay: (c) => c.repeat()).shimmer(duration: 1300.ms, delay: (i * 80).ms, color: Colors.white.withValues(alpha: 0.05)),
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
    var i = 0;
    Widget row(Map<String, dynamic> s) => _ThreadTile(session: s, project: _projectOf(s), index: i++, onTap: () => _open(s));
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: EdgeInsets.fromLTRB(0, 4, 0, 110 + MediaQuery.paddingOf(context).bottom),
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
          child: TextField(
            onChanged: (v) => setState(() => _query = v),
            decoration: InputDecoration(
              hintText: 'Search threads',
              prefixIcon: const Icon(Icons.search_rounded, color: Afh.text3),
              contentPadding: const EdgeInsets.symmetric(vertical: 12),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(999),
                borderSide: const BorderSide(color: Afh.line),
              ),
              enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(999),
                borderSide: const BorderSide(color: Afh.line),
              ),
              focusedBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(999),
                borderSide: const BorderSide(color: Afh.orange),
              ),
            ),
          ),
        ),
        if (projects.length > 1)
          SizedBox(
            height: 42,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 14),
              children: [
                for (final p in ['', ...projects])
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 3),
                    child: Pressable(
                      onTap: () => setState(() => _filter = p),
                      child: AnimatedContainer(
                        duration: const Duration(milliseconds: 250),
                        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 9),
                        decoration: BoxDecoration(
                          gradient: _filter == p ? const LinearGradient(colors: [Color(0x40FFB11F), Color(0x40FF3D8A)]) : null,
                          color: _filter == p ? null : Afh.surface,
                          borderRadius: BorderRadius.circular(999),
                          border: Border.all(color: _filter == p ? Afh.orange.withValues(alpha: 0.5) : Afh.line),
                        ),
                        child: Text(
                          p.isEmpty ? 'All' : baseName(p),
                          style: TextStyle(fontWeight: FontWeight.w600, color: _filter == p ? Afh.text : Afh.text2),
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        if (shown.isEmpty)
          EmptyState(
            icon: Icons.forum_outlined,
            title: q.isEmpty ? 'No threads yet' : 'No matching threads',
            text: q.isEmpty ? 'Start one with New thread — AFH works on it on your computer.' : 'Try another word.',
          ),
        if (running.isNotEmpty) const _Section('Working now'),
        ...running.map(row),
        if (running.isNotEmpty && rest.isNotEmpty) const _Section('Recent'),
        ...rest.map(row),
      ],
    );
  }
}

class _Section extends StatelessWidget {
  const _Section(this.text);
  final String text;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(26, 18, 26, 8),
    child: Text(text.toUpperCase(), style: Afh.label),
  );
}

class _LiveLabel extends StatelessWidget {
  const _LiveLabel({required this.state});
  final String state;
  @override
  Widget build(BuildContext context) {
    final (color, label) = switch (state) {
      'live' => (Afh.good, 'Live'),
      'offline' => (Afh.text3, 'Offline'),
      'reconnecting' => (Afh.amber, 'Reconnecting…'),
      _ => (Afh.amber, 'Connecting…'),
    };
    return Row(
      children: [
        PulseDot(color: color, live: state == 'live', size: 7),
        const SizedBox(width: 6),
        Text(
          label,
          style: TextStyle(fontSize: 12.5, color: color, fontWeight: FontWeight.w600, fontFamily: Afh.body),
        ),
      ],
    );
  }
}

class _ThreadTile extends StatelessWidget {
  const _ThreadTile({required this.session, required this.project, required this.index, required this.onTap});
  final Map<String, dynamic> session;
  final String project;
  final int index;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final running = session['running'] == true;
    final updated = session['time']?['updated'];
    final when = updated is num ? DateTime.fromMillisecondsSinceEpoch(updated.toInt() < 1e12 ? updated.toInt() * 1000 : updated.toInt()) : null;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      child: Pressable(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: Afh.surface,
            borderRadius: BorderRadius.circular(20),
            border: Border.all(color: running ? Afh.orange.withValues(alpha: 0.4) : Afh.line),
          ),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${session['title'] ?? ''}'.isEmpty ? 'New thread' : '${session['title']}',
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15.5, height: 1.3),
                    ),
                    const SizedBox(height: 7),
                    Row(
                      children: [
                        if (project.isNotEmpty)
                          Flexible(
                            child: Container(
                              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                              decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.06), borderRadius: BorderRadius.circular(8)),
                              child: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  const Icon(Icons.folder_rounded, size: 13, color: Afh.text3),
                                  const SizedBox(width: 4),
                                  Flexible(
                                    child: Text(
                                      baseName(project),
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                      style: const TextStyle(fontSize: 12, color: Afh.text2),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ),
                        const SizedBox(width: 8),
                        if (running) ...[
                          const PulseDot(color: Afh.orange, size: 7),
                          const SizedBox(width: 6),
                          const Text(
                            'Working',
                            style: TextStyle(fontSize: 12.5, color: Afh.orange, fontWeight: FontWeight.w700),
                          ),
                        ] else
                          Text(ago(when), style: const TextStyle(fontSize: 12.5, color: Afh.text3)),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              const Icon(Icons.chevron_right_rounded, color: Afh.text3),
            ],
          ),
        ),
      ),
    ).animate().fadeIn(delay: (30 * index.clamp(0, 12)).ms, duration: 300.ms).moveY(begin: 10, end: 0, delay: (30 * index.clamp(0, 12)).ms, curve: Afh.ease);
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
    return Padding(
      padding: EdgeInsets.fromLTRB(22, 0, 22, 22 + MediaQuery.viewInsetsOf(context).bottom),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('New thread', style: Afh.h2()),
          const SizedBox(height: 4),
          const Text('AFH starts working on it on your computer right away.', style: TextStyle(color: Afh.text2)),
          const SizedBox(height: 18),
          const Text('PROJECT', style: Afh.label),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final p in widget.projects)
                Pressable(
                  onTap: () => setState(() => _dir = p),
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 220),
                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
                    decoration: BoxDecoration(
                      gradient: _dir == p ? const LinearGradient(colors: [Color(0x40FFB11F), Color(0x40FF3D8A)]) : null,
                      color: _dir == p ? null : Afh.surface2,
                      borderRadius: BorderRadius.circular(999),
                      border: Border.all(color: _dir == p ? Afh.orange.withValues(alpha: 0.5) : Afh.line),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.folder_rounded, size: 15, color: _dir == p ? Afh.orange : Afh.text3),
                        const SizedBox(width: 6),
                        Text(
                          baseName(p),
                          style: TextStyle(fontWeight: FontWeight.w600, color: _dir == p ? Afh.text : Afh.text2),
                        ),
                      ],
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 18),
          TextField(
            controller: _text,
            autofocus: true,
            minLines: 3,
            maxLines: 8,
            textCapitalization: TextCapitalization.sentences,
            decoration: const InputDecoration(hintText: 'What should AFH do?'),
            onChanged: (_) => setState(() {}),
          ),
          const SizedBox(height: 18),
          GradButton(label: 'Start', icon: Icons.arrow_upward_rounded, busy: _busy, onTap: _text.text.trim().isEmpty ? null : _start),
        ],
      ),
    );
  }
}
