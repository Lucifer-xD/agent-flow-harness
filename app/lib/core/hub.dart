// Everything the app knows about each computer, kept live. A Hub holds one event stream per computer
// and shares it with every screen: the list of threads, what is waiting for the user, and the open
// threads themselves, which stay in memory so going back to one is instant.
import 'dart:async';

import 'package:flutter/foundation.dart';

import 'l10n.dart';
import 'native.dart';
import 'relay.dart';
import 'store.dart';

class Hubs extends ChangeNotifier {
  Hubs._() {
    Account.i.addListener(_sync);
  }
  static final Hubs i = Hubs._();

  final Map<String, Hub> all = {};
  bool _paused = false;

  void _sync() {
    final online = {for (final c in Account.i.computers.where((c) => c.online)) c.id: c};
    for (final id in [...all.keys]) {
      if (!Account.i.computers.any((c) => c.id == id)) all.remove(id)?.close();
    }
    for (final c in online.values) {
      final had = all[c.id];
      if (had == null) {
        all[c.id] = Hub(c)..addListener(notifyListeners);
        if (!_paused) all[c.id]!.open();
      } else if (!_paused && !had.open_) {
        had.open();
      }
    }
    notifyListeners();
  }

  /// The app went to the background: connections rest, except to a computer that is working on something
  /// (Android keeps that one open with a notification, the iPhone for as long as it lets the app live).
  void pause() {
    _paused = true;
    for (final h in all.values) {
      if (Notify.keepsLine && h.sessions.any((s) => s['running'] == true)) continue;
      h.rest();
    }
  }

  Future<void> resume() async {
    _paused = false;
    for (final h in all.values) {
      if (h.open_) {
        unawaited(h.load());
      } else {
        h.open();
      }
    }
    await Account.i.refresh();
  }

  Iterable<Hub> get online => all.values.where((h) => h.state != 'offline');
  Hub? of(String id) => all[id];

  /// Open questions and approvals, oldest first.
  List<Ask> get asks {
    final out = [for (final h in all.values) ...h.asks.values];
    out.sort((a, b) => a.at.compareTo(b.at));
    return out;
  }

  List<(Hub, J)> threads({bool running = false, bool archived = false}) {
    final out = [
      for (final h in all.values)
        for (final s in h.sessions)
          if (!running || s['running'] == true) (h, s),
    ];
    out.sort((a, b) => updatedOf(b.$2).compareTo(updatedOf(a.$2)));
    return out;
  }

  bool get busy => all.values.any((h) => h.sessions.any((s) => s['running'] == true));
}

DateTime updatedOf(J s) => DateTime.fromMillisecondsSinceEpoch(((asMap(s['time'])['updated'] ?? asMap(s['time'])['created'] ?? 0) as num).toInt());
String dirOf(J s) => '${asMap(s['location'])['directory'] ?? s['directory'] ?? ''}';
List<J> todosOf(J s) => asList(asMap(asMap(s['metadata'])['afh'])['todos']);
String modeOf(J s) => '${asMap(asMap(s['metadata'])['afh'])['mode'] ?? 'ask'}';

/// Something waiting for the user: an approval, a question, or design options.
/// What a thread is called; before it has a name, the project it works in.
String threadName(J? s) {
  final t_ = '${s?['title'] ?? ''}'.trim();
  if (t_.isNotEmpty) return t_;
  final d = s == null ? '' : baseName(dirOf(s));
  return d.isEmpty ? t('Thread') : d;
}

class Ask {
  Ask(this.hub, this.data) : at = DateTime.now();
  final Hub hub;
  final J data;
  final DateTime at;
  String get id => '${data['id']}';
  String get sid => '${data['sessionID']}';
  String get action => '${data['action']}';
  J get meta => asMap(data['metadata']);
  bool get isQuestion => action == 'question';
  bool get isDesign => action == 'design';
  List<String> get resources => [for (final r in (data['resources'] as List? ?? const [])) '$r'];
  String get thread => threadName(hub.session(sid));

  Future<void> reply(String decision, {String? message, List<J>? answers}) async {
    hub.asks.remove(id);
    hub.poke();
    try {
      await hub.pc.post('/api/sessions/$sid/permissions/$id', {'decision': decision, 'message': ?message, 'answers': ?answers});
    } catch (e) {
      hub.asks[id] = this;
      hub.poke();
      rethrow;
    }
  }
}

