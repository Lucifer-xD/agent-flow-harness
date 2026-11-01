// A thread on one of your computers, live: replies stream in, each step the agent takes shows up as
// it happens, approvals and questions are a tap, and the box at the bottom sends the next message
// (even while it works) or stops the run.
import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_animate/flutter_animate.dart';

import '../remote.dart';
import '../theme.dart';
import '../widgets/common.dart';
import '../widgets/composer.dart';
import '../widgets/logo.dart';
import '../widgets/md.dart';

typedef J = Map<String, dynamic>;

class SessionScreen extends StatefulWidget {
  const SessionScreen({super.key, required this.computer, required this.session});
  final Computer computer;
  final J session;
  @override
  State<SessionScreen> createState() => _SessionScreenState();
}

class _SessionScreenState extends State<SessionScreen> {
  late final Pc _pc = Pc(widget.computer);
  late J _session = widget.session;
  late final String _sid = widget.session['id'] as String;
  List<J> _msgs = [];
  final Map<String, J> _perms = {};
  late bool _running = widget.session['running'] == true;
  String? _runError;
  bool _loaded = false;
  ApiError? _loadError;
  String _live = 'connecting';
  StreamSubscription? _sub;
  Timer? _soon;
  bool _frame = false;
  bool _sending = false;
  final _input = TextEditingController();
  final _focus = FocusNode();
  final Set<String> _open = {};

  @override
  void initState() {
    super.initState();
    _input.addListener(() => setState(() {}));
    _load();
    _sub = _pc
        .events(
          onState: (s) {
            if (!mounted) return;
            setState(() => _live = s);
            if (s == 'live' && _loaded) _load();
          },
        )
        .listen(_onEvent);
  }

