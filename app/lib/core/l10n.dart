// Words on screen, in the user's language. English is the key; l10n_ar.dart has the Arabic.
import 'dart:ui';

import 'l10n_ar.dart';
import 'store.dart';

bool _arabic = false;
bool get arabic => _arabic;
Locale get locale => Locale(_arabic ? 'ar' : 'en');

void pickLanguage() {
  final l = Settings.i.language;
  _arabic = l == 'ar' || (l == 'system' && PlatformDispatcher.instance.locale.languageCode == 'ar');
}

/// The text in the user's language; each {} takes the next value.
String t(String en, [Object? a, Object? b, Object? c]) {
  var s = _arabic ? (ar[en] ?? en) : en;
  for (final v in [a, b, c]) {
    if (v == null) break;
    s = s.replaceFirst('{}', '$v');
  }
  return s;
}

bool isRtl(String text) {
  for (final r in text.runes.take(120)) {
    if ((r >= 0x590 && r <= 0x8ff) || (r >= 0xfb1d && r <= 0xfefc)) return true;
    if ((r >= 0x41 && r <= 0x5a) || (r >= 0x61 && r <= 0x7a)) return false;
  }
  return false;
}

/// "now", "4m", "2h", "Mon", "12 Nov".
String ago(DateTime d) {
  final s = DateTime.now().difference(d);
  if (s.inSeconds < 45) return t('now');
  if (s.inMinutes < 60) return t('{}m', s.inMinutes < 1 ? 1 : s.inMinutes);
  if (s.inHours < 24 && DateTime.now().day == d.day) return t('{}h', s.inHours);
  if (s.inDays < 6) return t(const ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][d.weekday - 1]);
  return '${d.day} ${t(const ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.month - 1])}';
}

/// The group a date falls in, for lists.
String dayGroup(DateTime d) {
  final now = DateTime.now();
  final days = DateTime(now.year, now.month, now.day).difference(DateTime(d.year, d.month, d.day)).inDays;
  if (days <= 0) return t('Today');
  if (days == 1) return t('Yesterday');
  if (days < 7) return t('This week');
  if (days < 31) return t('This month');
  return t('Older');
}

String took(int ms) {
  if (ms < 1000) return '${(ms / 1000).toStringAsFixed(1)}s';
  final s = ms ~/ 1000;
  if (s < 60) return '${s}s';
  if (s < 3600) return '${s ~/ 60}m ${s % 60}s';
  return '${s ~/ 3600}h ${(s % 3600) ~/ 60}m';
}

String count(num n) => n >= 1e6
    ? '${(n / 1e6).toStringAsFixed(n >= 1e7 ? 0 : 1)}M'
    : n >= 1000
    ? '${(n / 1000).toStringAsFixed(n >= 1e4 ? 0 : 1)}k'
    : '${n.round()}';

String bytesText(int n) => n >= 1 << 20
    ? '${(n / (1 << 20)).toStringAsFixed(1)} MB'
    : n >= 1024
    ? '${(n / 1024).round()} KB'
    : '$n B';

String money(num n) => '\$${n < 0.01 && n > 0 ? n.toStringAsFixed(4) : n.toStringAsFixed(2)}';