class Hub extends ChangeNotifier {
  Hub(this.computer) : pc = Pc(computer);
  final Computer computer;
  final Pc pc;

  String state = 'connecting'; // connecting | live | reconnecting | offline
  bool loaded = false;
  String? error;
  List<J> sessions = [];
  List<J> models = [];
  List<J> agents = [];
  Map<String, String> providerNames = {};
  J settings = {};
  J? defaultModel;
  String version = '';
  final Map<String, Ask> asks = {};
  final Map<String, String> now = {}; // thread → what it is doing this second
  final Map<String, ThreadStore> _threads = {};
  StreamSubscription<J>? _sub;
  Timer? _later;
  bool _first = true;
  int _tries = 0;

  bool get open_ => _sub != null;
  List<String> get projects => [for (final p in (settings['projects'] as List? ?? const [])) '$p'];
  J? session(String sid) => sessions.where((s) => s['id'] == sid).firstOrNull ?? _threads[sid]?.session;
  void poke() => notifyListeners();

  void open() {
    _sub?.cancel();
    var fresh = true; // whatever happened while the line was closed
    _sub = pc
        .events(
          onState: (s) {
            final was = state;
            if (s == 'gone') {
              state = 'offline';
            } else if (s == 'live') {
              state = 'live';
              if (was != 'live' || fresh) load();
              fresh = false;
            } else {
              state = s;
            }
            notifyListeners();
          },
        )
        .listen(_on);
    load();
  }

  void rest() {
    _sub?.cancel();
    _sub = null;
  }

  void close() {
    rest();
    _later?.cancel();
    for (final t in _threads.values) {
      t.dispose();
    }
    _threads.clear();
  }

  Future<void> load() async {
    try {
      final got = await Future.wait([pc.get('/api/sessions?limit=120'), if (_first || models.isEmpty) pc.get('/api/bootstrap')]);
      sessions = asList(got[0]);
      if (got.length > 1) _boot(asMap(got[1]));
      _first = false;
      loaded = true;
      error = null;
      if (state == 'connecting' || state == 'offline') state = 'live';
      notifyListeners();
      // what was already waiting when we connected
      final live = <String, Ask>{};
      for (final s in sessions.where((s) => s['running'] == true)) {
        try {
          for (final p in asList(await pc.get('/api/sessions/${s['id']}/permissions'))) {
            live['${p['id']}'] = asks['${p['id']}'] ?? Ask(this, p);
          }
        } on ApiError catch (e) {
          if (e.offline) rethrow; // deleted meanwhile otherwise
        }
      }
      asks
        ..clear()
        ..addAll(live);
      for (final t in _threads.values) {
        unawaited(t.load());
      }
      _tries = 0;
    } on ApiError catch (e) {
      error = e.message;
      if (e.offline) state = 'offline';
      // the line can be back before the computer answers
      if (open_ && _tries++ < 3) Timer(const Duration(seconds: 3), () => open_ ? load() : null);
    }
    Notify.working();
    notifyListeners();
  }

  void _boot(J b) {
    version = '${b['version'] ?? ''}';
    if (version.isNotEmpty) computer.version = version;
    settings = asMap(b['settings']);
    models = asList(b['models'] ?? asMap(b['models'])['models']);
    agents = asList(b['agents']);
    if (models.isEmpty) models = asList(asMap(b['models'])['models']);
    defaultModel = b['defaultModel'] is Map ? asMap(b['defaultModel']) : (settings['defaultModel'] is Map ? asMap(settings['defaultModel']) : null);
    final names = asMap(b['providerNames']);
    providerNames = {for (final e in names.entries) e.key: '${e.value}'};
  }

  Future<void> reloadModels() async {
    final m = asMap(await pc.get('/api/models'));
    models = asList(m['models']);
    providerNames = {for (final e in asMap(m['providerNames']).entries) e.key: '${e.value}'};
    if (m['defaultModel'] is Map) defaultModel = asMap(m['defaultModel']);
    notifyListeners();
  }

