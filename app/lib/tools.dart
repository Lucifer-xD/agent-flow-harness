// What the model can do from the phone, besides talking: search and read the web, check the weather
// and where the phone is, set reminders, add calendar events, find contacts, start calls, texts and
// emails (as drafts the user sends), copy text, remember things across chats, and hand work to AFH on
// the user's computers. Each tool says what it did as a ToolStep the chat shows under the reply.
import 'dart:async';
import 'dart:convert';

import 'package:add_2_calendar/add_2_calendar.dart' as cal;
import 'package:battery_plus/battery_plus.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_contacts/flutter_contacts.dart' hide Account;
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_timezone/flutter_timezone.dart';
import 'package:geocoding/geocoding.dart';
import 'package:geolocator/geolocator.dart';
import 'package:html/dom.dart' as dom;
import 'package:html/parser.dart' as html;
import 'package:http/http.dart' as http;
import 'package:math_expressions/math_expressions.dart';
import 'package:timezone/data/latest.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;
import 'package:url_launcher/url_launcher.dart';

import 'remote.dart';
import 'store.dart';

/// A tool failed in a way the model should hear about (and can work around).
class ToolError implements Exception {
  ToolError(this.message);
  final String message;
  @override
  String toString() => message;
}

/// What a tool may ask of the screen it runs under.
class ToolEnv {
  ToolEnv({required this.confirm});
  final Future<bool> Function(String title, String text, String action) confirm;
}

class Tool {
  const Tool(this.name, this.description, this.properties, this.run, this.label, {this.required = const []});
  final String name;
  final String description;
  final Map<String, Map<String, dynamic>> properties;
  final List<String> required;
  final Future<String> Function(Map<String, dynamic> args, ToolEnv env) run;
  final String Function(Map<String, dynamic> args) label; // "Searched the web for …"

  Map<String, dynamic> get schema => {'type': 'object', 'properties': properties, if (required.isNotEmpty) 'required': required};
}

Map<String, dynamic> _str(String d) => {'type': 'string', 'description': d};
Map<String, dynamic> _num(String d) => {'type': 'number', 'description': d};
Map<String, dynamic> _bool(String d) => {'type': 'boolean', 'description': d};
String _s(Map<String, dynamic> a, String k) => '${a[k] ?? ''}'.trim();
String _cut(String s, int n) => s.length <= n ? s : '${s.substring(0, n)}…';

const _ua = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36';

/// The tools offered to the model right now (the computer ones only with an AFH account).
List<Tool> phoneTools() => [
  ..._web,
  ..._device,
  ..._apps,
  ..._memory,
  if (Account.i.signedIn) ..._computers,
];

/// Facts the model needs to use the tools well: today's date, where it runs, what it should remember.
String toolContext() {
  final now = DateTime.now();
  final off = now.timeZoneOffset;
  final sign = off.isNegative ? '-' : '+';
  final hh = off.inHours.abs().toString().padLeft(2, '0');
  final mm = (off.inMinutes.abs() % 60).toString().padLeft(2, '0');
  final memory = Settings.i.memory;
  return [
    'You are AFH, an assistant in the AFH app on the user\'s ${_platform()} phone.',
    'Right now it is ${now.toIso8601String().substring(0, 16)} local time (UTC$sign$hh:$mm, ${now.timeZoneName}).',
    'You have tools: use them whenever they help instead of guessing — search the web for anything recent or factual you are '
        'unsure of and read the pages you cite, check the weather or the phone\'s location when asked, set reminders, add calendar '
        'events, find contacts, prepare calls, texts and emails, and hand coding or computer work to AFH on the user\'s computer. '
        'Say briefly what you did. Cite web sources as markdown links.',
    if (memory.isNotEmpty) 'Things the user asked you to remember:\n${memory.map((m) => '- $m').join('\n')}',
  ].join('\n\n');
}

String _platform() => switch (defaultTargetPlatform) {
  TargetPlatform.iOS => 'iPhone',
  TargetPlatform.android => 'Android',
  _ => defaultTargetPlatform.name,
};

// ---- the web -----------------------------------------------------------------------------------

