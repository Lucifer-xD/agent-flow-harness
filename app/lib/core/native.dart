// Notifications (approvals you can answer without opening the app, finished work, reminders), what
// other apps share into AFH, and staying connected while a thread runs (Android).
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_timezone/flutter_timezone.dart';
import 'package:http/http.dart' as http;
import 'package:timezone/data/latest.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;

import 'hub.dart';
import 'l10n.dart';
import 'relay.dart';
import 'store.dart';
import 'tools.dart' show ToolError;

const _channel = MethodChannel('afh/native');

/// What another app shared: text and copies of its files.
class Shared {
  Shared(this.text, this.files);
  final String text;
  final List<Att> files;
}

class Native {
  static void Function(Shared s)? onShared;

  static void listen() {
    if (!Platform.isAndroid) return;
    _channel.setMethodCallHandler((c) async {
      if (c.method == 'sharedNow') unawaited(_take());
    });
    _take();
  }

  static const _clip = MethodChannel('afh/clipboard');

  /// iPhone: is there a picture on the clipboard (asking this shows no prompt), and the picture itself.
  static Future<bool> hasPicture() async => Platform.isIOS && (await _clip.invokeMethod<bool>('has').catchError((_) => false) ?? false);
  static Future<Att?> picture() async {
    final b = await _clip.invokeMethod<Uint8List>('get');
    return b == null ? null : Media.keepBytes(b, 'pasted.jpg');
  }

  /// Back on the first screen: the app steps aside but keeps running, so work that is on keeps reporting.
  static void background() => _channel.invokeMethod('background').catchError((_) => null);

  static Future<void> _take() async {
    final got = await _channel.invokeMapMethod<String, dynamic>('shared').catchError((_) => null);
    if (got == null) return;
    final files = <Att>[];
    for (final f in (got['files'] as List? ?? const [])) {
      try {
        files.add(await Media.keep('${f['path']}', label: '${f['name']}'));
        File('${f['path']}').deleteSync();
      } catch (_) {}
    }
    final text = '${got['text'] ?? ''}'.trim();
    if (text.isNotEmpty || files.isNotEmpty) onShared?.call(Shared(text, files));
  }
}

/// Allow / Deny pressed on a notification while the app itself isn't running: answer from here.
@pragma('vm:entry-point')
Future<void> onNotificationAction(NotificationResponse r) async {
  if (r.payload == null || (r.actionId != 'allow' && r.actionId != 'deny')) return;
  WidgetsFlutterBinding.ensureInitialized();
  final p = jsonDecode(r.payload!) as Map<String, dynamic>;
  final token = await const FlutterSecureStorage().read(key: 'relay.token');
  if (token == null) return;
  try {
    await http.post(
      Uri.parse('$server/r/${p['cid']}/api/sessions/${p['sid']}/permissions/${p['rid']}'),
      headers: {'authorization': 'Bearer $token', 'content-type': 'application/json'},
      body: jsonEncode({'decision': r.actionId == 'allow' ? 'once' : 'reject'}),
    );
  } catch (_) {}
}

class Notify {
  static final _plugin = FlutterLocalNotificationsPlugin();
  static bool _ready = false;
  static bool inFront = true; // the app is on screen
  static String? openThread; // "computer/thread" on screen right now
  static void Function(String cid, String sid)? onOpen;
  static void Function(String chat)? onOpenChat;

  static Future<void> init() async {
    if (_ready) return;
    _ready = true;
    tzdata.initializeTimeZones();
    try {
      tz.setLocalLocation(tz.getLocation((await FlutterTimezone.getLocalTimezone()).identifier));
    } catch (_) {}
    try {
      await _plugin.initialize(
        settings: InitializationSettings(
          android: const AndroidInitializationSettings('ic_notify'),
          iOS: DarwinInitializationSettings(
            requestAlertPermission: false,
            requestBadgePermission: false,
            requestSoundPermission: false,
            notificationCategories: [
              DarwinNotificationCategory(
                'ask',
                actions: [
                  DarwinNotificationAction.plain('allow', t('Allow'), options: {DarwinNotificationActionOption.foreground}),
                  DarwinNotificationAction.plain('deny', t('Deny'), options: {DarwinNotificationActionOption.foreground}),
                ],
              ),
            ],
          ),
        ),
        onDidReceiveNotificationResponse: _tapped,
        onDidReceiveBackgroundNotificationResponse: onNotificationAction,
      );
      final launch = await _plugin.getNotificationAppLaunchDetails();
      if (launch?.didNotificationLaunchApp == true && launch!.notificationResponse != null) _tapped(launch.notificationResponse!);
    } catch (e) {
      debugLog('notifications: $e');
    }
  }

  static void _tapped(NotificationResponse r) {
    if (r.payload == null) return;
    final p = jsonDecode(r.payload!) as Map<String, dynamic>;
    if (r.actionId == 'allow' || r.actionId == 'deny') {
      final ask = Hubs.i.asks.where((a) => a.id == p['rid']).firstOrNull;
      if (ask != null) {
        unawaited(ask.reply(r.actionId == 'allow' ? 'once' : 'reject').catchError((_) {}));
      } else {
        onNotificationAction(r);
      }
      return;
    }
    if (p['chat'] != null) onOpenChat?.call('${p['chat']}');
    if (p['sid'] != null) onOpen?.call('${p['cid']}', '${p['sid']}');
  }

  static Future<bool> allowed() async {
    await init();
    try {
      final ok = Platform.isIOS
          ? await _plugin.resolvePlatformSpecificImplementation<IOSFlutterLocalNotificationsPlugin>()?.requestPermissions(alert: true, sound: true, badge: true)
          : await _plugin.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()?.requestNotificationsPermission();
      return ok != false;
    } catch (_) {
      return false;
    }
  }