  Future<void> reloadSettings() async {
    settings = asMap(await pc.get('/api/settings'));
    notifyListeners();
  }

  /// Models worth offering: switched on, not hidden.
  List<J> get usable => [
    for (final m in models)
      if (m['hidden'] != true && m['enabled'] != false) m,
  ];
  J? model(Object? ref) {
    final r = asMap(ref);
    return models.where((m) => m['id'] == r['id'] && m['providerID'] == r['providerID']).firstOrNull;
  }

  String modelName(Object? ref) => '${model(ref)?['name'] ?? asMap(ref)['id'] ?? ''}';

  ThreadStore thread(String sid) => _threads.putIfAbsent(sid, () => ThreadStore(this, sid));

  Future<J> create({required String dir, J? model, String? agent, String? mode, bool worktree = false, String? title}) async {
    final s = asMap(
      await pc.post('/api/sessions', {'directory': dir, 'model': ?model, 'agent': ?agent, 'mode': ?mode, if (worktree) 'worktree': true, 'title': ?title}),
    );
    sessions.insert(0, s);
    thread('${s['id']}').session = s;
    notifyListeners();
    return s;
  }

  Future<void> change(String sid, J fields) async {
    final s = session(sid);
    s?.addAll({if (fields.containsKey('title')) 'title': fields['title']});
    notifyListeners();
    await pc.patch('/api/sessions/$sid', fields);
    if (fields['archived'] != null) sessions.removeWhere((s) => s['id'] == sid);
    notifyListeners();
  }

  Future<void> remove(String sid) async {
    sessions.removeWhere((s) => s['id'] == sid);
    notifyListeners();
    await pc.delete('/api/sessions/$sid');
    _threads.remove(sid);
  }

  Future<void> stop(String sid) => pc.post('/api/sessions/$sid/interrupt');

  void _reloadSoon() {
    _later ??= Timer(const Duration(milliseconds: 500), () async {
      _later = null;
      try {
        sessions = asList(await pc.get('/api/sessions?limit=120'));
        notifyListeners();
        Notify.working();
      } catch (_) {}
    });
  }

  void _on(J ev) {
    final type = '${ev['type']}';
    final d = asMap(ev['data']);
    final sid = '${d['sessionID'] ?? ''}';
    _threads[sid]?.on(type, d);
    final s = sid.isEmpty ? null : sessions.where((x) => x['id'] == sid).firstOrNull;
    switch (type) {
      case 'session.execution.started':
        s?['running'] = true;
        now[sid] = 'Thinking';
        if (s == null) _reloadSoon();
        Notify.working();
      case 'session.execution.succeeded' || 'session.execution.failed' || 'session.execution.interrupted':
        if (s != null) {
          s['running'] = false;
          s['waiting'] = false;
          s['failed'] = type.endsWith('failed');
        }
        now.remove(sid);
        asks.removeWhere((_, a) => a.sid == sid);
        if (s != null && asMap(s)['parentID'] == null && !type.endsWith('interrupted')) {
          final failed = type.endsWith('failed'), why = '${asMap(d['error'])['message'] ?? ''}';
          // a first run is named right after it ends
          Timer(Duration(milliseconds: '${s['title'] ?? ''}'.isEmpty ? 2600 : 0), () => Notify.finished(this, session(sid) ?? s, failed: failed, error: why));
        }
        Notify.working();
        _reloadSoon();
      case 'session.tool.called':
        now[sid] = stepLabel('${d['name'] ?? _threads[sid]?.toolName('${d['id']}') ?? _names['${d['id']}'] ?? ''}', asMap(d['input']), live: true, root: s == null ? null : dirOf(s));
        _names.remove('${d['id']}');
      case 'session.tool.input.started':
        _names['${d['id']}'] = '${d['name']}';
        return;
      case 'session.text.started':
        now[sid] = 'Writing';
      case 'session.reasoning.started':
        now[sid] = 'Thinking';
      case 'session.text.delta' || 'session.reasoning.delta' || 'session.tool.progress' || 'session.tool.input.delta':
        return;
      case 'session.todos.updated':
        if (s != null) {
          final meta = asMap(s['metadata']);
          meta['afh'] = {...asMap(meta['afh']), 'todos': d['todos'] ?? asMap(asMap(meta['afh']))['todos']};
          s['metadata'] = meta;
        }
      case 'permission.asked':
        final a = Ask(this, d);
        asks[a.id] = a;
        s?['waiting'] = true;
        now[sid] = a.isQuestion ? 'Has a question' : a.isDesign ? 'Has designs to show' : 'Waiting for you';
        // a thread gets its name when it first asks: wait for it
        '${s?['title'] ?? ''}'.isEmpty ? Timer(const Duration(milliseconds: 2500), () => asks.containsKey(a.id) ? Notify.ask(a) : null) : Notify.ask(a);
      case 'permission.replied':
        final id = '${d['id'] ?? d['requestID']}';
        asks.remove(id);
        s?['waiting'] = asks.values.any((a) => a.sid == sid);
        Notify.gone(id);
      case 'session.renamed':
        s?['title'] = d['title'];
      case 'session.created' || 'session.updated' || 'session.archived' || 'session.unarchived' || 'session.deleted':
        _reloadSoon();
        return;
      case 'model.updated':
        unawaited(reloadModels().catchError((_) {}));
        return;
      case 'afh.ready':
        load();
        return;
      case 'afh.restarting':
        state = 'reconnecting';
      case 'session.tool.success' || 'session.tool.failed':
        break;
      default:
        return;
    }
    notifyListeners();
  }

