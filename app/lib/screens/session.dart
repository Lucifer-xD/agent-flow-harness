// A thread on one of your computers, live: replies stream in, each step the agent takes shows up as
// it happens, approvals and questions are a tap, and the box at the bottom sends the next message
// (even while it works) or stops the run.
import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

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
    final (Color dot, String state, bool pulse) = _live != 'live'
        ? (Afh.warn, _live == 'connecting' ? 'Connecting' : 'Reconnecting', true)
        : perms.isNotEmpty
        ? (Afh.warn, 'Needs you', true)
        : _running
        ? (Afh.accent, 'Working', true)
        : _runError != null
        ? (Afh.bad, 'Failed', false)
        : (Afh.good, 'Live', false);
    final where = _subtitle.isEmpty ? widget.computer.name : '${widget.computer.name} · $_subtitle';
    return Scaffold(
      appBar: AppBar(
        title: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            AnimatedSwitcher(
              duration: Afh.med,
              child: Text(title, key: ValueKey(title), maxLines: 1, overflow: TextOverflow.ellipsis),
            ),
            const SizedBox(height: 1),
            Tooltip(
              message: _live == 'live' ? 'Live' : 'Reconnecting',
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  PulseDot(color: dot, live: pulse, size: 6),
                  const SizedBox(width: 3),
                  Flexible(
                    child: Text(
                      '$state · $where',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w400, color: Afh.text3, fontFamily: Afh.body),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
        actions: const [SizedBox(width: 8)],
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
                      duration: Afh.med,
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
                              child: Text('+${perms.length - 1} more waiting', style: TextStyle(color: Afh.text3, fontSize: 12.5)),
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
            icon: off ? LucideIcons.wifiOff : LucideIcons.circleAlert,
            title: off ? '${widget.computer.name} is offline' : 'Couldn\'t open this thread',
            text: _loadError!.message,
            action: SecondaryButton(label: 'Try again', icon: LucideIcons.refreshCw, onTap: _load),
          ),
        ],
      );
    }
    if (!_loaded) return const Center(child: AfhLogo(width: 96, working: true));
    if (shown.isEmpty && !_running) {
      return const Center(
        child: EmptyState(icon: LucideIcons.sparkles, title: 'A fresh thread', text: 'Send the first message below.'),
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
      padding: const EdgeInsets.fromLTRB(18, 8, 18, 12),
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
          constraints: BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * 0.8),
          margin: const EdgeInsets.only(top: 14, bottom: 4),
          padding: const EdgeInsets.symmetric(horizontal: 15, vertical: 10),
          decoration: BoxDecoration(
            color: Afh.p.bubble,
            borderRadius: const BorderRadius.only(
              topLeft: Radius.circular(20),
              topRight: Radius.circular(20),
              bottomLeft: Radius.circular(20),
              bottomRight: Radius.circular(6),
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text('${m['text'] ?? ''}', style: TextStyle(fontSize: 15.5, height: 1.45, color: Afh.text)),
              if (files > 0)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(LucideIcons.paperclip, size: 13, color: Afh.text2),
                      const SizedBox(width: 4),
                      Text('$files file${files > 1 ? 's' : ''}', style: TextStyle(fontSize: 12.5, color: Afh.text2)),
                    ],
                  ),
                ),
            ],
          ),
        ),
      );
      if (m['fresh'] == true) w = w.enter();
      return w;
    }
    if (m['type'] != 'assistant') {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 12),
        child: Row(
          children: [
            Expanded(child: Divider(color: Afh.line)),
            Flexible(
              flex: 4,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 10),
                child: Text(
                  '${m['text'] ?? m['metadata']?['label'] ?? ''}',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: Afh.text3, fontSize: 12.5, height: 1.35),
                ),
              ),
            ),
            Expanded(child: Divider(color: Afh.line)),
          ],
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
          _Thoughts(
            text: text.trim(),
            live: part['live'] == true,
            open: _open.contains(key),
            onTap: () => setState(() => _open.contains(key) ? _open.remove(key) : _open.add(key)),
          ),
        );
      }
    }
    flush();
    if (m['error'] != null) out.add(_ErrorNote('${m['error']}'));
    return Padding(
      padding: const EdgeInsets.only(top: 14, bottom: 2),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: out),
    );
  }
}

