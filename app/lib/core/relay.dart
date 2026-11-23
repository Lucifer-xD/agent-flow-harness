// Remote control: the AFH account server, and through it AFH on the user's own computers. The app
// signs in with a bearer token kept on the phone; requests to /r/<computer>/ are passed by the relay
// to that computer's AFH, which answers them as if the user were sitting at it.
import 'dart:async';
import 'dart:convert';
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import 'l10n.dart';
import 'store.dart';

typedef J = Map<String, dynamic>;
J asMap(Object? v) => v is Map ? J.from(v) : <String, dynamic>{};
List<J> asList(Object? v) => [for (final x in (v is List ? v : const [])) if (x is Map) J.from(x)];

// --dart-define=AFH_SERVER=http://10.0.2.2:8841 points a debug build at a local relay.
const server = String.fromEnvironment('AFH_SERVER', defaultValue: 'https://agentflowharness.com');

class ApiError implements Exception {
  ApiError(this.message, this.status);
  final String message;
  final int status;
  bool get offline => status == 503;
  @override
  String toString() => message;
}

class Computer {
  Computer(this.id, this.name, this.online, this.lastSeen, this.version);
  final String id;
  final String name;
  final bool online;
  final DateTime? lastSeen;
  String? version; // what runs there now; the thread line tells first when it was updated
  factory Computer.fromJson(J j) => Computer(
    j['id'] as String,
    j['name'] as String? ?? 'Computer',
    j['online'] == true,
    j['lastSeen'] is num ? DateTime.fromMillisecondsSinceEpoch(((j['lastSeen'] as num) * (j['lastSeen'] as num > 1e12 ? 1 : 1000)).round()) : null,
    j['version'] as String?,
  );

  /// Whether AFH there is at least this version (1.36 brought the parts the phone needs for files).
  bool atLeast(int major, int minor) {
    final p = (version ?? '').split('.').map((x) => int.tryParse(x) ?? 0).toList();
    if (p.length < 2) return true; // unknown: try
    return p[0] > major || (p[0] == major && p[1] >= minor);
  }
}

Future<dynamic> _request(String method, String path, {Object? body, Duration timeout = const Duration(seconds: 40)}) async {
  final token = Settings.i.relayToken;
  final req = http.Request(method, Uri.parse('$server$path'));
  if (token != null) req.headers['authorization'] = 'Bearer $token';
  if (body != null) {
    req.headers['content-type'] = 'application/json';
    req.body = jsonEncode(body);
  }
  return _answer(req, path, timeout);
}

Future<dynamic> _answer(http.Request req, String path, Duration timeout) async {
  final http.Response res;
  final client = http.Client();
  try {
    res = await http.Response.fromStream(await client.send(req).timeout(timeout)).timeout(timeout);
  } on TimeoutException {
    throw ApiError(t('The server didn\'t answer in time.'), 0);
  } catch (_) {
    throw ApiError(t('No connection. Check your internet and try again.'), 0);
  } finally {
    client.close();
  }
  dynamic data;
  try {
    final text = utf8.decode(res.bodyBytes);
    data = text.isEmpty ? null : jsonDecode(text);
  } catch (_) {}
  if (res.statusCode >= 400) {
    String? detail;
    if (data is Map) {
      final d = data['error'] ?? data['detail'];
      detail = d is String ? d : (d is List && d.isNotEmpty ? '${d.first['msg']}' : null);
    }
    if (res.statusCode == 401 && path.startsWith('/relay/api/me')) {
      await Settings.i.setRelay(null, null);
      Account.i.computers = [];
    }
    throw ApiError(detail ?? (res.statusCode == 503 ? 'That computer is offline.' : 'Something went wrong (${res.statusCode}).'), res.statusCode);
  }
  return data;
}

/// The AFH account on this phone and the computers in it.
class Account extends ChangeNotifier {
  Account._();
  static final Account i = Account._();

  List<Computer> computers = [];
  bool loading = false, loaded = false;
  ApiError? error;

  bool get signedIn => Settings.i.relayToken != null;
  String get email => Settings.i.relayEmail ?? '';

  Future<void> signIn(String email, String password, {bool create = false}) async {
    final got = await _request('POST', '/relay/api/${create ? 'signup' : 'signin'}', body: {'email': email, 'password': password, 'kind': 'app'});
    final token = got['token'] as String?;
    if (token == null) throw ApiError('The server didn\'t return a session. Update the app.', 0);
    await Settings.i.setRelay(token, (got['user'] as Map?)?['email'] as String? ?? email);
    notifyListeners();
    await refresh();
  }

  Future<void> signOut() async {
    try {
      await _request('POST', '/relay/api/signout', body: {}, timeout: const Duration(seconds: 8));
    } catch (_) {}
    await Settings.i.setRelay(null, null);
    computers = [];
    loaded = false;
    notifyListeners();
  }

  Future<void> removeComputer(String id) async {
    await _request('DELETE', '/relay/api/computers/${Uri.encodeComponent(id)}');
    await refresh();
  }

  Future<void> refresh() async {
    if (!signedIn) return;
    loading = true;
    notifyListeners();
    try {
      final me = await _request('GET', '/relay/api/me');
      computers = [for (final c in (me['computers'] as List? ?? [])) Computer.fromJson(J.from(c as Map))];
      computers.sort((a, b) => a.online != b.online ? (a.online ? -1 : 1) : a.name.toLowerCase().compareTo(b.name.toLowerCase()));
      error = null;
      loaded = true;
    } on ApiError catch (e) {
      error = e;
    }
    loading = false;
    notifyListeners();
  }
}