  final Map<String, String> _names = {};
}

/// A message of a thread. Each one tells only its own widgets when it changes.
class TMsg extends ChangeNotifier {
  TMsg(this.d);
  J d;
  bool live = false;
  String get id => '${d['id']}';
  String get type => '${d['type']}';
  List<J> get parts {
    final c = d['content'];
    if (c is List<J>) return c;
    final l = asList(c);
    d['content'] = l;
    return l;
  }

  void ping() => notifyListeners();
}

/// One thread, live.
class ThreadStore extends ChangeNotifier {
  ThreadStore(this.hub, this.sid) : session = asMap(hub.sessions.where((s) => s['id'] == sid).firstOrNull);
  final Hub hub;
  final String sid;
  Pc get pc => hub.pc;

  J session;
  List<TMsg> msgs = [];
  bool loaded = false, running = false;
  String? error, runError;
  List<J> todos = [], jobs = [], children = [];
  J? goal;
  List<J>? diff; // null: not read yet
  J? usage;
  DateTime? startedAt;
  final List<(String, List<Att2>)> sending = []; // on their way to the computer
  Timer? _soon, _redraw, _diffSoon;
  final Set<TMsg> _dirty = {};
  bool _dead = false;

  String get dir => dirOf(session);
  String get title => '${session['title'] ?? ''}'.isEmpty ? 'New thread' : '${session['title']}';
  Iterable<Ask> get asks => hub.asks.values.where((a) => a.sid == sid);
  String? toolName(String id) {
    for (final m in msgs.reversed.take(2)) {
      for (final p in m.parts) {
        if (p['id'] == id) return '${p['name']}';
      }
    }
    return null;
  }

  @override
  void dispose() {
    _dead = true;
    _soon?.cancel();
    _redraw?.cancel();
    _diffSoon?.cancel();
    super.dispose();
  }

  Future<void> load() async {
    try {
      final got = await Future.wait([pc.get('/api/sessions/$sid'), pc.get('/api/sessions/$sid/messages'), pc.get('/api/sessions/$sid/permissions')]);
      if (_dead) return;
      session = asMap(got[0]);
      running = session['running'] == true;
      todos = todosOf(session);
      final old = {for (final m in msgs) m.id: m};
      msgs = [
        for (final m in asList(got[1]))
          if (old['${m['id']}'] case final TMsg t) (t..d = m..live = false) else TMsg(m),
      ];
      if (running && msgs.isNotEmpty && msgs.last.type == 'assistant' && asMap(msgs.last.d['time'])['completed'] == null) msgs.last.live = true;
      if (running) startedAt ??= DateTime.now();
      for (final p in asList(got[2])) {
        hub.asks.putIfAbsent('${p['id']}', () => Ask(hub, p));
      }
      loaded = true;
      error = null;
      for (final m in msgs) {
        m.ping();
      }
      notifyListeners();
      unawaited(_extras());
    } on ApiError catch (e) {
      if (_dead) return;
      error = e.message;
      notifyListeners();
    }
  }