dynamic _deep(dynamic v) {
  if (v is Map) return <String, dynamic>{for (final e in v.entries) '${e.key}': _deep(e.value)};
  if (v is List) return [for (final x in v) _deep(x)];
  return v;
}

/// "Working" under the last message while the run hasn't started writing yet.
class _Working extends StatelessWidget {
  const _Working();
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 2),
      child: Row(
        children: [
          TypingDots(color: Afh.text3),
          const SizedBox(width: 10),
          Text(
            'Working…',
            style: TextStyle(color: Afh.text3, fontSize: 13.5, fontWeight: FontWeight.w500),
          ).animate(onPlay: (c) => c.repeat()).shimmer(duration: 1600.ms, color: Afh.text),
        ],
      ),
    ).animate().fadeIn(duration: 250.ms);
  }
}

class _ErrorNote extends StatelessWidget {
  const _ErrorNote(this.text);
  final String text;
  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 6),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Afh.bad.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(Afh.r),
        border: Border.all(color: Afh.bad.withValues(alpha: 0.3)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(padding: const EdgeInsets.only(top: 1), child: Icon(LucideIcons.circleAlert, size: 18, color: Afh.bad)),
          const SizedBox(width: 10),
          Expanded(
            child: Text(text, style: TextStyle(color: Afh.text, fontSize: 14, height: 1.4)),
          ),
        ],
      ),
    );
  }
}

