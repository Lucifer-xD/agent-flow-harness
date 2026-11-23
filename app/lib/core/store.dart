// What the app keeps on the phone: provider keys (in the system keychain / keystore), settings, and
// the chats themselves (one JSON file per chat, plus their photos and files, in the app's own folder).
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:ui' as ui;

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

  // ---- appearance ----
  String get themeMode => _p.getString('look.mode') ?? _p.getString('theme.mode') ?? 'system'; // system | dark | light
  String get accent => _p.getString('look.accent') ?? 'ember';
  bool get black => _p.getBool('look.black') ?? false; // pure black on OLED
  double get textScale => _p.getDouble('look.text') ?? 1;
  bool get haptics => _p.getBool('look.haptics') ?? true;
  bool get calm => _p.getBool('look.calm') ?? false; // fewer animations
  String get language => _p.getString('language') ?? 'system'; // system | en | ar

  // ---- plain preferences ----
  bool flag(String key, [bool fallback = false]) => _p.getBool(key) ?? fallback;
  String str(String key, [String fallback = '']) => _p.getString(key) ?? fallback;
  double dbl(String key, double fallback) => _p.getDouble(key) ?? fallback;
  List<String> strings(String key) => _p.getStringList(key) ?? const [];

  /// Saves a preference (bool, String, double or a list of strings; null removes it) and redraws.
  void put(String key, Object? v, {bool quiet = false}) {
    switch (v) {
      case null:
        _p.remove(key);
      case bool b:
        _p.setBool(key, b);
      case String s:
        _p.setString(key, s);
      case double d:
        _p.setDouble(key, d);
      case List<String> l:
        _p.setStringList(key, l);
    }
    if (!quiet) notifyListeners();
  }

  List<Assistant> get assistants {
    final raw = _p.getString('assistants');
    if (raw == null) return const [];
    try {
      return [for (final a in jsonDecode(raw) as List) Assistant.fromJson(Map<String, dynamic>.from(a as Map))];
    } catch (_) {
      return const [];
    }
  }

  set assistants(List<Assistant> v) {
    _p.setString('assistants', jsonEncode([for (final a in v) a.toJson()]));
    notifyListeners();
  }

  Assistant? assistant(String? id) => id == null ? null : assistants.where((a) => a.id == id).firstOrNull;

  // ---- providers ----
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
  set tools(bool v) => put('tools', v);

  /// Things the user asked the assistant to remember, added to every chat.
  List<String> get memory => _p.getStringList('memory') ?? const [];
  set memory(List<String> v) => put('memory', v);

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

/// A persona for chats: its own instructions, and optionally its own model.
class Assistant {
  Assistant({required this.id, this.name = '', this.system = '', this.model, this.icon = 'sparkles'});
  final String id;
  String name, system, icon;
  String? model; // "provider/model"
  Map<String, dynamic> toJson() => {'id': id, 'name': name, 'system': system, 'icon': icon, 'model': ?model};
  factory Assistant.fromJson(Map<String, dynamic> j) => Assistant(
    id: j['id'] as String,
    name: j['name'] as String? ?? '',
    system: j['system'] as String? ?? '',
    icon: j['icon'] as String? ?? 'sparkles',
    model: j['model'] as String?,
  );
}

/// A photo or file that goes with a message. [name] is the file's name inside the app's own media folder
/// (a name, not a path: iOS moves the folder when the app updates).
class Att {
  Att({required this.name, required this.label, this.mime = 'application/octet-stream', this.size = 0, this.text});
  final String name, label, mime;
  final int size;
  final String? text; // a text file's contents, sent as text
  bool get isImage => mime.startsWith('image/');
  bool get isPdf => mime == 'application/pdf';
  File get file => Media.file(name);
  Map<String, dynamic> toJson() => {'name': name, 'label': label, 'mime': mime, 'size': size, 'text': ?text};
  factory Att.fromJson(Map<String, dynamic> j) => Att(
    name: j['name'] as String? ?? '',
    label: j['label'] as String? ?? '',
    mime: j['mime'] as String? ?? 'application/octet-stream',
    size: (j['size'] as num?)?.toInt() ?? 0,
    text: j['text'] as String?,
  );
}