final _web = <Tool>[
  Tool(
    'web_search',
    'Search the web. Returns titles, links and snippets; read the best pages with read_webpage before answering from them.',
    {'query': _str('What to search for'), 'max_results': _num('How many results (default 8, at most 15)')},
    (a, _) => webSearch(_s(a, 'query'), ((a['max_results'] as num?) ?? 8).toInt().clamp(1, 15)),
    (a) => 'Searched the web for "${_s(a, 'query')}"',
    required: ['query'],
  ),
  Tool(
    'read_webpage',
    'Read a web page (or a plain-text or JSON URL) and return its readable text.',
    {'url': _str('The full http(s) URL')},
    (a, _) => readPage(_s(a, 'url')),
    (a) => 'Read ${Uri.tryParse(_s(a, 'url'))?.host ?? _s(a, 'url')}',
    required: ['url'],
  ),
  Tool(
    'get_weather',
    'Current weather and the next days\' forecast for a place, or for where the phone is when no place is given.',
    {'place': _str('A city or place name; leave empty for the phone\'s location')},
    (a, _) => weather(_s(a, 'place')),
    (a) => _s(a, 'place').isEmpty ? 'Checked the weather here' : 'Checked the weather in ${_s(a, 'place')}',
  ),
];

Future<String> webSearch(String query, int max) async {
  if (query.isEmpty) throw ToolError('Give a query.');
  var results = <Map<String, String>>[];
  try {
    results = await _duckduckgo(query);
  } catch (_) {}
  if (results.isEmpty) {
    try {
      results = await _bing(query);
    } catch (_) {}
  }
  if (results.isEmpty) throw ToolError('The search found nothing (or the search engines could not be reached).');
  return [
    for (final (i, r) in results.take(max).indexed) '${i + 1}. ${r['title']}\n   ${r['url']}\n   ${r['snippet']}',
  ].join('\n');
}

Future<List<Map<String, String>>> _duckduckgo(String q) async {
  final res = await http
      .post(Uri.parse('https://html.duckduckgo.com/html/'), headers: {'user-agent': _ua, 'content-type': 'application/x-www-form-urlencoded'}, body: {'q': q, 'kl': ''})
      .timeout(const Duration(seconds: 15));
  if (res.statusCode != 200) return [];
  final doc = html.parse(utf8.decode(res.bodyBytes, allowMalformed: true));
  final out = <Map<String, String>>[];
  for (final r in doc.querySelectorAll('.result')) {
    if (r.classes.contains('result--ad')) continue;
    final a = r.querySelector('a.result__a');
    if (a == null) continue;
    var href = a.attributes['href'] ?? '';
    final u = Uri.tryParse(href.startsWith('//') ? 'https:$href' : href);
    if (u != null && u.queryParameters['uddg'] != null) href = u.queryParameters['uddg']!;
    if (!href.startsWith('http')) continue;
    out.add({'title': a.text.trim(), 'url': href, 'snippet': r.querySelector('.result__snippet')?.text.trim() ?? ''});
  }
  return out;
}

Future<List<Map<String, String>>> _bing(String q) async {
  final res = await http
      .get(Uri.https('www.bing.com', '/search', {'q': q, 'setlang': 'en'}), headers: {'user-agent': _ua, 'accept-language': 'en'})
      .timeout(const Duration(seconds: 15));
  if (res.statusCode != 200) return [];
  final doc = html.parse(utf8.decode(res.bodyBytes, allowMalformed: true));
  return [
    for (final li in doc.querySelectorAll('li.b_algo'))
      if (li.querySelector('h2 a') case final a?)
        if ((a.attributes['href'] ?? '').startsWith('http'))
          {'title': a.text.trim(), 'url': a.attributes['href']!, 'snippet': (li.querySelector('.b_caption p') ?? li.querySelector('p'))?.text.trim() ?? ''},
  ];
}