/// The agent's reasoning: a quiet "Thought" line that unfolds into text along a hairline.
class _Thoughts extends StatelessWidget {
  const _Thoughts({required this.text, required this.live, required this.open, required this.onTap});
  final String text;
  final bool live, open;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final label = Text(live ? 'Thinking' : 'Thought', style: TextStyle(fontWeight: FontWeight.w500, fontSize: 14, color: Afh.text2));
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Pressable(
            scale: 0.98,
            onTap: onTap,
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(LucideIcons.brain, size: 16, color: Afh.text3),
                  const SizedBox(width: 8),
                  live ? label.animate(onPlay: (c) => c.repeat()).shimmer(duration: 1500.ms, color: Afh.text) : label,
                  const SizedBox(width: 4),
                  AnimatedRotation(
                    turns: open ? 0.25 : 0,
                    duration: Afh.fast,
                    child: Icon(LucideIcons.chevronRight, size: 15, color: Afh.text3),
                  ),
                ],
              ),
            ),
          ),
          AnimatedSize(
            duration: Afh.med,
            curve: Afh.ease,
            alignment: Alignment.topCenter,
            child: open
                ? Container(
                    width: double.infinity,
                    margin: const EdgeInsets.only(top: 6, left: 7, bottom: 4),
                    padding: const EdgeInsets.only(left: 14),
                    decoration: BoxDecoration(border: Border(left: BorderSide(color: Afh.line2, width: 2))),
                    child: Text(text, style: TextStyle(color: Afh.text3, fontSize: 13.5, height: 1.5)),
                  )
                : const SizedBox(width: double.infinity),
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

/// The icon, verb ("Edited"/"Editing"), short target and whether the target is code-like (mono).
(IconData, String, String, bool) _toolLook(J p) {
  final name = '${p['name'] ?? ''}'.toLowerCase();
  final st = (p['state'] as Map?) ?? {};
  final input = st['input'] is Map ? st['input'] as Map : const {};
  final done = st['status'] == 'completed' || st['status'] == 'error';
  final v = _verbs[name] ?? (name.isEmpty ? 'Tool' : name.replaceAll('_', ' '), name.isEmpty ? 'Working' : name.replaceAll('_', ' '));
  final verb = done ? v.$1 : v.$2;
  var icon = LucideIcons.wrench;
  var target = _pick(input, ['path', 'filePath', 'file_path', 'file']) ?? '';
  var isPath = target.isNotEmpty;
  var mono = true;
  if (RegExp(r'^(write|edit|multiedit|patch|apply_patch)$').hasMatch(name)) {
    icon = LucideIcons.filePen;
  } else if (name == 'read') {
    icon = LucideIcons.fileText;
  } else if (RegExp(r'^(shell|bash|exec|execute|command)$').hasMatch(name)) {
    icon = LucideIcons.terminal;
    target = _pick(input, ['command', 'cmd', 'code']) ?? '';
    isPath = false;
  } else if (RegExp(r'^(grep|glob|search|find|list|ls)$').hasMatch(name)) {
    icon = LucideIcons.search;
    target = _pick(input, ['pattern', 'query', 'path']) ?? '';
  } else if (name == 'browser') {
    icon = LucideIcons.monitor;
    target = _pick(input, ['url', 'action']) ?? '';
    isPath = false;
  } else if (RegExp('web|fetch').hasMatch(name)) {
    icon = LucideIcons.globe;
    target = _pick(input, ['url', 'query']) ?? '';
    isPath = false;
    mono = target.startsWith('http');
  } else if (RegExp('task|agent|delegate').hasMatch(name)) {
    icon = LucideIcons.bot;
    target = _pick(input, ['description', 'prompt']) ?? '';
    isPath = false;
    mono = false;
  } else if (name == 'question') {
    icon = LucideIcons.messageCircleQuestion;
    final qs = input['questions'];
    target = qs is List && qs.isNotEmpty && qs.first is Map ? (_pick(qs.first as Map, ['question']) ?? '') : '';
    isPath = false;
    mono = false;
  } else if (RegExp('todo|plan|goal').hasMatch(name)) {
    icon = LucideIcons.listChecks;
    target = _pick(input, ['objective', 'goal']) ?? '';
    isPath = false;
    mono = false;
  } else if (RegExp('memory|skill').hasMatch(name)) {
    icon = LucideIcons.bookmark;
  }
  if (isPath && !target.contains(' ')) target = baseName(target);
  target = target.split('\n').first;
  if (target.length > 140) target = target.substring(0, 140);
  return (icon, verb, target, mono);
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

/// A run of tool calls in one hairline box; more than two fold behind a "N steps" header.
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
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (var i = 0; i < tools.length; i++) ...[
          if (i > 0) Divider(height: 1, color: Afh.line),
          _ToolRow(key: ValueKey('t${tools[i]['id']}'), tool: tools[i], open: open, onToggle: onToggle),
        ],
      ],
    );
    Widget header() {
      Widget label = Text(
        anyBusy ? 'Working · ${tools.length} steps' : '${tools.length} steps',
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(fontWeight: FontWeight.w500, color: Afh.text2, fontSize: 13.5),
      );
      if (anyBusy) label = label.animate(onPlay: (c) => c.repeat()).shimmer(duration: 1500.ms, color: Afh.text);
      return InkWell(
        onTap: () {
          open.contains(key) ? open.remove(key) : open.add(key);
          onToggle();
        },
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          child: Row(
            children: [
              SizedBox(
                width: 15,
                height: 15,
                child: anyBusy
                    ? Padding(padding: const EdgeInsets.all(1.5), child: CircularProgressIndicator(strokeWidth: 1.8, color: Afh.accent))
                    : Icon(LucideIcons.layers, size: 15, color: Afh.text3),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Row(
                  children: [
                    Flexible(child: label),
                    if (failed > 0 && !anyBusy) ...[const SizedBox(width: 8), Pill('$failed failed', color: Afh.bad)],
                  ],
                ),
              ),
              const SizedBox(width: 8),
              AnimatedRotation(
                turns: expanded ? 0.25 : 0,
                duration: Afh.fast,
                child: Icon(LucideIcons.chevronRight, size: 15, color: Afh.text3),
              ),
            ],
          ),
        ),
      );
    }

    return Container(
      margin: const EdgeInsets.symmetric(vertical: 5),
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(borderRadius: BorderRadius.circular(12), border: Border.all(color: Afh.line)),
      child: Material(
        type: MaterialType.transparency,
        child: collapsible
            ? Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  header(),
                  AnimatedSize(
                    duration: Afh.med,
                    curve: Afh.ease,
                    alignment: Alignment.topCenter,
                    child: expanded
                        ? Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [Divider(height: 1, color: Afh.line), rows],
                          )
                        : const SizedBox(width: double.infinity),
                  ),
                ],
              )
            : rows,
      ),
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
    final (icon, verb, target, mono) = _toolLook(tool);
    final st = (tool['state'] as Map?) ?? {};
    final status = '${st['status'] ?? 'pending'}';
    final input = st['input'] is Map ? st['input'] as Map : const {};
    final key = 't:${tool['id']}';
    final isOpen = open.contains(key);
    final cmd = _pick(input, ['command', 'cmd', 'code']);
    final err = st['error'];
    final out = err != null ? _toolText(err is Map ? (err['message'] ?? err) : err) : _toolText(st['content']);
    final running = status == 'running' || status == 'pending';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        InkWell(
          onTap: () {
            isOpen ? open.remove(key) : open.add(key);
            onToggle();
          },
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
            child: Row(
              children: [
                Icon(icon, size: 15, color: running ? Afh.text2 : Afh.text3),
                const SizedBox(width: 10),
                ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 150),
                  child: Text(
                    verb,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontWeight: FontWeight.w500, fontSize: 13.5, color: Afh.text),
                  ),
                ),
                const SizedBox(width: 7),
                Expanded(
                  child: Text(
                    target,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: mono
                        ? TextStyle(fontFamily: Afh.mono, fontSize: 12.5, color: Afh.text3)
                        : TextStyle(fontSize: 13.5, color: Afh.text3),
                  ),
                ),
                const SizedBox(width: 8),
                SizedBox(
                  width: 14,
                  height: 14,
                  child: running
                      ? Padding(padding: const EdgeInsets.all(1), child: CircularProgressIndicator(strokeWidth: 1.8, color: Afh.accent))
                      : Icon(
                          status == 'error' ? LucideIcons.circleAlert : LucideIcons.check,
                          size: 14,
                          color: status == 'error' ? Afh.bad : Afh.good,
                        ).animate().fadeIn(duration: 200.ms),
                ),
              ],
            ),
          ),
        ),
        AnimatedSize(
          duration: Afh.med,
          curve: Afh.ease,
          alignment: Alignment.topCenter,
          child: !isOpen
              ? const SizedBox(width: double.infinity)
              : Padding(
                  padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
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
    );
  }
}

