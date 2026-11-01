// What the app keeps on the phone: provider keys (in the system keychain / keystore), settings, and
// the chats themselves (one JSON file per chat in the app's own folder).
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _secure = FlutterSecureStorage();

String newId() {
  final r = Random.secure();
  return DateTime.now().millisecondsSinceEpoch.toRadixString(36) + List.generate(6, (_) => r.nextInt(36).toRadixString(36)).join();
}

/// Settings and secrets.
class Settings extends ChangeNotifier {
  Settings._();
  static final Settings i = Settings._();

  late SharedPreferences _p;
  final Map<String, String> keys = {}; // provider id → API key
  final Map<String, List<String>> models = {}; // provider id → models fetched with the key
  final Map<String, Map<String, dynamic>> auth = {}; // provider id → sign-in tokens (ChatGPT, Copilot)
  String? relayToken;
  String? relayEmail;

  Future<void> load() async {
    _p = await SharedPreferences.getInstance();
    try {
      final all = await _secure.readAll();
      for (final e in all.entries) {
        if (e.key.startsWith('key.')) keys[e.key.substring(4)] = e.value;
        if (e.key.startsWith('auth.')) auth[e.key.substring(5)] = jsonDecode(e.value) as Map<String, dynamic>;
      }
      relayToken = all['relay.token'];
    } catch (_) {
      // a keystore that can't be read (restored backup on a new phone): start over
      await _secure.deleteAll();
    }
    relayEmail = _p.getString('relay.email');
    final m = _p.getString('models');
    if (m != null) {
      (jsonDecode(m) as Map<String, dynamic>).forEach((k, v) => models[k] = List<String>.from(v as List));
    }
  }

  bool get onboarded => _p.getBool('onboarded') ?? false;
  set onboarded(bool v) {
    _p.setBool('onboarded', v);
    notifyListeners();
  }

  /// "provider/model" picked last, used for new chats.
  String? get lastModel => _p.getString('lastModel');
  set lastModel(String? v) {
    v == null ? _p.remove('lastModel') : _p.setString('lastModel', v);
  }

  String get system => _p.getString('system') ?? '';
  set system(String v) {
    _p.setString('system', v);
    notifyListeners();
  }

  /// Appearance: 'system' | 'dark' | 'light', plus the theme picked for each mode.
  String get themeMode => _p.getString('theme.mode') ?? 'system';
  String get darkTheme => _p.getString('theme.dark') ?? 'sunset';
  String get lightTheme => _p.getString('theme.light') ?? 'paper';
  void setTheme({String? mode, String? dark, String? light}) {
    if (mode != null) _p.setString('theme.mode', mode);
    if (dark != null) _p.setString('theme.dark', dark);
    if (light != null) _p.setString('theme.light', light);
    notifyListeners();
  }

  String? baseUrl(String provider) => _p.getString('base.$provider');
  void setBaseUrl(String provider, String? url) {
    url == null || url.isEmpty ? _p.remove('base.$provider') : _p.setString('base.$provider', url);
    notifyListeners();
  }

  Future<void> setKey(String provider, String? key) async {
    if (key == null || key.isEmpty) {
      keys.remove(provider);
      models.remove(provider);
      await _secure.delete(key: 'key.$provider');
    } else {
      keys[provider] = key;
      await _secure.write(key: 'key.$provider', value: key);
    }
    await _saveModels();
    notifyListeners();
  }

  /// Sign-in tokens; null signs out (and forgets the models it could use).
  Future<void> setAuth(String provider, Map<String, dynamic>? value, {bool quiet = false}) async {
    if (value == null) {
      auth.remove(provider);
      models.remove(provider);
      await _secure.delete(key: 'auth.$provider');
      await _saveModels();
    } else {
      auth[provider] = value;
      await _secure.write(key: 'auth.$provider', value: jsonEncode(value));
    }
    if (!quiet) notifyListeners(); // a token refresh mid-reply needn't rebuild the screen
  }