  @override
  void dispose() {
    _sub?.cancel();
    _soon?.cancel();
    _input.dispose();
    _focus.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final got = await Future.wait([
        _pc.get('/api/sessions/$_sid'),
        _pc.get('/api/sessions/$_sid/messages'),
        _pc.get('/api/sessions/$_sid/permissions').catchError((_) => <dynamic>[]),
      ]);
      _session = J.from(got[0] as Map);
      _running = _session['running'] == true;
      _msgs = [for (final m in (got[1] as List? ?? [])) _deep(m) as J];
      _perms
        ..clear()
        ..addEntries([for (final p in (got[2] as List? ?? [])) MapEntry('${p['id']}', J.from(p as Map))]);
      _loaded = true;
      _loadError = null;
    } on ApiError catch (e) {
      if (!_loaded) {
        _loadError = e;
      } else if (mounted) {
        showToast(context, e.message, error: true);
      }
    }
    if (mounted) setState(() {});
  }

  // ---- live events (the same stream the desktop app uses) ----

  J _asst(String? id, [J? d]) {
    final key = id ?? 'live';
    for (final m in _msgs) {
      if (m['id'] == key) return m;
    }
    final m = <String, dynamic>{'id': key, 'type': 'assistant', 'content': <dynamic>[], 'live': true};
    _msgs.add(m);
    return m;
  }

  J _part(J m, String type, dynamic ordinal) {
    final content = m['content'] as List;
    for (final c in content) {
      if (c['type'] == type && c['ordinal'] == ordinal) return c as J;
    }
    final p = <String, dynamic>{'type': type, 'ordinal': ordinal, 'text': '', 'live': true};
    content.add(p);
    return p;
  }

  J _tool(J m, String? id, [String? name]) {
    final content = m['content'] as List;
    for (final c in content) {
      if (c['type'] == 'tool' && c['id'] == id) return c as J;
    }
    final p = <String, dynamic>{
      'type': 'tool',
      'id': id,
      'name': name,
      'state': <String, dynamic>{'status': 'pending', 'input': <String, dynamic>{}},
    };
    content.add(p);
    return p;
  }

  void _onEvent(J ev) {
    final d = (ev['data'] as Map?)?.cast<String, dynamic>() ?? {};
    final t = ev['type'] as String? ?? '';
    if (t == 'permission.replied') {
      // replies may not name the thread; the id is enough
      if (_perms.remove('${d['id'] ?? d['permissionID'] ?? d['requestID']}') != null && mounted) setState(() {});
      return;
    }
    if (d['sessionID'] != _sid) return;
    final aid = d['assistantMessageID'] as String?;
    switch (t) {
      case 'session.execution.started':
        _running = true;
        _runError = null;
      case 'session.execution.succeeded' || 'session.execution.interrupted' || 'session.execution.failed':
        _running = false;
        if (t.endsWith('failed')) _runError = '${(d['error'] as Map?)?['message'] ?? 'The run failed'}';
        for (final m in _msgs) {
          m['live'] = false;
          for (final p in (m['content'] as List? ?? [])) {
            if (p is Map) p['live'] = false;
          }
        }
        if (t.endsWith('succeeded')) HapticFeedback.lightImpact();
        Timer(const Duration(milliseconds: 300), _load);
      case 'session.inbox.delivered' || 'session.notice' || 'session.compaction.ended' || 'session.updated':
        _soon?.cancel();
        _soon = Timer(const Duration(milliseconds: 250), _load);
        return;
      case 'session.renamed':
        _session['title'] = d['title'];
      case 'session.step.started':
        _asst(aid, d);
      case 'session.step.failed':
        final err = d['error'] as Map?;
        if (!RegExp('interrupt|abort|cancel', caseSensitive: false).hasMatch('${err?['type'] ?? ''} ${err?['message'] ?? ''}')) {
          _asst(aid)['error'] = err?['message'];
        }
      case 'session.text.started' || 'session.reasoning.started':
        _part(_asst(aid), t.contains('reasoning') ? 'reasoning' : 'text', d['ordinal']);
      case 'session.text.delta' || 'session.reasoning.delta':
        final p = _part(_asst(aid), t.contains('reasoning') ? 'reasoning' : 'text', d['ordinal']);
        p['text'] = '${p['text']}${d['delta'] ?? ''}';
        _redraw();
        return;
      case 'session.text.ended' || 'session.reasoning.ended':
        final p = _part(_asst(aid), t.contains('reasoning') ? 'reasoning' : 'text', d['ordinal']);
        if (d['text'] != null) p['text'] = d['text'];
        p['live'] = false;
      case 'session.tool.input.started':
        _tool(_asst(aid), d['id'] as String?, d['name'] as String?);
      case 'session.tool.called':
        final p = _tool(_asst(aid), d['id'] as String?, d['name'] as String?);
        p['name'] = d['name'] ?? p['name'];
        p['state'] = <String, dynamic>{'status': 'running', 'input': d['input'] ?? <String, dynamic>{}};
      case 'session.tool.success' || 'session.tool.failed':
        final p = _tool(_asst(aid), d['id'] as String?);
        final input = (p['state'] as Map?)?['input'];
        p['state'] = t.endsWith('success')
            ? <String, dynamic>{'status': 'completed', 'input': input, 'content': d['content'], 'metadata': d['metadata']}
            : <String, dynamic>{'status': 'error', 'input': input, 'error': d['error'], 'content': d['content']};
      case 'permission.asked':
        _perms['${d['id']}'] = J.from(d);
        HapticFeedback.heavyImpact();
      default:
        return;
    }
    if (mounted) setState(() {});
  }

  void _redraw() {
    if (_frame || !mounted) return;
    _frame = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _frame = false;
      if (mounted) setState(() {});
    });
    WidgetsBinding.instance.scheduleFrame();
  }

  // ---- actions ----

  Future<void> _send() async {
    final text = _input.text.trim();
    if (text.isEmpty || _sending) return;
    setState(() => _sending = true);
    try {
      await _pc.post('/api/sessions/$_sid/prompt', {'text': text});
      HapticFeedback.lightImpact();
      _input.clear();
      _msgs.add({'id': 'local-${DateTime.now().millisecondsSinceEpoch}', 'type': 'user', 'text': text, 'fresh': true});
      _running = true;
      _runError = null;
      Timer(const Duration(milliseconds: 900), _load);
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.message, error: true);
    }
    if (mounted) setState(() => _sending = false);
  }

  Future<void> _stop() async {
    HapticFeedback.mediumImpact();
    try {
      await _pc.post('/api/sessions/$_sid/interrupt');
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.message, error: true);
    }
  }

  Future<bool> _answer(J req, J body) async {
    try {
      await _pc.post('/api/sessions/$_sid/permissions/${req['id']}', body);
      HapticFeedback.mediumImpact();
      setState(() => _perms.remove('${req['id']}'));
      return true;
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.message, error: true);
      return false;
    }
  }

  String get _subtitle {
    final proj = (_session['project'] ?? _session['location']?['directory'] ?? '') as String;
    final model = _session['model'] is Map ? (_session['model']['id'] ?? _session['model']['modelID'] ?? '') : '';
    return [if (proj.isNotEmpty) baseName(proj), if ('$model'.isNotEmpty) model].join(' · ');
  }

  @override
  Widget build(BuildContext context) {
    final title = '${_session['title'] ?? ''}'.isEmpty ? 'New thread' : '${_session['title']}';
    final shown = _msgs.where((m) => m['type'] == 'user' || m['type'] == 'assistant' || '${m['text'] ?? ''}'.isNotEmpty).toList();
    final last = shown.isEmpty ? null : shown.last;
    final streaming =
        last != null &&
        last['type'] == 'assistant' &&
        (last['content'] as List? ?? []).any((p) => p['live'] == true && p['type'] == 'text' && '${p['text']}'.isNotEmpty);
    final perms = _perms.values.toList();
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 0,
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            AnimatedSwitcher(
              duration: const Duration(milliseconds: 300),
              child: Text(title, key: ValueKey(title), maxLines: 1, overflow: TextOverflow.ellipsis),
            ),
            const SizedBox(height: 2),
            Text(
              _subtitle.isEmpty ? widget.computer.name : '${widget.computer.name} · $_subtitle',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 12.5, color: Afh.text3, fontFamily: Afh.body),
            ),
          ],
        ),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 16),
            child: Tooltip(
              message: _live == 'live' ? 'Live' : 'Reconnecting',
              child: PulseDot(color: _live == 'live' ? Afh.good : Afh.amber, live: _live == 'live'),
            ),
          ),
        ],
      ),
      body: Column(
        children: [
          Expanded(child: _list(shown, streaming)),
          Composer(
            controller: _input,
            focus: _focus,
            busy: _running,
            sendWhileBusy: true,
            onSend: _send,
            onStop: _stop,
            bottom: MediaQuery.paddingOf(context).bottom,
            hint: _running ? 'Add to the run…' : 'Message AFH…',
            top: perms.isEmpty
                ? null
                : Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: AnimatedSwitcher(
                      duration: const Duration(milliseconds: 350),
                      transitionBuilder: (c, a) => SizeTransition(
                        sizeFactor: a,
                        child: FadeTransition(opacity: a, child: c),
                      ),
                      child: Column(
                        key: ValueKey(perms.first['id']),
                        children: [
                          perms.first['action'] == 'question'
                              ? _QuestionCard(req: perms.first, onAnswer: _answer)
                              : _ApprovalCard(req: perms.first, onAnswer: _answer),
                          if (perms.length > 1)
                            Padding(
                              padding: const EdgeInsets.only(top: 6),
                              child: Text('+${perms.length - 1} more waiting', style: const TextStyle(color: Afh.text3, fontSize: 12.5)),
                            ),
                        ],
                      ),
                    ),
                  ),
          ),
        ],
      ),
    );
  }

  Widget _list(List<J> shown, bool streaming) {
    if (!_loaded && _loadError != null) {
      final off = _loadError!.offline;
      return ListView(
        children: [
          const SizedBox(height: 60),
          EmptyState(
            icon: off ? Icons.bedtime_rounded : Icons.error_outline_rounded,
            title: off ? '${widget.computer.name} is offline' : 'Couldn\'t open this thread',
            text: _loadError!.message,
            action: GhostButton(label: 'Try again', icon: Icons.refresh_rounded, onTap: _load),
          ),
        ],
      );
    }
    if (!_loaded) return const Center(child: AfhLogo(width: 110, working: true));
    if (shown.isEmpty && !_running) {
      return const Center(
        child: EmptyState(icon: Icons.auto_awesome_rounded, title: 'A fresh thread', text: 'Send the first message below.'),
      );
    }
    final items = <Widget>[
      for (final m in shown) KeyedSubtree(key: ValueKey(m['id']), child: _message(m)),
      if (_running && !streaming) const _Working(),
      if (_runError != null && !_running) _ErrorNote(_runError!),
    ];
    return ListView.builder(
      reverse: true,
      keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 16),
      itemCount: items.length,
      itemBuilder: (_, i) => items[items.length - 1 - i],
    );
  }

  Widget _message(J m) {
    if (m['type'] == 'user') {
      final files = (m['files'] as List? ?? []).length;
      Widget w = Align(
        alignment: Alignment.centerRight,
        child: Container(
          margin: const EdgeInsets.only(left: 48, top: 12, bottom: 4),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 11),
          decoration: BoxDecoration(
            gradient: const LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [Color(0xFF3B2416), Color(0xFF3A1928)]),
            borderRadius: const BorderRadius.only(
              topLeft: Radius.circular(22),
              topRight: Radius.circular(22),
              bottomLeft: Radius.circular(22),
              bottomRight: Radius.circular(7),
            ),
            border: Border.all(color: Afh.orange.withValues(alpha: 0.28)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text('${m['text'] ?? ''}', style: const TextStyle(fontSize: 15.5, height: 1.45, color: Color(0xFFFFF3EA))),
              if (files > 0)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.attach_file_rounded, size: 14, color: Afh.text2),
                      Text('$files file${files > 1 ? 's' : ''}', style: const TextStyle(fontSize: 12.5, color: Afh.text2)),
                    ],
                  ),
                ),
            ],
          ),
        ),
      );
      if (m['fresh'] == true) w = w.animate().fadeIn(duration: 250.ms).moveY(begin: 12, end: 0, curve: Afh.ease);
      return w;
    }
    if (m['type'] != 'assistant') {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 10),
        child: Center(
          child: Text(
            '${m['text'] ?? m['metadata']?['label'] ?? ''}',
            textAlign: TextAlign.center,
            style: const TextStyle(color: Afh.text3, fontSize: 12.5),
          ),
        ),
      );
    }
    final out = <Widget>[];
    var group = <J>[];
    void flush() {
      if (group.isEmpty) return;
      out.add(_ToolGroup(key: ValueKey('g${group.first['id']}'), tools: group, open: _open, onToggle: () => setState(() {})));
      group = [];
    }

    for (final p in (m['content'] as List? ?? []).cast<Map>()) {
      final part = p.cast<String, dynamic>();
      if (part['type'] == 'tool') {
        group.add(part);
        continue;
      }
      flush();
      final text = '${part['text'] ?? ''}';
      if (part['type'] == 'text' && text.isNotEmpty) {
        out.add(Padding(padding: const EdgeInsets.symmetric(vertical: 4), child: Md(text)));
      } else if (part['type'] == 'reasoning' && text.trim().isNotEmpty) {
        final key = 'r:${m['id']}:${part['ordinal']}';
        out.add(
          _Fold(
            icon: Icons.psychology_alt_rounded,
            title: part['live'] == true ? 'Thinking…' : 'Thought',
            live: part['live'] == true,
            open: _open.contains(key),
            onTap: () => setState(() => _open.contains(key) ? _open.remove(key) : _open.add(key)),
            child: Text(text.trim(), style: const TextStyle(color: Afh.text3, fontSize: 13.5, height: 1.45)),
          ),
        );
      }
    }
    flush();
    if (m['error'] != null) out.add(_ErrorNote('${m['error']}'));
    return Padding(
      padding: const EdgeInsets.only(top: 12, bottom: 2),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: out),
    );
  }
}