Future<String> readPage(String url) async {
  final u = Uri.tryParse(url);
  if (u == null || !u.hasScheme || !(u.scheme == 'http' || u.scheme == 'https')) throw ToolError('That is not an http(s) URL.');
  final http.Response res;
  try {
    res = await http
        .get(u, headers: {'user-agent': _ua, 'accept': 'text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.5', 'accept-language': 'en'})
        .timeout(const Duration(seconds: 20));
  } on TimeoutException {
    throw ToolError('The page did not answer in time.');
  } catch (_) {
    throw ToolError('Could not reach ${u.host}.');
  }
  if (res.statusCode >= 400) throw ToolError('${u.host} answered ${res.statusCode}.');
  final type = res.headers['content-type'] ?? '';
  if (type.contains('pdf')) throw ToolError('That is a PDF, which this phone can\'t read. Search for an HTML version instead.');
  if (type.startsWith('image/') || type.startsWith('video/') || type.startsWith('audio/')) throw ToolError('That is a $type file, not a page.');
  final body = utf8.decode(res.bodyBytes.length > 3000000 ? res.bodyBytes.sublist(0, 3000000) : res.bodyBytes, allowMalformed: true);
  if (!type.contains('html') && !body.trimLeft().startsWith('<')) return _cut(body, 15000);
  final doc = html.parse(body);
  final title = doc.querySelector('title')?.text.trim() ?? '';
  for (final e in doc.querySelectorAll('script,style,noscript,svg,nav,footer,header,form,iframe,aside,button,template')) {
    e.remove();
  }
  final root = doc.querySelector('article') ?? doc.querySelector('main') ?? doc.body;
  if (root == null) return title;
  for (final e in root.querySelectorAll('p,div,li,h1,h2,h3,h4,h5,h6,br,tr,section,blockquote,pre')) {
    e.append(dom.Text('\n'));
  }
  for (final e in root.querySelectorAll('a[href]')) {
    final href = e.attributes['href'] ?? '';
    if (href.startsWith('http') && e.text.trim().length > 2) e.append(dom.Text(' ($href)'));
  }
  final lines = root.text.split('\n').map((l) => l.replaceAll(RegExp(r'\s+'), ' ').trim()).where((l) => l.isNotEmpty).toList();
  final text = lines.join('\n');
  return _cut('${title.isEmpty ? '' : '# $title\n\n'}$text', 15000);
}

const _wmo = {
  0: 'clear sky', 1: 'mainly clear', 2: 'partly cloudy', 3: 'overcast', 45: 'fog', 48: 'rime fog', 51: 'light drizzle', 53: 'drizzle',
  55: 'heavy drizzle', 61: 'light rain', 63: 'rain', 65: 'heavy rain', 66: 'freezing rain', 67: 'heavy freezing rain', 71: 'light snow',
  73: 'snow', 75: 'heavy snow', 77: 'snow grains', 80: 'light showers', 81: 'showers', 82: 'violent showers', 85: 'snow showers',
  86: 'heavy snow showers', 95: 'thunderstorm', 96: 'thunderstorm with hail', 99: 'thunderstorm with heavy hail',
};

Future<String> weather(String place) async {
  double lat, lon;
  String name;
  if (place.isEmpty) {
    final p = await _position();
    lat = p.latitude;
    lon = p.longitude;
    name = await _placeName(lat, lon) ?? 'your location';
  } else {
    final g = await http.get(Uri.https('geocoding-api.open-meteo.com', '/v1/search', {'name': place, 'count': '1'})).timeout(const Duration(seconds: 15));
    final hit = ((jsonDecode(g.body) as Map)['results'] as List?)?.firstOrNull as Map?;
    if (hit == null) throw ToolError('No place called "$place" was found.');
    lat = (hit['latitude'] as num).toDouble();
    lon = (hit['longitude'] as num).toDouble();
    name = [hit['name'], hit['admin1'], hit['country']].whereType<String>().join(', ');
  }
  final res = await http
      .get(
        Uri.https('api.open-meteo.com', '/v1/forecast', {
          'latitude': '$lat',
          'longitude': '$lon',
          'current': 'temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,precipitation',
          'daily': 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset',
          'timezone': 'auto',
          'forecast_days': '5',
        }),
      )
      .timeout(const Duration(seconds: 15));
  if (res.statusCode != 200) throw ToolError('The weather service answered ${res.statusCode}.');
  final j = jsonDecode(res.body) as Map;
  final c = j['current'] as Map;
  final d = j['daily'] as Map;
  final days = <String>[
    for (var i = 0; i < (d['time'] as List).length; i++)
      '${d['time'][i]}: ${_wmo[d['weather_code'][i]] ?? 'code ${d['weather_code'][i]}'}, ${d['temperature_2m_min'][i]}–${d['temperature_2m_max'][i]} °C, '
          'rain chance ${d['precipitation_probability_max'][i] ?? '?'}%, sunrise ${'${d['sunrise'][i]}'.split('T').last}, sunset ${'${d['sunset'][i]}'.split('T').last}',
  ];
  return 'Weather for $name (${lat.toStringAsFixed(3)}, ${lon.toStringAsFixed(3)}), local time ${c['time']}:\n'
      'Now: ${_wmo[c['weather_code']] ?? c['weather_code']}, ${c['temperature_2m']} °C (feels like ${c['apparent_temperature']} °C), '
      'humidity ${c['relative_humidity_2m']}%, wind ${c['wind_speed_10m']} km/h, precipitation ${c['precipitation']} mm\n'
      'Next days:\n${days.join('\n')}';
}

// ---- the phone ---------------------------------------------------------------------------------

final _device = <Tool>[
  Tool(
    'get_location',
    'Where the phone is right now: coordinates, accuracy and the street address. Asks the user for permission the first time.',
    {},
    (a, _) async {
      final p = await _position();
      final place = await _placeName(p.latitude, p.longitude);
      return 'Latitude ${p.latitude}, longitude ${p.longitude} (±${p.accuracy.round()} m)${place == null ? '' : '\nAddress: $place'}';
    },
    (a) => 'Checked where you are',
  ),
  Tool(
    'get_device_info',
    'The phone\'s date and time, time zone, battery level and charging state, platform and language.',
    {},
    (a, _) async {
      final b = Battery();
      int? level;
      BatteryState? state;
      try {
        level = await b.batteryLevel;
        state = await b.batteryState;
      } catch (_) {}
      String zone = DateTime.now().timeZoneName;
      try {
        zone = (await FlutterTimezone.getLocalTimezone()).identifier;
      } catch (_) {}
      return 'Local time: ${DateTime.now()}\nTime zone: $zone\nPlatform: ${_platform()}\nLanguage: ${PlatformDispatcher.instance.locale.toLanguageTag()}'
          '${level == null ? '' : '\nBattery: $level% (${state?.name ?? 'unknown'})'}';
    },
    (a) => 'Checked the phone',
  ),
  Tool(
    'calculate',
    'Evaluate a math expression exactly, e.g. "(1200*0.15)+sqrt(16)" or "2^10". Supports + - * / ^ % sqrt sin cos tan log ln abs.',
    {'expression': _str('The expression')},
    (a, _) async {
      final e = _s(a, 'expression');
      try {
        final v = RealEvaluator(ContextModel()).evaluate(GrammarParser().parse(e));
        return '$e = ${v == v.roundToDouble() && v.abs() < 1e15 ? v.toInt() : v}';
      } catch (_) {
        throw ToolError('Could not evaluate "$e".');
      }
    },
    (a) => 'Calculated ${_cut(_s(a, 'expression'), 40)}',
    required: ['expression'],
  ),
  Tool(
    'read_clipboard',
    'Read the text the user last copied.',
    {},
    (a, _) async => (await Clipboard.getData(Clipboard.kTextPlain))?.text ?? '(the clipboard is empty)',
    (a) => 'Read your clipboard',
  ),
  Tool(
    'copy_to_clipboard',
    'Put text on the clipboard so the user can paste it anywhere.',
    {'text': _str('The text to copy')},
    (a, _) async {
      await Clipboard.setData(ClipboardData(text: _s(a, 'text')));
      return 'Copied.';
    },
    (a) => 'Copied text to your clipboard',
    required: ['text'],
  ),
];

Future<Position> _position() async {
  if (!await Geolocator.isLocationServiceEnabled()) throw ToolError('Location is turned off on this phone.');
  var perm = await Geolocator.checkPermission();
  if (perm == LocationPermission.denied) perm = await Geolocator.requestPermission();
  if (perm == LocationPermission.denied || perm == LocationPermission.deniedForever) {
    throw ToolError('The user did not allow location access (they can turn it on in the phone\'s settings for AFH).');
  }
  return Geolocator.getCurrentPosition(locationSettings: const LocationSettings(accuracy: LocationAccuracy.high, timeLimit: Duration(seconds: 20)));
}

Future<String?> _placeName(double lat, double lon) async {
  try {
    final p = (await Geocoding().placemarkFromCoordinates(lat, lon)).firstOrNull;
    if (p == null) return null;
    return [p.street, p.subLocality, p.locality, p.administrativeArea, p.country].whereType<String>().where((s) => s.isNotEmpty).toSet().join(', ');
  } catch (_) {
    return null;
  }
}

// ---- other apps on the phone -------------------------------------------------------------------

Future<String> _launch(Uri uri, String what) async {
  try {
    if (await launchUrl(uri, mode: LaunchMode.externalApplication)) return 'Opened $what. The user takes it from there.';
  } catch (_) {}
  throw ToolError('This phone could not open $what.');
}

final _apps = <Tool>[
  Tool(
    'open_link',
    'Open a web page or app link on the phone for the user to see.',
    {'url': _str('The URL to open')},
    (a, _) => _launch(Uri.parse(_s(a, 'url')), 'the link'),
    (a) => 'Opened ${Uri.tryParse(_s(a, 'url'))?.host ?? 'a link'}',
    required: ['url'],
  ),
  Tool(
    'open_maps',
    'Show a place, or directions to it, in the phone\'s maps app.',
    {'query': _str('An address or place name'), 'directions': _bool('true for directions from where the user is')},
    (a, _) {
      final q = _s(a, 'query');
      final ios = defaultTargetPlatform == TargetPlatform.iOS;
      final uri = a['directions'] == true
          ? (ios ? Uri.https('maps.apple.com', '/', {'daddr': q}) : Uri.https('www.google.com', '/maps/dir/', {'api': '1', 'destination': q}))
          : (ios ? Uri.https('maps.apple.com', '/', {'q': q}) : Uri.https('www.google.com', '/maps/search/', {'api': '1', 'query': q}));
      return _launch(uri, 'maps');
    },
    (a) => a['directions'] == true ? 'Opened directions to ${_s(a, 'query')}' : 'Opened ${_s(a, 'query')} in maps',
    required: ['query'],
  ),
  Tool(
    'start_call',
    'Open the phone app ready to call a number (the user taps call). Use find_contact first for names.',
    {'number': _str('The phone number')},
    (a, _) => _launch(Uri(scheme: 'tel', path: _s(a, 'number').replaceAll(RegExp(r'[^0-9+*#]'), '')), 'the phone app'),
    (a) => 'Ready to call ${_s(a, 'number')}',
    required: ['number'],
  ),
  Tool(
    'draft_text_message',
    'Open Messages with a text ready to send (the user taps send).',
    {'number': _str('Who to send it to (a phone number); can be empty'), 'body': _str('The message')},
    (a, _) {
      final n = _s(a, 'number').replaceAll(RegExp(r'[^0-9+]'), '');
      final body = Uri.encodeComponent(_s(a, 'body'));
      final sep = defaultTargetPlatform == TargetPlatform.iOS ? '&' : '?';
      return _launch(Uri.parse('sms:$n${sep}body=$body'), 'Messages');
    },
    (a) => 'Drafted a text${_s(a, 'number').isEmpty ? '' : ' to ${_s(a, 'number')}'}',
    required: ['body'],
  ),
  Tool(
    'draft_email',
    'Open the mail app with an email ready to send (the user taps send).',
    {'to': _str('Email address(es), comma-separated; can be empty'), 'subject': _str('Subject'), 'body': _str('The email text')},
    (a, _) {
      String enc(String s) => Uri.encodeComponent(s);
      return _launch(Uri.parse('mailto:${_s(a, 'to')}?subject=${enc(_s(a, 'subject'))}&body=${enc(_s(a, 'body'))}'), 'the mail app');
    },
    (a) => 'Drafted an email${_s(a, 'to').isEmpty ? '' : ' to ${_s(a, 'to')}'}',
    required: ['body'],
  ),
  Tool(
    'find_contact',
    'Look up people in the phone\'s contacts by name; returns their numbers and emails. Asks for permission the first time.',
    {'name': _str('All or part of the name')},
    (a, _) async {
      final name = _s(a, 'name');
      final st = await FlutterContacts.permissions.request(PermissionType.read);
      if (st != PermissionStatus.granted && st != PermissionStatus.limited) throw ToolError('The user did not allow access to contacts.');
      final found = await FlutterContacts.getAll(properties: {ContactProperty.name, ContactProperty.phone, ContactProperty.email}, filter: ContactFilter.name(name), limit: 10);
      if (found.isEmpty) return 'No contact matches "$name".';
      return [
        for (final c in found)
          '${c.displayName ?? '?'}: ${[...c.phones.map((p) => 'phone ${p.number}'), ...c.emails.map((e) => 'email ${e.address}')].join(', ')}',
      ].join('\n');
    },
    (a) => 'Looked up ${_s(a, 'name')} in your contacts',
    required: ['name'],
  ),
  Tool(
    'set_reminder',
    'Set a reminder: the phone shows a notification at that time, even with the app closed.',
    {
      'message': _str('What to remind the user about'),
      'at': _str('When, as local date-time "YYYY-MM-DDTHH:MM" (use this or in_minutes)'),
      'in_minutes': _num('Or: in how many minutes from now'),
    },
    (a, _) async {
      final mins = a['in_minutes'] as num?;
      final when = mins != null ? DateTime.now().add(Duration(seconds: (mins * 60).round())) : DateTime.tryParse(_s(a, 'at'));
      if (when == null) throw ToolError('Give "at" as YYYY-MM-DDTHH:MM or "in_minutes".');
      if (when.isBefore(DateTime.now())) throw ToolError('That time has already passed.');
      await Reminders.schedule(_s(a, 'message'), when);
      return 'Reminder set for ${when.toString().substring(0, 16)}.';
    },
    (a) => 'Set a reminder: ${_cut(_s(a, 'message'), 50)}',
    required: ['message'],
  ),
  Tool(
    'add_calendar_event',
    'Add an event to the phone\'s calendar; the calendar app opens with it filled in for the user to save.',
    {
      'title': _str('Event title'),
      'start': _str('Local start "YYYY-MM-DDTHH:MM"'),
      'end': _str('Local end "YYYY-MM-DDTHH:MM" (default: one hour later)'),
      'location': _str('Where'),
      'notes': _str('Notes'),
      'all_day': _bool('An all-day event'),
    },
    (a, _) async {
      final start = DateTime.tryParse(_s(a, 'start'));
      if (start == null) throw ToolError('Give "start" as YYYY-MM-DDTHH:MM.');
      final end = DateTime.tryParse(_s(a, 'end')) ?? start.add(const Duration(hours: 1));
      final ok = await cal.Add2Calendar.addEvent2Cal(
        cal.Event(
          title: _s(a, 'title'),
          startDate: start,
          endDate: end,
          location: _s(a, 'location').isEmpty ? null : _s(a, 'location'),
          description: _s(a, 'notes').isEmpty ? null : _s(a, 'notes'),
          allDay: a['all_day'] == true,
        ),
      );
      if (!ok) throw ToolError('The calendar could not be opened.');
      return 'The calendar opened with "${_s(a, 'title')}" on ${start.toString().substring(0, 16)}; the user saves it there.';
    },
    (a) => 'Added "${_cut(_s(a, 'title'), 40)}" to your calendar',
    required: ['title', 'start'],
  ),
];

/// Local notifications for set_reminder.
class Reminders {
  static final _plugin = FlutterLocalNotificationsPlugin();
  static bool _ready = false;

  static Future<void> _init() async {
    if (_ready) return;
    tzdata.initializeTimeZones();
    try {
      tz.setLocalLocation(tz.getLocation((await FlutterTimezone.getLocalTimezone()).identifier));
    } catch (_) {}
    await _plugin.initialize(
      settings: const InitializationSettings(
        android: AndroidInitializationSettings('@mipmap/ic_launcher'),
        iOS: DarwinInitializationSettings(requestAlertPermission: false, requestBadgePermission: false, requestSoundPermission: false),
      ),
    );
    _ready = true;
  }

  static Future<void> schedule(String message, DateTime when) async {
    await _init();
    final allowed = defaultTargetPlatform == TargetPlatform.iOS
        ? await _plugin.resolvePlatformSpecificImplementation<IOSFlutterLocalNotificationsPlugin>()?.requestPermissions(alert: true, sound: true, badge: true)
        : await _plugin.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()?.requestNotificationsPermission();
    if (allowed == false) throw ToolError('The user did not allow notifications for AFH.');
    await _plugin.zonedSchedule(
      id: when.millisecondsSinceEpoch ~/ 1000 % 2147483647,
      scheduledDate: tz.TZDateTime.from(when, tz.local),
      notificationDetails: const NotificationDetails(
        android: AndroidNotificationDetails('reminders', 'Reminders', channelDescription: 'Reminders the assistant sets for you', importance: Importance.high, priority: Priority.high),
        iOS: DarwinNotificationDetails(presentAlert: true, presentSound: true),
      ),
      androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle,
      title: 'Reminder',
      body: message,
    );
  }
}

// ---- memory ------------------------------------------------------------------------------------

final _memory = <Tool>[
  Tool(
    'remember',
    'Remember a fact about the user or their preferences for all future chats (name, city, how they like answers…). Only when they ask or it is clearly useful.',
    {'fact': _str('The fact, as one short sentence')},
    (a, _) async {
      final f = _s(a, 'fact');
      if (f.isEmpty) throw ToolError('Give the fact.');
      final m = [...Settings.i.memory];
      if (!m.contains(f)) m.add(f);
      Settings.i.memory = m.length > 50 ? m.sublist(m.length - 50) : m;
      return 'Remembered.';
    },
    (a) => 'Remembered: ${_cut(_s(a, 'fact'), 50)}',
    required: ['fact'],
  ),
  Tool(
    'forget',
    'Forget something you were asked to remember.',
    {'fact': _str('The remembered fact (or words from it)')},
    (a, _) async {
      final q = _s(a, 'fact').toLowerCase();
      final m = [...Settings.i.memory];
      final before = m.length;
      m.removeWhere((x) => x.toLowerCase().contains(q) || q.contains(x.toLowerCase()));
      Settings.i.memory = m;
      return before == m.length ? 'Nothing like that was remembered.' : 'Forgotten.';
    },
    (a) => 'Forgot: ${_cut(_s(a, 'fact'), 50)}',
    required: ['fact'],
  ),
];

// ---- AFH on the user's computers ---------------------------------------------------------------

Computer _pick(String name) {
  final online = Account.i.computers.where((c) => c.online).toList();
  if (online.isEmpty) throw ToolError('None of the user\'s computers is online. They need to open AFH on one.');
  if (name.isEmpty) return online.first;
  return online.firstWhere((c) => c.name.toLowerCase() == name.toLowerCase(),
      orElse: () => online.firstWhere((c) => c.name.toLowerCase().contains(name.toLowerCase()), orElse: () => throw ToolError('No online computer is called "$name".')));
}

String _assistantText(List msgs) {
  for (final m in msgs.reversed) {
    if (m is! Map || m['type'] != 'assistant') continue;
    final text = [for (final c in (m['content'] as List? ?? [])) if (c is Map && c['type'] == 'text') '${c['text'] ?? ''}'].join('\n').trim();
    if (text.isNotEmpty) return text;
  }
  return '';
}

final _computers = <Tool>[
  Tool(
    'list_computers',
    'The user\'s computers with AFH (online or not) and, for online ones, their projects (folders AFH works in).',
    {},
    (a, _) async {
      await Account.i.refresh();
      if (Account.i.computers.isEmpty) return 'No computers are linked to the user\'s AFH account.';
      final out = <String>[];
      for (final c in Account.i.computers) {
        var line = '${c.name}: ${c.online ? 'online' : 'offline'}';
        if (c.online) {
          try {
            final s = await Pc(c).get('/api/settings');
            final projects = [for (final p in (s['projects'] as List? ?? [])) '$p'];
            if (projects.isNotEmpty) line += '\n  projects: ${projects.take(15).join(', ')}';
          } catch (_) {}
        }
        out.add(line);
      }
      return out.join('\n');
    },
    (a) => 'Checked your computers',
  ),
  Tool(
    'run_on_computer',
    'Hand a task to AFH, the coding agent on the user\'s computer: it can read and change files, run commands, build and test code, '
        'browse, and anything else the computer can do. Waits up to a few minutes for its answer. The user confirms first.',
    {
      'task': _str('What AFH on the computer should do, fully explained'),
      'project': _str('The project folder to work in (from list_computers); empty for the most recent one'),
      'computer': _str('Which computer (empty for the first online one)'),
    },
    (a, env) async {
      if (Account.i.computers.isEmpty) await Account.i.refresh();
      final c = _pick(_s(a, 'computer'));
      final pc = Pc(c);
      final settings = await pc.get('/api/settings');
      final projects = [for (final p in (settings['projects'] as List? ?? [])) '$p'];
      final want = _s(a, 'project');
      final dir = want.isEmpty
          ? (projects.isEmpty ? null : projects.first)
          : projects.firstWhere((p) => p == want || baseName(p).toLowerCase() == want.toLowerCase(), orElse: () => want);
      final task = _s(a, 'task');
      if (!await env.confirm('Run this on ${c.name}?', '${dir == null ? '' : 'In ${baseName(dir)}:\n\n'}$task', 'Run it')) {
        throw ToolError('The user said no.');
      }
      final s = Map<String, dynamic>.from(await pc.post('/api/sessions', {'directory': ?dir}) as Map);
      final sid = s['id'];
      await pc.post('/api/sessions/$sid/prompt', {'text': task});
      final until = DateTime.now().add(const Duration(minutes: 4));
      while (DateTime.now().isBefore(until)) {
        await Future<void>.delayed(const Duration(seconds: 5));
        final st = await pc.get('/api/sessions/$sid');
        if (st is Map && st['running'] != true) {
          final text = _assistantText(await pc.get('/api/sessions/$sid/messages') as List? ?? []);
          return 'AFH on ${c.name} finished (thread $sid).\n\n${text.isEmpty ? '(no text reply)' : _cut(text, 12000)}';
        }
        final perms = await pc.get('/api/sessions/$sid/permissions').catchError((_) => <dynamic>[]);
        if (perms is List && perms.isNotEmpty) {
          return 'AFH on ${c.name} is waiting for the user to approve a step (thread $sid). Tell them to open Computers → ${c.name} to approve it.';
        }
      }
      return 'AFH on ${c.name} is still working on it (thread $sid). The user can follow it under Computers → ${c.name}; check back with read_computer_thread.';
    },
    (a) => 'Asked AFH on ${_s(a, 'computer').isEmpty ? 'your computer' : _s(a, 'computer')}: ${_cut(_s(a, 'task'), 50)}',
    required: ['task'],
  ),
  Tool(
    'read_computer_thread',
    'Check on a thread started with run_on_computer: whether it is still running and its latest answer.',
    {'thread': _str('The thread id'), 'computer': _str('Which computer (empty for the first online one)')},
    (a, _) async {
      if (Account.i.computers.isEmpty) await Account.i.refresh();
      final pc = Pc(_pick(_s(a, 'computer')));
      final sid = _s(a, 'thread');
      final st = await pc.get('/api/sessions/$sid');
      final text = _assistantText(await pc.get('/api/sessions/$sid/messages') as List? ?? []);
      return '${st is Map && st['running'] == true ? 'Still running.' : 'Finished.'}\n\n${text.isEmpty ? '(no text yet)' : _cut(text, 12000)}';
    },
    (a) => 'Checked the thread on your computer',
    required: ['thread'],
  ),
];