  /// Whether the model may use tools (web search, location, reminders…).
  bool get tools => _p.getBool('tools') ?? true;
  set tools(bool v) {
    _p.setBool('tools', v);
    notifyListeners();
  }

  /// Things the user asked the assistant to remember, added to every chat.
  List<String> get memory => _p.getStringList('memory') ?? const [];
  set memory(List<String> v) {
    _p.setStringList('memory', v);
    notifyListeners();
  }

  /// Fields a provider's address is built from (Azure resource name, Cloudflare account id…).
  String? param(String provider, String name) => _p.getString('param.$provider.$name');
  void setParam(String provider, String name, String? value) {
    value == null || value.isEmpty ? _p.remove('param.$provider.$name') : _p.setString('param.$provider.$name', value);
  }

  Future<void> setModels(String provider, List<String> list) async {
    models[provider] = list;
    await _saveModels();
    notifyListeners();
  }

  Future<void> _saveModels() => _p.setString('models', jsonEncode(models));

  Future<void> setRelay(String? token, String? email) async {
    relayToken = token;
    relayEmail = email;
    if (token == null) {
      await _secure.delete(key: 'relay.token');
      await _p.remove('relay.email');
    } else {
      await _secure.write(key: 'relay.token', value: token);
      await _p.setString('relay.email', email ?? '');
    }
    notifyListeners();
  }
}

class Msg {
  Msg({required this.role, this.text = '', this.reasoning = '', this.model, DateTime? at, this.error, List<String>? images, List<ToolStep>? steps})
    : at = at ?? DateTime.now(),
      images = images ?? [],
      steps = steps ?? [];
  final String role; // user | assistant
  String text;
  String reasoning;
  String? model;
  DateTime at;
  String? error;
  final List<String> images; // photos sent with a user message: files in the app's own folder
  final List<ToolStep> steps; // what the assistant did on the way to its answer (searched the web…)

  Map<String, dynamic> toJson() => {
    'role': role,
    'text': text,
    if (reasoning.isNotEmpty) 'reasoning': reasoning,
    if (model != null) 'model': model,
    'at': at.millisecondsSinceEpoch,
    if (error != null) 'error': error,
    if (images.isNotEmpty) 'images': images,
    if (steps.isNotEmpty) 'steps': steps.map((s) => s.toJson()).toList(),
  };
  factory Msg.fromJson(Map<String, dynamic> j) => Msg(
    role: j['role'] as String,
    text: j['text'] as String? ?? '',
    reasoning: j['reasoning'] as String? ?? '',
    model: j['model'] as String?,
    at: DateTime.fromMillisecondsSinceEpoch(j['at'] as int? ?? 0),
    error: j['error'] as String?,
    images: List<String>.from(j['images'] as List? ?? const []),
    steps: [for (final s in (j['steps'] as List? ?? const [])) ToolStep.fromJson(Map<String, dynamic>.from(s as Map))],
  );
}

/// One tool the model used while answering.
class ToolStep {
  ToolStep({required this.tool, required this.label, this.detail = '', this.state = 'running'});
  final String tool;
  String label; // "Searched the web for …"
  String detail; // a short summary of what came back
  String state; // running | done | error

  Map<String, dynamic> toJson() => {'tool': tool, 'label': label, if (detail.isNotEmpty) 'detail': detail, 'state': state == 'running' ? 'error' : state};
  factory ToolStep.fromJson(Map<String, dynamic> j) =>
      ToolStep(tool: j['tool'] as String? ?? '', label: j['label'] as String? ?? '', detail: j['detail'] as String? ?? '', state: j['state'] as String? ?? 'done');
}

class Chat {
  Chat({required this.id, this.title = '', required this.provider, required this.model, List<Msg>? messages, DateTime? updated, this.pinned = false})
    : messages = messages ?? [],
      updated = updated ?? DateTime.now();
  final String id;
  String title;
  String provider;
  String model;
  final List<Msg> messages;
  DateTime updated;
  bool pinned;