dynamic _deep(dynamic v) {
  if (v is Map) return <String, dynamic>{for (final e in v.entries) '${e.key}': _deep(e.value)};
  if (v is List) return [for (final x in v) _deep(x)];
  return v;
}

class _Working extends StatelessWidget {
  const _Working();
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 14),
      child: Row(
        children: [
          const AfhLogo(width: 44, working: true, intro: false),
          const SizedBox(width: 12),
          const Text(
            'AFH is working',
            style: TextStyle(color: Afh.text2, fontWeight: FontWeight.w600),
          ).animate(onPlay: (c) => c.repeat()).shimmer(duration: 1600.ms, color: Afh.amber),
        ],
      ),
    ).animate().fadeIn();
  }
}

class _ErrorNote extends StatelessWidget {
  const _ErrorNote(this.text);
  final String text;
  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 6),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Afh.bad.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: Afh.bad.withValues(alpha: 0.3)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.error_outline_rounded, size: 18, color: Afh.bad),
          const SizedBox(width: 8),
          Expanded(
            child: Text(text, style: const TextStyle(color: Color(0xFFFFC2CD), height: 1.4)),
          ),
        ],
      ),
    );
  }
}

/// A box with a header that folds its body away.
class _Fold extends StatelessWidget {
  const _Fold({required this.icon, required this.title, required this.open, required this.onTap, required this.child, this.live = false});
  final IconData icon;
  final String title;
  final bool open, live;
  final VoidCallback onTap;
  final Widget child;
  @override
  Widget build(BuildContext context) {
    Widget label = Text(
      title,
      maxLines: 1,
      overflow: TextOverflow.ellipsis,
      style: const TextStyle(fontWeight: FontWeight.w600, color: Afh.text2, fontSize: 13.5),
    );
    if (live) label = label.animate(onPlay: (c) => c.repeat()).shimmer(duration: 1400.ms, color: Afh.amber);
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 4),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.035),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Afh.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InkWell(
            borderRadius: BorderRadius.circular(16),
            onTap: onTap,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
              child: Row(
                children: [
                  Icon(icon, size: 17, color: Afh.amber),
                  const SizedBox(width: 9),
                  Expanded(child: label),
                  AnimatedRotation(
                    turns: open ? 0.5 : 0,
                    duration: const Duration(milliseconds: 250),
                    child: const Icon(Icons.keyboard_arrow_down_rounded, size: 20, color: Afh.text3),
                  ),
                ],
              ),
            ),
          ),
          AnimatedSize(
            duration: const Duration(milliseconds: 300),
            curve: Afh.ease,
            alignment: Alignment.topCenter,
            child: open ? Padding(padding: const EdgeInsets.fromLTRB(12, 0, 12, 12), child: child) : const SizedBox(width: double.infinity),
          ),
        ],
      ),
    );
  }
}

