// Speaking and listening: dictation into a message, reading a reply aloud, and the two together.
import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:speech_to_text/speech_to_text.dart';

import 'l10n.dart';
import 'store.dart';

class Voice extends ChangeNotifier {
  Voice._();
  static final Voice i = Voice._();

  final _stt = SpeechToText();
  final _tts = FlutterTts();
  bool _sttReady = false, _ttsReady = false;

  bool listening = false;
  String heard = '';
  double level = 0; // how loud, 0..1
  String? error;

  String? speaking; // id of what is being read aloud
  Completer<void>? _spoke;

  /// Starts listening; [onText] gets the words so far, [onDone] the final ones.
  Future<bool> listen({required void Function(String) onText, void Function(String)? onDone, Duration pause = const Duration(seconds: 3)}) async {
    await hush();
    error = null;
    if (!_sttReady) {
      try {
        _sttReady = await _stt.initialize(
          onStatus: (s) {
            if ((s == 'done' || s == 'notListening') && listening) _ended();
          },
          onError: (e) {
            if (e.errorMsg != 'error_no_match' && e.errorMsg != 'error_speech_timeout') error = e.errorMsg;
            if (listening) _ended();
          },
        );
      } catch (_) {
        _sttReady = false;
      }
    }
    if (!_sttReady) {
      error = t('Speech isn\'t available on this phone. Check the microphone permission.');
      notifyListeners();
      return false;
    }
    heard = '';
    listening = true;
    _done = onDone;
    notifyListeners();
    final lang = Settings.i.str('voice.lang');
    await _stt.listen(
      onResult: (r) {
        heard = r.recognizedWords;
        onText(heard);
        notifyListeners();
      },
      onSoundLevelChange: (v) {
        level = ((v + 2) / 12).clamp(0, 1);
        notifyListeners();
      },
      listenOptions: SpeechListenOptions(
        partialResults: true,
        listenMode: ListenMode.dictation,
        pauseFor: pause,
        listenFor: const Duration(minutes: 2),
        localeId: lang.isEmpty ? (arabic ? 'ar-EG' : null) : lang,
      ),
    );
    return true;
  }

  void Function(String)? _done;
  void _ended() {
    listening = false;
    level = 0;
    final d = _done;
    _done = null;
    notifyListeners();
    d?.call(heard);
  }

  Future<void> stopListening({bool cancel = false}) async {
    if (!listening) return;
    if (cancel) _done = null;
    await _stt.stop();
    if (listening) _ended();
  }

  Future<List<LocaleName>> locales() async {
    if (!_sttReady) {
      try {
        _sttReady = await _stt.initialize();
      } catch (_) {}
    }
    return _sttReady ? await _stt.locales() : const [];
  }

  Future<void> _tts_() async {
    if (_ttsReady) return;
    _ttsReady = true;
    await _tts.awaitSpeakCompletion(true);
    if (defaultTargetPlatform == TargetPlatform.iOS) {
      await _tts.setSharedInstance(true);
      await _tts.setIosAudioCategory(IosTextToSpeechAudioCategory.playback, [IosTextToSpeechAudioCategoryOptions.duckOthers]);
    }
  }

  /// Reads text aloud; ends when it's done or hushed.
  Future<void> speak(String id, String text) async {
    await hush();
    await _tts_();
    speaking = id;
    notifyListeners();
    final clean = plain(text);
    try {
      await _tts.setLanguage(isRtl(clean) ? 'ar' : 'en-US');
      await _tts.setSpeechRate(Settings.i.dbl('voice.rate', .5));
      final mine = _spoke = Completer<void>();
      for (final chunk in _chunks(clean)) {
        if (mine.isCompleted || speaking != id) break;
        await Future.any([_tts.speak(chunk), mine.future]);
      }
    } catch (e) {
      debugLog('tts: $e');
    }
    if (speaking == id) {
      speaking = null;
      notifyListeners();
    }
  }

  Future<void> hush() async {
    final s = _spoke;
    _spoke = null;
    if (s != null && !s.isCompleted) s.complete();
    if (speaking != null) {
      speaking = null;
      notifyListeners();
    }
    if (_ttsReady) await _tts.stop();
  }

  static Iterable<String> _chunks(String s) sync* {
    final buf = StringBuffer();
    for (final part in s.split(RegExp(r'(?<=[.!?؟\n])\s+'))) {
      if (buf.length + part.length > 600 && buf.isNotEmpty) {
        yield buf.toString();
        buf.clear();
      }
      buf.write('$part ');
    }
    if (buf.toString().trim().isNotEmpty) yield buf.toString();
  }

  /// Markdown as it should be said.
  static String plain(String s) => s
      .replaceAll(RegExp(r'```[\s\S]*?```'), t(' (code) '))
      .replaceAllMapped(RegExp(r'\[([^\]]+)\]\([^)]+\)'), (m) => m[1]!)
      .replaceAll(RegExp(r'^\s*\|?[-:| ]+\|\s*$', multiLine: true), '')
      .replaceAll(RegExp(r'[*_`#>|~]+'), ' ')
      .replaceAll(RegExp(r'https?://\S+'), t('a link'))
      .replaceAll(RegExp(r'[ \t]+'), ' ')
      .trim();
}