  Future<void> _extras() async {
    Future<dynamic> tryGet(String p) => pc.get(p).then<dynamic>((v) => v, onError: (_) => null);
    final got = await Future.wait([
      tryGet('/api/sessions/$sid/goal'),
      tryGet('/api/sessions/$sid/jobs'),
      tryGet('/api/sessions/$sid/children'),
      tryGet('/api/sessions/$sid/diff'),
      tryGet('/api/sessions/$sid/usage'),
    ]);
    if (_dead) return;
    goal = got[0] is Map ? asMap(got[0]) : null;
    jobs = asList(got[1]);
    children = asList(got[2]);
    diff = asList(got[3]);
    usage = got[4] is Map ? asMap(got[4]) : null;
    notifyListeners();
  }

  void _loadSoon([int ms = 250]) {
    _soon?.cancel();
    _soon = Timer(Duration(milliseconds: ms), load);
  }

  void _diffLater() {
    _diffSoon ??= Timer(const Duration(milliseconds: 900), () async {
      _diffSoon = null;
      try {
        diff = asList(await pc.get('/api/sessions/$sid/diff'));
        if (!_dead) notifyListeners();
      } catch (_) {}
    });
  }

  /// Text arrives in many small pieces: redraw the message at most ~30 times a second.
  void _touch(TMsg m) {
    _dirty.add(m);
    _redraw ??= Timer(const Duration(milliseconds: 33), () {
      _redraw = null;
      for (final m in [..._dirty]) {
        m.ping();
      }
      _dirty.clear();
    });
  }

  TMsg _asst(String? id, [J? d]) {
    final had = msgs.reversed.where((m) => m.id == id).firstOrNull;
    if (had != null) return had;
    final m = TMsg({
      'id': id,
      'type': 'assistant',
      'content': <J>[],
      'time': {'created': DateTime.now().millisecondsSinceEpoch},
      if (d != null) 'model': d['model'],
      if (d != null) 'agent': d['agent'],
    })..live = true;
    msgs.add(m);
    notifyListeners();
    return m;
  }

  J _part(TMsg m, String type, Object? ordinal) {
    final c = m.parts;
    for (final p in c) {
      if (p['type'] == type && p['ordinal'] == ordinal) return p;
    }
    final p = <String, dynamic>{'type': type, 'ordinal': ordinal, 'text': '', 'live': true, 'since': DateTime.now().millisecondsSinceEpoch};
    c.add(p);
    return p;
  }

  J _tool(TMsg m, String? id, [String? name]) {
    final c = m.parts;
    for (final p in c) {
      if (p['type'] == 'tool' && p['id'] == id) return p;
    }
    final p = <String, dynamic>{
      'type': 'tool',
      'id': id,
      'name': name ?? '',
      'state': <String, dynamic>{'status': 'pending', 'input': <String, dynamic>{}},
    };
    c.add(p);
    return p;
  }