/// Monospace text in the theme's code colour: scrolls both ways, with a copy button.
class _Code extends StatefulWidget {
  const _Code(this.text, {this.bad = false, this.diff = false});
  final String text;
  final bool bad, diff;
  @override
  State<_Code> createState() => _CodeState();
}

class _CodeState extends State<_Code> {
  bool _copied = false;

  Future<void> _copy() async {
    await Clipboard.setData(ClipboardData(text: widget.text));
    if (!mounted) return;
    setState(() => _copied = true);
    await Future.delayed(const Duration(milliseconds: 1500));
    if (mounted) setState(() => _copied = false);
  }

  Color _diffColor(String l) {
    if (l.startsWith('+') && !l.startsWith('+++')) return Afh.good;
    if (l.startsWith('-') && !l.startsWith('---')) return Afh.bad;
    if (l.startsWith('@@')) return Afh.text3;
    return Afh.text2;
  }

  @override
  Widget build(BuildContext context) {
    final style = TextStyle(fontFamily: Afh.mono, fontSize: 12.5, height: 1.5, color: Afh.text2);
    return Container(
      width: double.infinity,
      constraints: const BoxConstraints(maxHeight: 320),
      decoration: BoxDecoration(
        color: Afh.p.code,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: widget.bad ? Afh.bad.withValues(alpha: 0.35) : Afh.line),
      ),
      child: Stack(
        children: [
          SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(12, 10, 38, 10),
            child: SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: widget.diff
                  ? Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [for (final l in widget.text.split('\n')) Text(l, style: style.copyWith(color: _diffColor(l)))],
                    )
                  : Text(widget.text, style: style),
            ),
          ),
          Positioned(
            top: 2,
            right: 2,
            child: IconBtn(
              _copied ? LucideIcons.check : LucideIcons.copy,
              tooltip: 'Copy',
              size: 30,
              iconSize: 14,
              color: _copied ? Afh.good : Afh.text3,
              onTap: _copy,
            ),
          ),
        ],
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
    final cmd = md['command'] == null ? null : '${md['command']}';
    final shortCmd = cmd != null && !cmd.contains('\n') && cmd.length <= 120;
    return _Card(
      icon: LucideIcons.shieldCheck,
      title: '${md['title'] ?? r['action'] ?? 'The agent wants to continue'}',
      children: [
        if (cmd != null)
          shortCmd
              ? Text(
                  'wants to run: $cmd',
                  style: TextStyle(fontFamily: Afh.mono, fontSize: 12.5, height: 1.45, color: Afh.text3),
                )
              : _Code(_clip(cmd, 1500)),
        if (files.isNotEmpty)
          ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: 220),
            child: ListView(
              shrinkWrap: true,
              padding: EdgeInsets.zero,
              children: [
                for (final f in files.take(8))
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Pressable(
                        scale: 1,
                        onTap: () => setState(() => _openFile = _openFile == '${f['file']}' ? null : '${f['file']}'),
                        child: Padding(
                          padding: const EdgeInsets.symmetric(vertical: 6),
                          child: Row(
                            children: [
                              _FileStat('${f['status'] ?? 'modified'}'),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(
                                  baseName('${f['file']}'),
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: TextStyle(fontFamily: Afh.mono, fontSize: 12.5, color: Afh.text),
                                ),
                              ),
                              if (f['patch'] != null)
                                AnimatedRotation(
                                  turns: _openFile == '${f['file']}' ? 0.25 : 0,
                                  duration: Afh.fast,
                                  child: Icon(LucideIcons.chevronRight, size: 15, color: Afh.text3),
                                ),
                            ],
                          ),
                        ),
                      ),
                      if (_openFile == '${f['file']}' && f['patch'] != null)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 6),
                          child: _Code(_clip('${f['patch']}', 3000), diff: true),
                        ),
                    ],
                  ),
                if (files.length > 8) Text('+${files.length - 8} more files', style: TextStyle(color: Afh.text3, fontSize: 12.5)),
              ],
            ),
          ),
        if (cmd == null && files.isEmpty && resources.isNotEmpty) _Code(resources.take(8).join('\n')),
        const SizedBox(height: 12),
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: [
            _SmallButton(label: 'Allow', primary: true, busy: _busy == 'once', onTap: _busy == null ? () => _go('once') : null),
            _SmallButton(label: 'Always allow', busy: _busy == 'always', onTap: _busy == null ? () => _go('always') : null),
            _SmallButton(label: 'Deny', busy: _busy == 'reject', onTap: _busy == null ? () => _go('reject') : null),
          ],
        ),
      ],
    );
  }
}