// ---- tools ----

const _verbs = {
  'write': ('Wrote', 'Writing'),
  'edit': ('Edited', 'Editing'),
  'multiedit': ('Edited', 'Editing'),
  'patch': ('Patched', 'Patching'),
  'apply_patch': ('Patched', 'Patching'),
  'shell': ('Ran', 'Running'),
  'bash': ('Ran', 'Running'),
  'execute': ('Ran code', 'Running code'),
  'read': ('Read', 'Reading'),
  'glob': ('Found files', 'Finding files'),
  'grep': ('Searched', 'Searching'),
  'list': ('Listed', 'Listing'),
  'ls': ('Listed', 'Listing'),
  'webfetch': ('Fetched', 'Fetching'),
  'websearch': ('Searched the web', 'Searching the web'),
  'skill': ('Loaded skill', 'Loading skill'),
  'question': ('Asked', 'Asking'),
  'todowrite': ('Planned', 'Planning'),
  'todoread': ('Checked plan', 'Checking plan'),
  'memory': ('Updated memory', 'Updating memory'),
  'task': ('Delegated', 'Delegating'),
  'browser': ('Used the browser', 'Using the browser'),
  'goal': ('Set the goal', 'Setting the goal'),
};

String? _pick(Map input, List<String> keys) {
  for (final k in keys) {
    final v = input[k];
    if (v != null && '$v'.isNotEmpty) return '$v';
  }
  return null;
}