const _mimes = {
  'jpg': 'image/jpeg',
  'jpeg': 'image/jpeg',
  'png': 'image/png',
  'webp': 'image/webp',
  'gif': 'image/gif',
  'heic': 'image/heic',
  'heif': 'image/heic',
  'pdf': 'application/pdf',
  'zip': 'application/zip',
  'mp4': 'video/mp4',
  'mp3': 'audio/mpeg',
  'm4a': 'audio/mp4',
};
final _textTypes =
    'txt md csv tsv json yaml yml xml html css js ts tsx jsx py dart java kt swift c h cpp cs go rs rb php sh ps1 sql toml ini log gradle vue svelte srt lua r'
        .split(' ')
        .toSet();

/// Photos and files kept with chats, in one folder of the app.
class Media {
  static late Directory dir;
  static Future<void> load() async {
    dir = Directory('${(await getApplicationSupportDirectory()).path}/chats/images');
    await dir.create(recursive: true);
  }

  static File file(String name) => File(name.contains('/') ? name : '${dir.path}/$name');
  static String ext(String name) => name.contains('.') ? name.split('.').last.toLowerCase() : '';
  static String mimeOf(String name) => _mimes[ext(name)] ?? (_textTypes.contains(ext(name)) ? 'text/plain' : 'application/octet-stream');

  /// Copies a picked file into the app.
  static Future<Att> keep(String path, {String? label}) async {
    final from = File(path);
    final shown = label ?? path.split(RegExp(r'[\\/]')).last;
    final pic = await _picture(from, shown);
    if (pic != null) return pic;
    final e = ext(shown).isEmpty ? ext(path) : ext(shown);
    final name = '${newId()}.${e.isEmpty || e.length > 5 ? 'bin' : e}';
    await from.copy('${dir.path}/$name');
    final size = await from.length();
    String? text;
    if (_textTypes.contains(e) && size < 400000) {
      try {
        text = await from.readAsString();
      } catch (_) {}
    }
    return Att(name: name, label: shown, mime: mimeOf(ext(shown).isEmpty ? path : shown), size: size, text: text);
  }

  /// A photo as every model reads it: what the bytes are decides its type (not its name), and HEIC or a very
  /// large picture is made into a smaller PNG. Null: not a photo, or one this phone can't read.
  static Future<Att?> _picture(File from, String shown) async {
    final f = await from.open();
    final Uint8List h;
    try {
      h = await f.read(12);
    } finally {
      await f.close();
    }
    final type = kindOf(h);
    if (type == null) return null;
    final base = shown.contains('.') ? shown.substring(0, shown.lastIndexOf('.')) : shown;
    final size = await from.length();
    if (type != 'heic' && (size < 4500000 || type == 'gif')) {
      final name = '${newId()}.$type';
      await from.copy('${dir.path}/$name');
      return Att(name: name, label: '$base.$type', mime: _mimes[type]!, size: size);
    }
    try {
      final buf = await ui.ImmutableBuffer.fromUint8List(await from.readAsBytes());
      final codec = await ui.instantiateImageCodecWithSize(
        buf,
        getTargetSize: (w, h) {
          final k = min(1.0, 1600 / max(w, h));
          return ui.TargetImageSize(width: (w * k).round(), height: (h * k).round());
        },
      );
      final frame = await codec.getNextFrame();
      final png = await frame.image.toByteData(format: ui.ImageByteFormat.png);
      frame.image.dispose();
      codec.dispose();
      return await keepBytes(png!.buffer.asUint8List(), '$base.png');
    } catch (_) {
      return null;
    }
  }

  /// What a picture is, from its first bytes.
  static String? kindOf(List<int> h) {
    bool at(int i, String s) => h.length >= i + s.length && String.fromCharCodes(h.sublist(i, i + s.length)) == s;
    if (h.length > 2 && h[0] == 0xFF && h[1] == 0xD8 && h[2] == 0xFF) return 'jpg';
    if (h.isNotEmpty && h[0] == 0x89 && at(1, 'PNG')) return 'png';
    if (at(0, 'GIF8')) return 'gif';
    if (at(0, 'RIFF') && at(8, 'WEBP')) return 'webp';
    if (at(4, 'ftyp') && const ['heic', 'heix', 'hevc', 'heif', 'mif1', 'msf1', 'avif'].any((x) => at(8, x))) return 'heic';
    return null;
  }

