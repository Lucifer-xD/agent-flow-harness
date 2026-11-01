// Remote control: the AFH account server, and through it AFH on the user's own computers. The app
// signs in with a bearer token kept on the phone; requests to /r/<computer>/ are passed by the relay
// to that computer's AFH, which answers them as if the user were sitting at it.
import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import 'store.dart';

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
  final String? version;
  factory Computer.fromJson(Map<String, dynamic> j) => Computer(
    j['id'] as String,
    j['name'] as String? ?? 'Computer',
    j['online'] == true,
    j['lastSeen'] is num ? DateTime.fromMillisecondsSinceEpoch(((j['lastSeen'] as num) * (j['lastSeen'] as num > 1e12 ? 1 : 1000)).round()) : null,
    j['version'] as String?,
  );
}

Future<dynamic> _request(String method, String path, {Object? body, Duration timeout = const Duration(seconds: 30)}) async {
  final token = Settings.i.relayToken;
  final req = http.Request(method, Uri.parse('$server$path'));
  if (token != null) req.headers['authorization'] = 'Bearer $token';
  if (body != null) {
    req.headers['content-type'] = 'application/json';
    req.body = jsonEncode(body);
  }
  final http.Response res;
  try {
    res = await http.Response.fromStream(await req.send().timeout(timeout));
  } on TimeoutException {
    throw ApiError('The server didn\'t answer in time.', 0);
  } catch (_) {
    throw ApiError('No connection. Check your internet and try again.', 0);
  }
  final text = utf8.decode(res.bodyBytes);
  dynamic data;
  try {
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
  bool loading = false;
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
    notifyListeners();
  }

  Future<void> refresh() async {
    if (!signedIn) return;
    loading = true;
    notifyListeners();
    try {
      final me = await _request('GET', '/relay/api/me');
      computers = [for (final c in (me['computers'] as List? ?? [])) Computer.fromJson(Map<String, dynamic>.from(c as Map))];
      computers.sort((a, b) => a.online != b.online ? (a.online ? -1 : 1) : a.name.toLowerCase().compareTo(b.name.toLowerCase()));
      error = null;
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

  /// Live events from that AFH (every thread). Reconnects by itself until the subscription is cancelled.
  Stream<Map<String, dynamic>> events({void Function(String state)? onState}) {
    late StreamController<Map<String, dynamic>> out;
    http.Client? client;
    var stopped = false;
    Future<void> loop() async {
      var wait = 1000;
      while (!stopped) {
        client = http.Client();
        try {
          final req = http.Request('GET', Uri.parse('$server$_base/api/events'))
            ..headers['authorization'] = 'Bearer ${Settings.i.relayToken}'
            ..headers['accept'] = 'text/event-stream';
          final res = await client!.send(req).timeout(const Duration(seconds: 20));
          if (res.statusCode != 200) throw ApiError('events ${res.statusCode}', res.statusCode);
          onState?.call('live');
          wait = 1000;
          final data = StringBuffer();
          await for (final line in res.stream.transform(utf8.decoder).transform(const LineSplitter())) {
            if (line.startsWith('data:')) {
              if (data.isNotEmpty) data.write('\n');
              data.write(line.substring(5).trimLeft());
            } else if (line.isEmpty && data.isNotEmpty) {
              try {
                final ev = jsonDecode(data.toString());
                if (ev is Map<String, dynamic>) out.add(ev);
              } catch (_) {}
              data.clear();
            }
          }
        } catch (_) {
          if (stopped) return;
        } finally {
          client?.close();
        }
        if (stopped) return;
        onState?.call('reconnecting');
        await Future.delayed(Duration(milliseconds: wait));
        wait = (wait * 2).clamp(1000, 15000);
      }
    }

    out = StreamController<Map<String, dynamic>>(
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