(IconData, String, String) _toolLook(J p) {
  final name = '${p['name'] ?? ''}'.toLowerCase();
  final st = (p['state'] as Map?) ?? {};
  final input = st['input'] is Map ? st['input'] as Map : const {};
  final done = st['status'] == 'completed' || st['status'] == 'error';
  final v = _verbs[name] ?? (name.isEmpty ? 'Tool' : name.replaceAll('_', ' '), name.isEmpty ? 'Working' : name.replaceAll('_', ' '));
  final verb = done ? v.$1 : v.$2;
  var icon = Icons.build_rounded;
  var target = _pick(input, ['path', 'filePath', 'file_path', 'file']) ?? '';
  var isPath = target.isNotEmpty;
  if (RegExp(r'^(write|edit|multiedit|patch|apply_patch)$').hasMatch(name)) {
    icon = Icons.edit_document;
  } else if (name == 'read') {
    icon = Icons.description_rounded;
  } else if (RegExp(r'^(shell|bash|exec|execute|command)$').hasMatch(name)) {
    icon = Icons.terminal_rounded;
    target = _pick(input, ['command', 'cmd', 'code']) ?? '';
    isPath = false;
  } else if (RegExp(r'^(grep|glob|search|find|list|ls)$').hasMatch(name)) {
    icon = Icons.search_rounded;
    target = _pick(input, ['pattern', 'query', 'path']) ?? '';
  } else if (name == 'browser') {
    icon = Icons.public_rounded;
    target = _pick(input, ['url', 'action']) ?? '';
    isPath = false;
  } else if (RegExp('web|fetch').hasMatch(name)) {
    icon = Icons.language_rounded;
    target = _pick(input, ['url', 'query']) ?? '';
    isPath = false;
  } else if (RegExp('task|agent|delegate').hasMatch(name)) {
    icon = Icons.groups_rounded;
    target = _pick(input, ['description', 'prompt']) ?? '';
    isPath = false;
  } else if (name == 'question') {
    icon = Icons.help_rounded;
    final qs = input['questions'];
    target = qs is List && qs.isNotEmpty && qs.first is Map ? (_pick(qs.first as Map, ['question']) ?? '') : '';
    isPath = false;
  } else if (RegExp('todo|plan|goal').hasMatch(name)) {
    icon = Icons.checklist_rounded;
    target = _pick(input, ['objective', 'goal']) ?? '';
    isPath = false;
  } else if (RegExp('memory|skill').hasMatch(name)) {
    icon = Icons.bookmark_rounded;
  }
  if (isPath && !target.contains(' ')) target = baseName(target);
  target = target.split('\n').first;
  if (target.length > 140) target = target.substring(0, 140);
  return (icon, verb, target);
}

String _toolText(dynamic content) {
  if (content == null) return '';
  if (content is String) return content;
  if (content is List) {
    return content
        .map((c) => c is String ? c : (c is Map ? (c['text'] ?? (c['type'] == 'image' ? '[image]' : '')) : ''))
        .where((s) => '$s'.isNotEmpty)
        .join('\n');
  }
  if (content is Map) return const JsonEncoder.withIndent('  ').convert(content);
  return '$content';
}

String _clip(String s, [int n = 4000]) => s.length > n ? '${s.substring(0, n)}\n… ${s.length - n} more characters' : s;

class _ToolGroup extends StatelessWidget {
  const _ToolGroup({super.key, required this.tools, required this.open, required this.onToggle});
  final List<J> tools;
  final Set<String> open;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    final key = 'g:${tools.first['id']}';
    bool busy(J p) => ['running', 'pending'].contains((p['state'] as Map?)?['status']);
    final anyBusy = tools.any(busy);
    final failed = tools.where((p) => (p['state'] as Map?)?['status'] == 'error').length;
    final collapsible = tools.length > 2;
    final expanded = !collapsible || anyBusy || open.contains(key);
    final rows = Column(
      children: [for (final p in tools) _ToolRow(key: ValueKey('t${p['id']}'), tool: p, open: open, onToggle: onToggle)],
    );
    if (!collapsible) return Padding(padding: const EdgeInsets.symmetric(vertical: 4), child: rows);
    return _Fold(
      icon: anyBusy ? Icons.autorenew_rounded : Icons.done_all_rounded,
      title: anyBusy ? 'Working · ${tools.length} steps' : '${tools.length} steps${failed > 0 ? ' · $failed failed' : ''}',
      live: anyBusy,
      open: expanded,
      onTap: () {
        open.contains(key) ? open.remove(key) : open.add(key);
        onToggle();
      },
      child: rows,
    );
  }
}