  String get preview {
    for (final m in messages.reversed) {
      if (m.text.trim().isNotEmpty) return m.text.trim().replaceAll(RegExp(r'\s+'), ' ');
    }
    return '';
  }

  Map<String, dynamic> toJson() => {
    'id': id,
    'title': title,
    'provider': provider,
    'model': model,
    'updated': updated.millisecondsSinceEpoch,
    'pinned': pinned,
    'messages': messages.map((m) => m.toJson()).toList(),
  };
  factory Chat.fromJson(Map<String, dynamic> j) => Chat(
    id: j['id'] as String,
    title: j['title'] as String? ?? '',
    provider: j['provider'] as String? ?? 'openai',
    model: j['model'] as String? ?? '',
    updated: DateTime.fromMillisecondsSinceEpoch(j['updated'] as int? ?? 0),
    pinned: j['pinned'] as bool? ?? false,
    messages: ((j['messages'] as List?) ?? []).map((m) => Msg.fromJson(Map<String, dynamic>.from(m as Map))).toList(),
  );
}

/// Every chat, newest first. Saving is debounced while a reply streams in.
class Chats extends ChangeNotifier {
  Chats._();
  static final Chats i = Chats._();

  final List<Chat> all = [];
  late Directory _dir;
  final Map<String, Timer> _pending = {};

  Future<void> load() async {
    _dir = Directory('${(await getApplicationSupportDirectory()).path}/chats');
    await _dir.create(recursive: true);
    for (final f in _dir.listSync().whereType<File>().where((f) => f.path.endsWith('.json'))) {
      try {
        all.add(Chat.fromJson(jsonDecode(await f.readAsString()) as Map<String, dynamic>));
      } catch (_) {
        /* a half-written file: skip it */
      }
    }
    _sort();
  }

  /// Copies a picked photo into the app's own folder so the chat keeps it.
  Future<String> keepImage(String from) async {
    final dir = Directory('${_dir.path}/images');
    await dir.create(recursive: true);
    final ext = from.contains('.') ? from.split('.').last.toLowerCase() : 'jpg';
    return (await File(from).copy('${dir.path}/${newId()}.${ext.length > 4 ? 'jpg' : ext}')).path;
  }

  void _sort() => all.sort((a, b) => a.pinned != b.pinned ? (a.pinned ? -1 : 1) : b.updated.compareTo(a.updated));

  Chat create(String provider, String model) {
    final c = Chat(id: newId(), provider: provider, model: model);
    return c;
  }

  /// Stores the chat (adding it to the list the first time) and tells the list to redraw.
  void save(Chat c, {bool now = false}) {
    if (!all.contains(c)) all.add(c);
    _sort();
    notifyListeners();
    _pending[c.id]?.cancel();
    void write() {
      _pending.remove(c.id);
      final f = File('${_dir.path}/${c.id}.json');
      final tmp = File('${f.path}.tmp');
      tmp.writeAsStringSync(jsonEncode(c.toJson()));
      tmp.renameSync(f.path);
    }

    if (now) {
      write();
    } else {
      _pending[c.id] = Timer(const Duration(milliseconds: 600), write);
    }
  }

  void delete(Chat c) {
    all.remove(c);
    _pending.remove(c.id)?.cancel();
    final f = File('${_dir.path}/${c.id}.json');
    if (f.existsSync()) f.deleteSync();
    for (final m in c.messages) {
      for (final img in m.images) {
        try {
          File(img).deleteSync();
        } catch (_) {}
      }
    }
    notifyListeners();
  }

  /// Puts a chat back after an undo.
  void restore(Chat c) => save(c, now: true);

  void deleteAll() {
    for (final c in [...all]) {
      delete(c);
    }
  }

  void flush() {
    for (final e in [..._pending.entries]) {
      e.value.cancel();
      final c = all.firstWhere(
        (x) => x.id == e.key,
        orElse: () => Chat(id: '', provider: '', model: ''),
      );
      if (c.id.isNotEmpty) save(c, now: true);
    }
  }
}

void debugLog(Object o) {
  if (kDebugMode) debugPrint('$o');
}