/// One computer's AFH, reached through the relay.
class Pc {
  Pc(this.computer);
  final Computer computer;
  String get _base => '/r/${Uri.encodeComponent(computer.id)}';

  Future<dynamic> get(String path) => _request('GET', '$_base$path');
  Future<dynamic> post(String path, [Object body = const {}]) => _request('POST', '$_base$path', body: body);
  Future<dynamic> put(String path, Object body) => _request('PUT', '$_base$path', body: body);
  Future<dynamic> patch(String path, Object body) => _request('PATCH', '$_base$path', body: body);
  Future<dynamic> delete(String path, [Object? body]) => _request('DELETE', '$_base$path', body: body);

  /// Address and headers for a picture on that computer (Image.network).
  String url(String path) => '$server$_base$path';
  Map<String, String> get headers => {'authorization': 'Bearer ${Settings.i.relayToken}'};
  String imageUrl(String path) => url('/api/image?path=${Uri.encodeQueryComponent(path)}');

  Future<Uint8List> bytes(String path, {Duration timeout = const Duration(seconds: 40)}) async {
    final res = await http.get(Uri.parse(url(path)), headers: headers).timeout(timeout);
    if (res.statusCode >= 400) {
      String? m;
      try {
        m = jsonDecode(res.body)['error'] as String?;
      } catch (_) {}
      throw ApiError(m ?? 'Something went wrong (${res.statusCode}).', res.statusCode);
    }
    return res.bodyBytes;
  }

  /// Sends a photo or file to the computer and returns where it was saved there.
  Future<String> upload(String name, Uint8List data, String mime) async {
    if (data.length > 24 * 1024 * 1024) throw ApiError(t('{} is over 24 MB.', name), 413);
    if (!computer.atLeast(1, 36)) {
      // AFH before 1.36 saves every upload as pasted.png, so photos go as a real PNG and other files can't go
      if (!mime.startsWith('image/')) throw ApiError(t('Update AFH on {} to 1.36 to send files. Photos work already.', computer.name), 0);
      data = await _png(data);
      name = 'photo.png';
      mime = 'image/png';
    }
    final req = http.Request('POST', Uri.parse(url('/api/uploads?name=${Uri.encodeQueryComponent(name)}')))
      ..headers.addAll({...headers, 'content-type': mime, 'x-filename': Uri.encodeComponent(name)})
      ..bodyBytes = data;
    final got = await _answer(req, '/api/uploads', const Duration(minutes: 3));
    return '${asMap(got)['path']}';
  }

  static Future<Uint8List> _png(Uint8List data) async {
    final codec = await ui.instantiateImageCodec(data, targetWidth: 1400);
    final frame = await codec.getNextFrame();
    final out = await frame.image.toByteData(format: ui.ImageByteFormat.png);
    frame.image.dispose();
    return out!.buffer.asUint8List();
  }

  /// Live events from that AFH (every thread). Reconnects by itself until the subscription is cancelled.
  Stream<J> events({void Function(String state)? onState}) {
    late StreamController<J> out;
    http.Client? client;
    var stopped = false;
    Future<void> loop() async {
      var wait = 800;
      while (!stopped) {
        client = http.Client();
        try {
          final req = http.Request('GET', Uri.parse(url('/api/events')))
            ..headers.addAll(headers)
            ..headers['accept'] = 'text/event-stream';
          final res = await client!.send(req).timeout(const Duration(seconds: 20));
          if (res.statusCode != 200) {
            if (res.statusCode == 401 || res.statusCode == 404) {
              onState?.call('gone');
              stopped = true;
              return;
            }
            throw ApiError('events ${res.statusCode}', res.statusCode);
          }
          onState?.call('live');
          wait = 800;
          final data = StringBuffer();
          // the computer sends a ping every 15 s: silence means the line is dead
          await for (final line in res.stream.timeout(const Duration(seconds: 40)).transform(utf8.decoder).transform(const LineSplitter())) {
            if (stopped) return;
            if (line.startsWith('data:')) {
              if (data.isNotEmpty) data.write('\n');
              data.write(line.substring(5).trimLeft());
            } else if (line.isEmpty && data.isNotEmpty) {
              try {
                final ev = jsonDecode(data.toString());
                if (ev is J) out.add(ev);
              } catch (_) {}
              data.clear();
            }
          }
        } catch (e) {
          if (stopped) return;
          if (e is ApiError && e.offline) onState?.call('offline');
        } finally {
          client?.close();
        }
        if (stopped) return;
        onState?.call('reconnecting');
        await Future<void>.delayed(Duration(milliseconds: wait));
        wait = (wait * 2).clamp(800, 15000);
      }
    }

    out = StreamController<J>(
      onListen: loop,
      onCancel: () {
        stopped = true;
        client?.close();
      },
    );
    return out.stream;
  }
}

String baseName(String p) {
  final parts = p.split(RegExp(r'[\\/]')).where((s) => s.isNotEmpty).toList();
  return parts.isEmpty ? p : parts.last;
}

/// A file's path as the user thinks of it: inside its project when it is, else just its name.
String shortPath(String p, [String? root]) {
  final a = p.replaceAll('\\', '/');
  final r = (root ?? '').replaceAll('\\', '/');
  if (r.isNotEmpty && a.toLowerCase().startsWith('${r.toLowerCase()}/')) return a.substring(r.length + 1);
  if (!a.contains(':') && !a.startsWith('/')) return a;
  return baseName(a);
}