class _ToolRow extends StatelessWidget {
  const _ToolRow({super.key, required this.tool, required this.open, required this.onToggle});
  final J tool;
  final Set<String> open;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    final (icon, verb, target) = _toolLook(tool);
    final st = (tool['state'] as Map?) ?? {};
    final status = '${st['status'] ?? 'pending'}';
    final input = st['input'] is Map ? st['input'] as Map : const {};
    final key = 't:${tool['id']}';
    final isOpen = open.contains(key);
    final cmd = _pick(input, ['command', 'cmd', 'code']);
    final err = st['error'];
    final out = err != null ? _toolText(err is Map ? (err['message'] ?? err) : err) : _toolText(st['content']);
    final running = status == 'running' || status == 'pending';
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 3),
      decoration: BoxDecoration(
        color: Afh.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: status == 'error'
              ? Afh.bad.withValues(alpha: 0.35)
              : running
              ? Afh.orange.withValues(alpha: 0.35)
              : Afh.line,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InkWell(
            borderRadius: BorderRadius.circular(14),
            onTap: () {
              isOpen ? open.remove(key) : open.add(key);
              onToggle();
            },
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              child: Row(
                children: [
                  Icon(icon, size: 17, color: running ? Afh.orange : Afh.text2),
                  const SizedBox(width: 9),
                  Text(verb, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13.5)),
                  const SizedBox(width: 7),
                  Expanded(
                    child: Text(
                      target,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontFamily: Afh.mono, fontSize: 12.5, color: Afh.text3),
                    ),
                  ),
                  const SizedBox(width: 6),
                  if (running)
                    const SizedBox(width: 15, height: 15, child: CircularProgressIndicator(strokeWidth: 2, color: Afh.orange))
                  else
                    Icon(
                      status == 'error' ? Icons.cancel_rounded : Icons.check_circle_rounded,
                      size: 17,
                      color: status == 'error' ? Afh.bad : Afh.good,
                    ).animate().scale(curve: Afh.spring, duration: 400.ms),
                ],
              ),
            ),
          ),
          AnimatedSize(
            duration: const Duration(milliseconds: 280),
            curve: Afh.ease,
            alignment: Alignment.topCenter,
            child: !isOpen
                ? const SizedBox(width: double.infinity)
                : Padding(
                    padding: const EdgeInsets.fromLTRB(10, 0, 10, 10),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        if (cmd != null)
                          _Code(_clip(cmd, 2000))
                        else if (input.isNotEmpty)
                          _Code(_clip(const JsonEncoder.withIndent('  ').convert(input), 2000)),
                        if (out.isNotEmpty) ...[const SizedBox(height: 6), _Code(_clip(out), bad: status == 'error')],
                      ],
                    ),
                  ),
          ),
        ],
      ),
    );
  }
}

class _Code extends StatelessWidget {
  const _Code(this.text, {this.bad = false, this.diff = false});
  final String text;
  final bool bad, diff;
  @override
  Widget build(BuildContext context) {
    final lines = text.split('\n');
    return Container(
      constraints: const BoxConstraints(maxHeight: 320),
      decoration: BoxDecoration(
        color: const Color(0xFF0F0C0A),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: bad ? Afh.bad.withValues(alpha: 0.3) : Afh.line),
      ),
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(10),
        child: SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: diff
              ? Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final l in lines)
                      Text(
                        l,
                        style: TextStyle(
                          fontFamily: Afh.mono,
                          fontSize: 12,
                          height: 1.45,
                          color: l.startsWith('+') && !l.startsWith('+++')
                              ? Afh.good
                              : l.startsWith('-') && !l.startsWith('---')
                              ? Afh.bad
                              : l.startsWith('@@')
                              ? Afh.amber
                              : Afh.text2,
                        ),
                      ),
                  ],
                )
              : Text(
                  text,
                  style: TextStyle(fontFamily: Afh.mono, fontSize: 12, height: 1.45, color: bad ? const Color(0xFFFFC2CD) : Afh.text2),
                ),
        ),
      ),
    );
  }
}

// ---- approvals and questions ----

class _ApprovalCard extends StatefulWidget {
  const _ApprovalCard({required this.req, required this.onAnswer});
  final J req;
  final Future<bool> Function(J req, J body) onAnswer;
  @override
  State<_ApprovalCard> createState() => _ApprovalCardState();
}

class _ApprovalCardState extends State<_ApprovalCard> {
  String? _busy;
  String? _openFile;