  void on(String t, J d) {
    final aid = d['assistantMessageID'] as String?;
    switch (t) {
      case 'session.execution.started':
        running = true;
        runError = null;
        startedAt = DateTime.now();
      case 'session.execution.succeeded' || 'session.execution.interrupted' || 'session.execution.failed':
        running = false;
        startedAt = null;
        if (t.endsWith('failed')) runError = '${asMap(d['error'])['message'] ?? 'The run failed'}';
        for (final m in msgs) {
          if (m.live) {
            m.live = false;
            for (final p in m.parts) {
              p['live'] = false;
            }
            m.ping();
          }
        }
        _loadSoon(300);
      case 'session.inbox.enqueued':
        final p = asMap(asMap(d['item'])['payload']);
        if (!msgs.any((m) => m.id == d['inboxID'])) {
          sending.removeWhere((s) => s.$1 == p['text']);
          msgs.add(
            TMsg({
              'id': d['inboxID'],
              'type': 'user',
              'text': p['text'],
              'files': p['files'],
              'waiting': running,
              'time': {'created': DateTime.now().millisecondsSinceEpoch},
            }),
          );
        }
      case 'session.inbox.delivered' || 'session.notice' || 'session.compaction.ended' || 'session.updated' || 'session.revert.committed' || 'session.revert.cleared':
        _loadSoon();
        return;
      case 'session.renamed':
        session['title'] = d['title'];
      case 'session.step.started':
        for (final m in msgs) {
          if (m.live) {
            m.live = false;
            m.ping();
          }
        }
        _asst(aid, d).live = true;
      case 'session.step.failed':
        final err = asMap(d['error']);
        if (!RegExp('interrupt|abort|cancel', caseSensitive: false).hasMatch('${err['type'] ?? ''} ${err['message'] ?? ''}')) {
          _touch(_asst(aid)..d['error'] = err['message']);
        }
        return;
      case 'session.text.started' || 'session.reasoning.started':
        final m = _asst(aid);
        _part(m, t.contains('reasoning') ? 'reasoning' : 'text', d['ordinal']);
        _touch(m);
        return;
      case 'session.text.delta' || 'session.reasoning.delta':
        final m = _asst(aid);
        final p = _part(m, t.contains('reasoning') ? 'reasoning' : 'text', d['ordinal']);
        p['text'] = '${p['text']}${d['delta'] ?? ''}';
        _touch(m);
        return;
      case 'session.text.ended' || 'session.reasoning.ended':
        final m = _asst(aid);
        final p = _part(m, t.contains('reasoning') ? 'reasoning' : 'text', d['ordinal']);
        if (d['text'] != null) p['text'] = d['text'];
        p['live'] = false;
        p['took'] = DateTime.now().millisecondsSinceEpoch - ((p['since'] as num?)?.toInt() ?? DateTime.now().millisecondsSinceEpoch);
        _touch(m);
        return;
      case 'session.tool.input.started':
        final m = _asst(aid);
        _tool(m, d['id'] as String?, d['name'] as String?);
        _touch(m);
        return;
      case 'session.tool.called':
        final m = _asst(aid);
        final p = _tool(m, d['id'] as String?, d['name'] as String?);
        p['name'] = d['name'] ?? p['name'];
        p['state'] = <String, dynamic>{'status': 'running', 'input': d['input'] ?? <String, dynamic>{}};
        _touch(m);
        return;
      case 'session.tool.progress':
        final m = _asst(aid);
        final p = _tool(m, d['id'] as String?);
        final st = asMap(p['state']);
        st['content'] = d['content'];
        st['metadata'] = {...asMap(st['metadata']), ...asMap(d['metadata'])};
        p['state'] = st;
        _touch(m);
        return;
      case 'session.tool.success' || 'session.tool.failed':
        final m = _asst(aid);
        final p = _tool(m, d['id'] as String?);
        final input = asMap(p['state'])['input'];
        p['state'] = t.endsWith('success')
            ? <String, dynamic>{'status': 'completed', 'input': input, 'content': d['content'], 'metadata': d['metadata']}
            : <String, dynamic>{'status': 'error', 'input': input, 'error': d['error'], 'content': d['content'], 'metadata': d['metadata']};
        if (RegExp('edit|write|patch|shell').hasMatch('${p['name']}')) _diffLater();
        if ('${p['name']}' == 'subagent' || '${p['name']}' == 'delegate') unawaited(_extras());
        _touch(m);
        return;
      case 'session.todos.updated':
        todos = asList(d['todos']);
      case 'session.goal.updated':
        goal = d['goal'] is Map ? asMap(d['goal']) : goal;
        unawaited(_extras());
      case 'session.jobs.updated':
        unawaited(_extras());
        return;
      case 'permission.asked' || 'permission.replied':
        break;
      default:
        return;
    }
    if (!_dead) notifyListeners();
  }

  /// A message that couldn't go: say so, and keep the words for another try.
  void fail(String e, [String text = '']) {
    runError = e;
    if (text.isNotEmpty) Settings.i.put('draft.$sid', text, quiet: true);
    if (!_dead) notifyListeners();
  }