/// + added, − deleted, ~ changed.
class _FileStat extends StatelessWidget {
  const _FileStat(this.status);
  final String status;
  @override
  Widget build(BuildContext context) {
    final (sym, c) = status.startsWith('a')
        ? ('+', Afh.good)
        : status.startsWith('d')
        ? ('−', Afh.bad)
        : ('~', Afh.text2);
    return SizedBox(
      width: 14,
      child: Text(
        sym,
        textAlign: TextAlign.center,
        style: TextStyle(fontFamily: Afh.mono, color: c, fontWeight: FontWeight.w600, fontSize: 13.5),
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

  Widget _option(int i, Map o) {
    final label = '${o['label']}';
    final on = _picks[i].contains(label);
    final multiple = _qs[i]['multiple'] == true;
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Pressable(
        scale: 0.99,
        onTap: () => setState(() {
          if (!multiple) {
            final had = _picks[i].contains(label);
            _picks[i].clear();
            if (!had) _picks[i].add(label);
          } else {
            _picks[i].contains(label) ? _picks[i].remove(label) : _picks[i].add(label);
          }
        }),
        child: AnimatedContainer(
          duration: Afh.fast,
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
          decoration: BoxDecoration(
            color: on ? Afh.tint : Colors.transparent,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: on ? Afh.accent : Afh.line),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.only(top: 1),
                child: Icon(
                  multiple
                      ? (on ? LucideIcons.squareCheck : LucideIcons.square)
                      : (on ? LucideIcons.circleCheck : LucideIcons.circle),
                  size: 17,
                  color: on ? Afh.accent : Afh.text3,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(label, style: TextStyle(fontWeight: FontWeight.w500, fontSize: 14.5, height: 1.3, color: Afh.text)),
                    if (o['description'] != null && '${o['description']}'.isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.only(top: 2),
                        child: Text('${o['description']}', style: TextStyle(color: Afh.text2, fontSize: 13, height: 1.35)),
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return _Card(
      icon: LucideIcons.messageCircleQuestion,
      title: 'AFH has a question',
      sub: _qs.length > 1 ? '${_qs.length} questions' : 'Pick an answer',
      children: [
        ConstrainedBox(
          constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(context).height * 0.42),
          child: ListView(
            shrinkWrap: true,
            padding: EdgeInsets.zero,
            children: [
              for (var i = 0; i < _qs.length; i++) ...[
                if (_qs[i]['header'] != null) Text('${_qs[i]['header']}'.toUpperCase(), style: Afh.label),
                Padding(
                  padding: const EdgeInsets.only(top: 4, bottom: 8),
                  child: Text(
                    '${_qs[i]['question'] ?? ''}',
                    style: TextStyle(fontWeight: FontWeight.w500, fontSize: 15, height: 1.4, color: Afh.text),
                  ),
                ),
                for (final o in (_qs[i]['options'] as List? ?? []).whereType<Map>()) _option(i, o),
                TextField(
                  controller: _others[i],
                  style: TextStyle(fontSize: 14.5, color: Afh.text),
                  decoration: InputDecoration(
                    hintText: 'Or type your own answer',
                    isDense: true,
                    fillColor: Afh.bg,
                    contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: Afh.line)),
                    enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: Afh.line)),
                    focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: Afh.accent)),
                  ),
                ),
                const SizedBox(height: 14),
              ],
            ],
          ),
        ),
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: [
            _SmallButton(label: 'Send answer', primary: true, busy: _busy == 'send', onTap: _busy == null ? () => _go(false) : null),
            _SmallButton(label: 'Skip', busy: _busy == 'skip', onTap: _busy == null ? () => _go(true) : null),
          ],
        ),
      ],
    );
  }
}