  Future<void> _go(String decision) async {
    setState(() => _busy = decision);
    final ok = await widget.onAnswer(widget.req, {'decision': decision});
    if (!ok && mounted) setState(() => _busy = null);
  }

  @override
  Widget build(BuildContext context) {
    final r = widget.req;
    final md = (r['metadata'] as Map?) ?? {};
    final files = (md['files'] as List? ?? []).whereType<Map>().toList();
    final resources = (r['resources'] as List? ?? []).map((e) => '$e').toList();
    return _CardShell(
      icon: Icons.verified_user_rounded,
      title: 'Approval needed',
      sub: '${md['title'] ?? r['action'] ?? 'The agent wants to continue'}',
      children: [
        if (md['command'] != null) _Code(_clip('${md['command']}', 1500)),
        if (files.isNotEmpty)
          ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: 220),
            child: ListView(
              shrinkWrap: true,
              children: [
                for (final f in files.take(8))
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      InkWell(
                        onTap: () => setState(() => _openFile = _openFile == '${f['file']}' ? null : '${f['file']}'),
                        child: Padding(
                          padding: const EdgeInsets.symmetric(vertical: 7),
                          child: Row(
                            children: [
                              _FileStat('${f['status'] ?? 'modified'}'),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(
                                  baseName('${f['file']}'),
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(fontFamily: Afh.mono, fontSize: 13),
                                ),
                              ),
                              if (f['patch'] != null)
                                Icon(_openFile == '${f['file']}' ? Icons.expand_less_rounded : Icons.expand_more_rounded, size: 18, color: Afh.text3),
                            ],
                          ),
                        ),
                      ),
                      if (_openFile == '${f['file']}' && f['patch'] != null) _Code(_clip('${f['patch']}', 3000), diff: true),
                    ],
                  ),
                if (files.length > 8) Text('+${files.length - 8} more files', style: const TextStyle(color: Afh.text3, fontSize: 12.5)),
              ],
            ),
          ),
        if (md['command'] == null && files.isEmpty && resources.isNotEmpty) _Code(resources.take(8).join('\n')),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: _PermButton(label: 'Reject', kind: 0, busy: _busy == 'reject', onTap: _busy == null ? () => _go('reject') : null),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: _PermButton(label: 'Always', kind: 1, busy: _busy == 'always', onTap: _busy == null ? () => _go('always') : null),
            ),
            const SizedBox(width: 8),
            Expanded(
              flex: 2,
              child: _PermButton(label: 'Allow', kind: 2, busy: _busy == 'once', onTap: _busy == null ? () => _go('once') : null),
            ),
          ],
        ),
      ],
    );
  }
}

class _FileStat extends StatelessWidget {
  const _FileStat(this.status);
  final String status;
  @override
  Widget build(BuildContext context) {
    final c = status.startsWith('a')
        ? Afh.good
        : status.startsWith('d')
        ? Afh.bad
        : Afh.amber;
    return Container(
      width: 22,
      height: 22,
      alignment: Alignment.center,
      decoration: BoxDecoration(color: c.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(6)),
      child: Text(
        status.isEmpty ? 'M' : status[0].toUpperCase(),
        style: TextStyle(color: c, fontWeight: FontWeight.w800, fontSize: 12),
      ),
    );
  }
}

class _QuestionCard extends StatefulWidget {
  const _QuestionCard({required this.req, required this.onAnswer});
  final J req;
  final Future<bool> Function(J req, J body) onAnswer;
  @override
  State<_QuestionCard> createState() => _QuestionCardState();
}

class _QuestionCardState extends State<_QuestionCard> {
  late final List<Map> _qs = ((widget.req['metadata'] as Map?)?['questions'] as List? ?? []).whereType<Map>().toList();
  late final List<Set<String>> _picks = [for (final _ in _qs) <String>{}];
  late final List<TextEditingController> _others = [for (final _ in _qs) TextEditingController()];
  String? _busy;