  /// Sends a message (while the thread runs it becomes a note the agent reads at its next step).
  Future<void> send(String text, {List<Att2> files = const [], J? model, String? agent}) async {
    final ticket = (text, files);
    sending.add(ticket);
    notifyListeners();
    try {
      final paths = <String>[];
      for (final f in files) {
        paths.add(f.remotePath ?? (f.remotePath = await pc.upload(f.name, await f.read(), f.mime)));
      }
      await pc.post('/api/sessions/$sid/prompt', {'text': text, if (paths.isNotEmpty) 'files': paths, 'model': ?model, 'agent': ?agent});
      sending.remove(ticket);
      hub.sessions.where((s) => s['id'] == sid).firstOrNull?['running'] = true;
      Notify.working();
      notifyListeners();
      _loadSoon(400);
    } catch (_) {
      sending.remove(ticket);
      notifyListeners();
      rethrow;
    }
  }
}

/// A file on its way to a computer.
class Att2 {
  Att2(this.name, this.mime, this.read, {this.local});
  final String name, mime;
  final Future<Uint8List> Function() read;
  final String? local; // the phone's own copy, for the preview
  String? remotePath;
}

/// What a step does, in a few words: "Read pricing.py", "Ran the tests".
String stepLabel(String tool, J input, {bool live = false, String? root}) {
  String s(String k) => '${input[k] ?? ''}'.trim();
  final path = s('path').isNotEmpty ? s('path') : (s('file').isNotEmpty ? s('file') : s('filePath'));
  final file = path.isEmpty ? '' : baseName(path);
  String v(String now, String past) => t(live ? now : past);
  String cut(String t, [int n = 70]) => t.length > n ? '${t.substring(0, n - 1)}…' : t;
  switch (tool) {
    case 'shell' || 'bash':
      final what = s('description');
      return what.isNotEmpty ? cut(what) : '${v('Running', 'Ran')} ${cut(s('command').split('\n').first, 50)}';
    case 'read':
      return '${v('Reading', 'Read')} $file';
    case 'write':
      return '${v('Writing', 'Wrote')} $file';
    case 'edit' || 'multiedit' || 'patch':
      return file.isEmpty ? v('Editing files', 'Edited files') : '${v('Editing', 'Edited')} $file';
    case 'glob':
      return '${v('Looking for', 'Looked for')} ${cut(s('pattern'), 40)}';
    case 'grep':
      return '${v('Searching for', 'Searched for')} ${cut(s('pattern'), 40)}';
    case 'list' || 'ls':
      return '${v('Looking in', 'Looked in')} ${file.isEmpty ? t('the project') : file}';
    case 'todo' || 'todowrite':
      return v('Updating the plan', 'Updated the plan');
    case 'websearch' || 'web_search':
      return '${v('Searching the web for', 'Searched the web for')} ${cut(s('query'), 50)}';
    case 'webfetch' || 'web_fetch' || 'fetch':
      return '${v('Opening', 'Opened')} ${Uri.tryParse(s('url'))?.host ?? cut(s('url'), 40)}';
    case 'subagent' || 'delegate' || 'task':
      final role = s('role').isEmpty ? s('agent') : s('role');
      return '${role.isEmpty ? 'Subagent' : role[0].toUpperCase() + role.substring(1)}: ${cut(s('description'), 50)}';
    case 'question':
      return v('Asking you', 'Asked you');
    case 'design':
      return v('Showing designs', 'Showed designs');
    case 'browser':
      return '${v('Using the browser', 'Used the browser')}${s('url').isEmpty ? '' : ': ${Uri.tryParse(s('url'))?.host ?? ''}'}';
    case 'computer':
      return v('Using the computer', 'Used the computer');
    case 'chrome':
      return v('Using Chrome', 'Used Chrome');
    case 'threads':
      return v('Reading your threads', 'Read your threads');
    case 'skill':
      return '${v('Using the skill', 'Used the skill')} ${s('name')}';
    case 'memory' || 'remember':
      return v('Updating the memory', 'Updated the memory');
    case 'goal':
      return v('Checking the goal', 'Checked the goal');
    case '':
      return v('Working', 'Step');
  }
  final nice = tool.replaceAll(RegExp(r'[_\-.]+'), ' ').trim();
  return nice.isEmpty ? 'Step' : nice[0].toUpperCase() + nice.substring(1);
}