/// The flat card approvals and questions sit in, with a "Needs you" label.
class _Card extends StatelessWidget {
  const _Card({required this.icon, required this.title, this.sub, required this.children});
  final IconData icon;
  final String title;
  final String? sub;
  final List<Widget> children;
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Afh.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Afh.line),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(padding: const EdgeInsets.only(top: 1), child: Icon(icon, size: 16, color: Afh.text2)),
              const SizedBox(width: 8),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontWeight: FontWeight.w500, fontSize: 14.5, height: 1.3, color: Afh.text),
                    ),
                    if (sub != null)
                      Padding(
                        padding: const EdgeInsets.only(top: 2),
                        child: Text(sub!, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: Afh.text3, fontSize: 13)),
                      ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              Pill('Needs you', color: Afh.warn),
            ],
          ),
          const SizedBox(height: 10),
          ...children,
        ],
      ),
    ).enter();
  }
}

/// The compact buttons on a card: accent for the main answer, a hairline outline for the rest.
class _SmallButton extends StatelessWidget {
  const _SmallButton({required this.label, required this.busy, this.onTap, this.primary = false});
  final String label;
  final bool busy, primary;
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) {
    final fg = primary ? Afh.onAccent : Afh.text;
    return Pressable(
      onTap: onTap,
      child: AnimatedOpacity(
        duration: Afh.fast,
        opacity: onTap == null && !busy ? 0.5 : 1,
        child: Container(
          height: 32,
          constraints: const BoxConstraints(minWidth: 64),
          padding: const EdgeInsets.symmetric(horizontal: 14),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: primary ? Afh.accent : Colors.transparent,
            borderRadius: BorderRadius.circular(8),
            border: primary ? null : Border.all(color: Afh.line2),
          ),
          child: busy
              ? SizedBox(width: 12, height: 12, child: CircularProgressIndicator(strokeWidth: 1.8, color: fg))
              : Text(
                  label,
                  style: TextStyle(fontSize: 13, fontWeight: primary ? FontWeight.w600 : FontWeight.w500, color: fg),
                ),
        ),
      ),
    );
  }
}