  @override
  void dispose() {
    for (final c in _others) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _go(bool skip) async {
    setState(() => _busy = skip ? 'skip' : 'send');
    final body = skip
        ? <String, dynamic>{'decision': 'dismiss'}
        : <String, dynamic>{
            'decision': 'answer',
            'answers': [
              for (var i = 0; i < _qs.length; i++) {'selected': _picks[i].toList(), 'other': _others[i].text},
            ],
          };
    final ok = await widget.onAnswer(widget.req, body);
    if (!ok && mounted) setState(() => _busy = null);
  }

  @override
  Widget build(BuildContext context) {
    return _CardShell(
      icon: Icons.help_rounded,
      title: 'AFH has a question',
      sub: _qs.length > 1 ? '${_qs.length} questions' : 'Pick an answer',
      children: [
        ConstrainedBox(
          constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(context).height * 0.42),
          child: ListView(
            shrinkWrap: true,
            children: [
              for (var i = 0; i < _qs.length; i++) ...[
                if (_qs[i]['header'] != null) Text('${_qs[i]['header']}'.toUpperCase(), style: Afh.label),
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Text('${_qs[i]['question'] ?? ''}', style: const TextStyle(fontWeight: FontWeight.w600, height: 1.35)),
                ),
                for (final o in (_qs[i]['options'] as List? ?? []).whereType<Map>())
                  Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: Pressable(
                      scale: 0.98,
                      onTap: () => setState(() {
                        final label = '${o['label']}';
                        if (_qs[i]['multiple'] != true) {
                          final had = _picks[i].contains(label);
                          _picks[i].clear();
                          if (!had) _picks[i].add(label);
                        } else {
                          _picks[i].contains(label) ? _picks[i].remove(label) : _picks[i].add(label);
                        }
                      }),
                      child: AnimatedContainer(
                        duration: const Duration(milliseconds: 200),
                        width: double.infinity,
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          gradient: _picks[i].contains('${o['label']}') ? const LinearGradient(colors: [Color(0x38FFB11F), Color(0x38FF3D8A)]) : null,
                          color: _picks[i].contains('${o['label']}') ? null : Afh.surface2,
                          borderRadius: BorderRadius.circular(14),
                          border: Border.all(color: _picks[i].contains('${o['label']}') ? Afh.orange.withValues(alpha: 0.6) : Afh.line),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('${o['label']}', style: const TextStyle(fontWeight: FontWeight.w700)),
                            if (o['description'] != null && '${o['description']}'.isNotEmpty)
                              Padding(
                                padding: const EdgeInsets.only(top: 3),
                                child: Text('${o['description']}', style: const TextStyle(color: Afh.text2, fontSize: 13)),
                              ),
                          ],
                        ),
                      ),
                    ),
                  ),
                TextField(
                  controller: _others[i],
                  decoration: const InputDecoration(hintText: 'Or type your own answer', contentPadding: EdgeInsets.symmetric(horizontal: 14, vertical: 12)),
                ),
                const SizedBox(height: 12),
              ],
            ],
          ),
        ),
        Row(
          children: [
            Expanded(
              child: _PermButton(label: 'Skip', kind: 1, busy: _busy == 'skip', onTap: _busy == null ? () => _go(true) : null),
            ),
            const SizedBox(width: 8),
            Expanded(
              flex: 2,
              child: _PermButton(label: 'Send answer', kind: 2, busy: _busy == 'send', onTap: _busy == null ? () => _go(false) : null),
            ),
          ],
        ),
      ],
    );
  }
}

class _CardShell extends StatelessWidget {
  const _CardShell({required this.icon, required this.title, required this.sub, required this.children});
  final IconData icon;
  final String title, sub;
  final List<Widget> children;
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Afh.surface2,
        borderRadius: BorderRadius.circular(24),
        border: Border.all(color: Afh.orange.withValues(alpha: 0.45)),
        boxShadow: [BoxShadow(color: Afh.orange.withValues(alpha: 0.15), blurRadius: 30, spreadRadius: -6)],
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Container(
                width: 38,
                height: 38,
                decoration: BoxDecoration(gradient: Afh.grad, borderRadius: BorderRadius.circular(12)),
                child: Icon(icon, size: 20, color: const Color(0xFF1A0D05)),
              ).animate(onPlay: (c) => c.repeat(reverse: true)).scaleXY(end: 1.08, duration: 900.ms, curve: Curves.easeInOut),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15.5)),
                    Text(
                      sub,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(color: Afh.text2, fontSize: 13),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          ...children,
        ],
      ),
    ).animate().fadeIn(duration: 250.ms).moveY(begin: 20, end: 0, curve: Afh.spring, duration: 500.ms);
  }
}

class _PermButton extends StatelessWidget {
  const _PermButton({required this.label, required this.kind, required this.busy, this.onTap});
  final String label;
  final int kind; // 0 reject, 1 quiet, 2 primary
  final bool busy;
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) {
    final fg = kind == 2
        ? const Color(0xFF1A0D05)
        : kind == 0
        ? Afh.bad
        : Afh.text;
    return Pressable(
      onTap: onTap,
      child: AnimatedOpacity(
        duration: const Duration(milliseconds: 200),
        opacity: onTap == null && !busy ? 0.5 : 1,
        child: Container(
          height: 46,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            gradient: kind == 2 ? Afh.grad : null,
            color: kind == 2
                ? null
                : kind == 0
                ? Afh.bad.withValues(alpha: 0.1)
                : Afh.surface3,
            borderRadius: BorderRadius.circular(23),
            border: kind == 0 ? Border.all(color: Afh.bad.withValues(alpha: 0.35)) : null,
          ),
          child: busy
              ? SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: fg))
              : Text(
                  label,
                  style: TextStyle(fontWeight: FontWeight.w700, color: fg),
                ),
        ),
      ),
    );
  }
}