  static Future<Att> keepBytes(List<int> bytes, String label) async {
    final name = '${newId()}.${ext(label).isEmpty ? 'bin' : ext(label)}';
    await File('${dir.path}/$name').writeAsBytes(bytes);
    return Att(name: name, label: label, mime: mimeOf(label), size: bytes.length);
  }

  static void drop(Att a) {
    try {
      a.file.deleteSync();
    } catch (_) {}
  }
}

class Msg {
  Msg({required this.role, this.text = '', this.reasoning = '', this.model, DateTime? at, this.error, List<Att>? files, List<ToolStep>? steps, this.thoughtMs, this.tookMs})
    : at = at ?? DateTime.now(),
      files = files ?? [],
      steps = steps ?? [];
  final String role; // user | assistant
  String text;
  String reasoning;
  String? model;
  DateTime at;
  String? error;
  int? thoughtMs, tookMs;
  bool live = false; // being written right now (not saved)
  final List<Att> files;
  final List<ToolStep> steps; // what the assistant did on the way to its answer (searched the web…)

  Map<String, dynamic> toJson() => {
    'role': role,
    'text': text,
    if (reasoning.isNotEmpty) 'reasoning': reasoning,
    'model': ?model,
    'at': at.millisecondsSinceEpoch,
    'error': ?error,
    'thoughtMs': ?thoughtMs,
    'tookMs': ?tookMs,
    if (files.isNotEmpty) 'files': files.map((f) => f.toJson()).toList(),
    if (steps.isNotEmpty) 'steps': steps.map((s) => s.toJson()).toList(),
  };
  factory Msg.fromJson(Map<String, dynamic> j) => Msg(
    role: j['role'] as String,
    text: j['text'] as String? ?? '',
    reasoning: j['reasoning'] as String? ?? '',
    model: j['model'] as String?,
    at: DateTime.fromMillisecondsSinceEpoch(j['at'] as int? ?? 0),
    error: j['error'] as String?,
    thoughtMs: j['thoughtMs'] as int?,
    tookMs: j['tookMs'] as int?,
    files: [
      for (final f in (j['files'] as List? ?? const [])) Att.fromJson(Map<String, dynamic>.from(f as Map)),
      // 1.x kept full paths; only the name still means anything after an update
      for (final p in (j['images'] as List? ?? const [])) Att(name: '$p'.split('/').last, label: 'Photo', mime: Media.mimeOf('$p')),
    ],
    steps: [for (final s in (j['steps'] as List? ?? const [])) ToolStep.fromJson(Map<String, dynamic>.from(s as Map))],
  );
}

/// One tool the model used while answering.
class ToolStep {
  ToolStep({required this.tool, required this.label, this.detail = '', this.state = 'running', this.output = ''});
  final String tool;
  String label; // "Searched the web for …"
  String detail; // a short summary of what came back
  String output; // more of what came back, for the step's own sheet
  String state; // running | done | error

  Map<String, dynamic> toJson() => {
    'tool': tool,
    'label': label,
    if (detail.isNotEmpty) 'detail': detail,
    if (output.isNotEmpty) 'output': output,
    'state': state == 'running' ? 'error' : state,
  };
  factory ToolStep.fromJson(Map<String, dynamic> j) => ToolStep(
    tool: j['tool'] as String? ?? '',
    label: j['label'] as String? ?? '',
    detail: j['detail'] as String? ?? '',
    output: j['output'] as String? ?? '',
    state: j['state'] as String? ?? 'done',
  );
}

