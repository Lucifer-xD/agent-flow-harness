// Replies being written. They belong to the app, not to a screen: leave a chat and the reply goes on.
import 'dart:async';

import 'package:flutter/foundation.dart';

import 'ai.dart';
import 'l10n.dart';
import 'native.dart';
import 'store.dart';
import 'tools.dart';

class LiveRun extends ChangeNotifier {
  LiveRun(this.chat, this.msg);
  final Chat chat;
  final Msg msg;
  Run? run;
  final _started = DateTime.now();
  DateTime? _thinkingSince;
  Timer? _redraw;
  bool done = false;

  void ping() => notifyListeners();
  void soon() => _redraw ??= Timer(const Duration(milliseconds: 33), () {
    _redraw = null;
    if (!done) notifyListeners();
  });

  void stop() => run?.cancel();

  /// Once, when the reply is complete and the user has stopped to read it.
  void whenDone(void Function() f) {
    void on() {
      if (!done) return;
      removeListener(on);
      Timer(const Duration(milliseconds: 1500), f);
    }

    addListener(on);
  }
}

class Runs extends ChangeNotifier {
  Runs._();
  static final Runs i = Runs._();

  final Map<String, LiveRun> live = {};

  /// Asks the user before a tool does something outside the chat. Set by the shell.
  Future<bool> Function(String title, String text, String action)? confirm;

  LiveRun? of(String chat) => live[chat];

  /// Sends the chat (it ends with the user's message) and writes the reply into it.
  LiveRun start(Chat c) {
    final p = providerById(c.provider);
    final reply = Msg(role: 'assistant', model: c.model)..live = true;
    final history = [...c.messages];
    c.messages.add(reply);
    final r = LiveRun(c, reply);
    live[c.id] = r;
    notifyListeners();
    unawaited(_go(r, p, history));
    return r;
  }

  Future<void> _go(LiveRun r, Provider p, List<Msg> history) async {
    final c = r.chat;
    final a = Settings.i.assistant(c.assistant);
    final last = history.last;
    final run = r.run = Run(
      p,
      c.model,
      history,
      effort: c.effort,
      system: [if (a != null && a.system.trim().isNotEmpty) a.system.trim() else Settings.i.system].where((s) => s.trim().isNotEmpty).join('\n\n'),
      env: Settings.i.tools ? ToolEnv(confirm: (t, x, y) async => await confirm?.call(t, x, y) ?? false, photos: last.files) : null,
    );
    try {
      await for (final d in run.start()) {
        if (d.reasoning.isNotEmpty) {
          r._thinkingSince ??= DateTime.now();
          r.msg.reasoning += d.reasoning;
        }
        if (d.text.isNotEmpty) {
          if (r._thinkingSince != null && r.msg.thoughtMs == null) r.msg.thoughtMs = DateTime.now().difference(r._thinkingSince!).inMilliseconds;
          r.msg.text += d.text;
        }
        if (d.step != null && !r.msg.steps.contains(d.step)) r.msg.steps.add(d.step!);
        r.soon();
      }
    } on AiError catch (e) {
      r.msg.error = e.message;
    } catch (e) {
      r.msg.error = t('Something went wrong: {}', e);
    }
    if (r._thinkingSince != null) r.msg.thoughtMs ??= DateTime.now().difference(r._thinkingSince!).inMilliseconds;
    r.msg.tookMs = DateTime.now().difference(r._started).inMilliseconds;
    for (final s in r.msg.steps) {
      if (s.state == 'running') s.state = 'error';
    }
    r.msg.live = false;
    r.done = true;
    if (r.msg.text.isEmpty && r.msg.error == null && r.msg.steps.isEmpty && r.msg.reasoning.isEmpty) {
      run.cancelled ? c.messages.remove(r.msg) : r.msg.error = t('The model sent an empty reply.');
    }
    c.updated = DateTime.now();
    live.remove(c.id);
    Chats.i.save(c, now: true);
    r.ping();
    notifyListeners();
    if (!run.cancelled && r.msg.error == null) Notify.reply(c, r.msg.text);
  }
}

/// A new chat with the model used last (or the first one that's set up).
(String, String)? firstModel() {
  final last = Settings.i.lastModel;
  if (last != null && last.contains('/')) {
    final pid = last.substring(0, last.indexOf('/'));
    if (providers.any((p) => p.id == pid && p.ready)) return (pid, last.substring(pid.length + 1));
  }
  for (final p in providers.where((p) => p.ready)) {
    if (p.models.isNotEmpty) return (p.id, p.models.first);
  }
  return null;
}