  static int _id(String s) => s.hashCode & 0x3fffffff;

  static Future<void> _show(String key, String title, String body, {required String channel, required String channelName, J? payload, bool ask = false}) async {
    if (!_ready) return;
    try {
      await _plugin.show(
        id: _id(key),
        title: title,
        body: body,
        payload: payload == null ? null : jsonEncode(payload),
        notificationDetails: NotificationDetails(
          android: AndroidNotificationDetails(
            channel,
            channelName,
            importance: ask ? Importance.high : Importance.defaultImportance,
            priority: ask ? Priority.high : Priority.defaultPriority,
            styleInformation: BigTextStyleInformation(body),
            color: const Color(0xFFFF5A3C),
            actions: ask
                ? [
                    AndroidNotificationAction('allow', t('Allow'), showsUserInterface: false, cancelNotification: true),
                    AndroidNotificationAction('deny', t('Deny'), showsUserInterface: false, cancelNotification: true),
                  ]
                : null,
          ),
          iOS: DarwinNotificationDetails(presentAlert: true, presentSound: true, categoryIdentifier: ask ? 'ask' : null),
        ),
      );
    } catch (e) {
      debugLog('notify: $e');
    }
  }

  /// A thread wants an approval or an answer.
  static void ask(Ask a) {
    if (!Settings.i.flag('notify.asks', true) || (inFront && openThread == '${a.hub.computer.id}/${a.sid}') || inFront) return;
    final body = a.isQuestion
        ? '${asList(a.meta['questions']).firstOrNull?['question'] ?? t('It has a question for you.')}'
        : a.isDesign
        ? t('It made designs for you to choose from.')
        : '${a.meta['description'] ?? a.meta['title'] ?? a.action}\n${a.meta['command'] ?? a.resources.take(3).map(baseName).join(', ')}';
    _show(
      a.id,
      a.thread,
      body.trim(),
      channel: 'asks',
      channelName: t('Needs you'),
      ask: !a.isQuestion && !a.isDesign,
      payload: {'cid': a.hub.computer.id, 'sid': a.sid, 'rid': a.id},
    );
  }

  static void gone(String rid) {
    if (_ready) unawaited(_plugin.cancel(id: _id(rid)).catchError((_) {}));
  }

  /// The app is open: what its notifications said is on screen now.
  static Future<void> clear() async {
    if (!_ready) return;
    try {
      for (final n in await _plugin.getActiveNotifications()) {
        if (n.id != null && (n.channelId == 'asks' || n.channelId == 'done')) await _plugin.cancel(id: n.id!, tag: n.tag);
      }
    } catch (_) {}
  }

  /// A thread finished on a computer.
  static void finished(Hub h, J s, {bool failed = false, String error = ''}) {
    if (!Settings.i.flag('notify.done', true) || inFront) return;
    _show(
      '${s['id']}',
      threadName(s),
      failed ? '${t('Stopped on an error')}${error.isEmpty ? '' : ': $error'}' : t('Finished on {}', h.computer.name),
      channel: 'done',
      channelName: t('Finished work'),
      payload: {'cid': h.computer.id, 'sid': '${s['id']}'},
    );
  }

  /// A chat's reply is ready (the app was in the background).
  static void reply(Chat c, String text) {
    if (!Settings.i.flag('notify.done', true) || inFront) return;
    final body = text.trim().replaceAll(RegExp(r'[#*`>]+'), '');
    _show(
      c.id,
      c.title.isEmpty ? t('Reply ready') : c.title,
      body.length > 180 ? '${body.substring(0, 180)}…' : body,
      channel: 'done',
      channelName: t('Finished work'),
      payload: {'chat': c.id},
    );
  }

  /// Keeps the connection open in the background (Android) while something runs.
  static Timer? _soon;
  static bool _liveOn = false;
  static void working() {
    if (!Platform.isAndroid) return;
    _soon?.cancel();
    _soon = Timer(const Duration(milliseconds: 600), () async {
      final running = Hubs.i.threads(running: true);
      final want = Settings.i.flag('notify.live', true) && running.isNotEmpty;
      if (!want) {
        if (_liveOn) unawaited(_channel.invokeMethod('liveStop').catchError((_) => null));
        _liveOn = false;
        if (!inFront) Hubs.i.pause();
        return;
      }
      if (!_liveOn && !inFront) return; // Android only lets it start while the app is on screen
      final (h, s) = running.first;
      final on = await _channel
          .invokeMethod('live', {
            'title': running.length == 1 ? threadName(s) : t('{} threads are working', running.length),
            'text': t('Connected to {}', h.computer.name),
          })
          .catchError((_) => false);
      _liveOn = on == true;
    });
  }

  static bool get keepsLine => _liveOn || Platform.isIOS;

  /// Reminders the assistant sets.
  static Future<void> remind(String message, DateTime when) async {
    if (!await allowed()) throw ToolError('The user did not allow notifications for AFH.');
    await _plugin.zonedSchedule(
      id: when.millisecondsSinceEpoch ~/ 1000 % 2147483647,
      scheduledDate: tz.TZDateTime.from(when, tz.local),
      notificationDetails: const NotificationDetails(
        android: AndroidNotificationDetails('reminders', 'Reminders', channelDescription: 'Reminders the assistant sets for you', importance: Importance.high, priority: Priority.high),
        iOS: DarwinNotificationDetails(presentAlert: true, presentSound: true),
      ),
      androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle,
      title: t('Reminder'),
      body: message,
    );
  }
}

bool get isIOS => defaultTargetPlatform == TargetPlatform.iOS;