class Chat {
  Chat({
    required this.id,
    this.title = '',
    required this.provider,
    required this.model,
    List<Msg>? messages,
    DateTime? updated,
    this.pinned = false,
    this.archived = false,
    this.effort,
    this.assistant,
    this.temporary = false,
  }) : messages = messages ?? [],
       updated = updated ?? DateTime.now();
  final String id;
  String title;
  String provider;
  String model;
  String? effort; // null: the model's own default
  String? assistant;
  final List<Msg> messages;
  DateTime updated;
  bool pinned, archived;
  bool temporary; // never written to the phone, gone when you leave it

  String get preview {
    for (final m in messages.reversed) {
      if (m.text.trim().isNotEmpty) return m.text.trim().replaceAll(RegExp(r'^\s*(?:[-+]|\|?[-:| ]+\|)\s+', multiLine: true), '').replaceAll(RegExp(r'[#*`>|]+|\b_|_\b'), '').replaceAll(RegExp(r'\s+'), ' ').trim();
    }
    return '';
  }

  /// The first place the words appear, for search.
  String? find(String q) {
    for (final m in messages) {
      final at = m.text.toLowerCase().indexOf(q);
      if (at >= 0) {
        final from = (at - 24).clamp(0, m.text.length);
        return '${from > 0 ? '…' : ''}${m.text.substring(from, (at + 90).clamp(0, m.text.length)).replaceAll(RegExp(r'\s+'), ' ')}';
      }
    }
    return null;
  }

  String export() {
    final out = StringBuffer('# ${title.isEmpty ? 'Chat' : title}\n');
    for (final m in messages) {
      out.write('\n## ${m.role == 'user' ? 'You' : (m.model ?? 'Assistant')}\n\n${m.text.trim()}\n');
    }
    return out.toString();
  }

  Map<String, dynamic> toJson() => {
    'id': id,
    'title': title,
    'provider': provider,
    'model': model,
    'updated': updated.millisecondsSinceEpoch,
    'pinned': pinned,
    if (archived) 'archived': true,
    'effort': ?effort,
    'assistant': ?assistant,
    'messages': messages.map((m) => m.toJson()).toList(),
  };
  factory Chat.fromJson(Map<String, dynamic> j) => Chat(
    id: j['id'] as String,
    title: j['title'] as String? ?? '',
    provider: j['provider'] as String? ?? 'openai',
    model: j['model'] as String? ?? '',
    updated: DateTime.fromMillisecondsSinceEpoch(j['updated'] as int? ?? 0),
    pinned: j['pinned'] as bool? ?? false,
    archived: j['archived'] as bool? ?? false,
    effort: j['effort'] as String?,
    assistant: j['assistant'] as String?,
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

  Iterable<Chat> get shown => all.where((c) => !c.archived);
  Chat? byId(String id) => all.where((c) => c.id == id).firstOrNull;

  Future<void> load() async {
    _dir = Directory('${(await getApplicationSupportDirectory()).path}/chats');
    await _dir.create(recursive: true);
    await Media.load();
    for (final f in _dir.listSync().whereType<File>().where((f) => f.path.endsWith('.json'))) {
      try {
        all.add(Chat.fromJson(jsonDecode(await f.readAsString()) as Map<String, dynamic>));
      } catch (_) {
        /* a half-written file: skip it */
      }
    }
    _sort();
  }

  void _sort() => all.sort((a, b) => a.pinned != b.pinned ? (a.pinned ? -1 : 1) : b.updated.compareTo(a.updated));

  /// Stores the chat (adding it to the list the first time) and tells the list to redraw.
  void save(Chat c, {bool now = false}) {
    if (c.temporary) return;
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

  void delete(Chat c, {bool keepMedia = false}) {
    all.remove(c);
    _pending.remove(c.id)?.cancel();
    final f = File('${_dir.path}/${c.id}.json');
    if (f.existsSync()) f.deleteSync();
    if (!keepMedia) {
      for (final m in c.messages) {
        m.files.forEach(Media.drop);
      }
    }
    notifyListeners();
  }

  void deleteAll() {
    for (final c in [...all]) {
      delete(c);
    }
  }

  void flush() {
    for (final id in [..._pending.keys]) {
      _pending[id]?.cancel();
      final c = byId(id);
      if (c != null) save(c, now: true);
    }
  }
}

void debugLog(Object o) {
  if (kDebugMode) debugPrint('$o');
}
