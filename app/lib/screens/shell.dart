// The frame: four places in a floating dock, and one button for something new.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:quick_actions/quick_actions.dart';

import '../core/hub.dart';
import '../core/l10n.dart';
import '../core/native.dart';
import '../core/relay.dart';
import '../core/runs.dart';
import '../core/store.dart';
import '../ui/kit.dart';
import '../ui/look.dart';
import '../ui/motion.dart';
import 'chat.dart';
import 'compose.dart';
import 'home.dart';
import 'lists.dart';
import 'providers.dart';
import 'talk.dart';
import 'thread.dart';
import 'you.dart';

class Shell extends StatefulWidget {
  const Shell({super.key});
  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  int _at = 0;
  final _scrolls = [for (var i = 0; i < 4; i++) ScrollController()];
  final _built = {0};
  Timer? _poll;

  @override
  void initState() {
    super.initState();
    Runs.i.confirm = (title, text, action) async => mounted && await confirm(context, title, text, action);
    Notify.onOpen = (cid, sid) => _thread(cid, sid);
    Notify.onOpenChat = (id) {
      final c = Chats.i.byId(id);
      if (c != null) _open(ChatScreen(c));
    };
    Native.onShared = (s) {
      if (mounted) compose(context, text: s.text.isEmpty ? null : s.text, files: s.files);
    };
    Native.listen();
    unawaited(Notify.init());
    unawaited(Account.i.refresh());
    _poll = Timer.periodic(const Duration(seconds: 45), (_) {
      if (Notify.inFront && Account.i.signedIn) Account.i.refresh();
    });
    const QuickActions().initialize((id) {
      if (!mounted) return;
      switch (id) {
        case 'chat':
          _open(ChatScreen(newChat(), focus: true));
        case 'work':
          compose(context, where: 1);
        case 'talk':
          firstModel() == null ? _open(const ProvidersScreen()) : go(context, TalkScreen(newChat()), over: true);
      }
    });
    const QuickActions().setShortcutItems([
      ShortcutItem(type: 'chat', localizedTitle: t('New chat'), icon: 'ic_s_chat'),
      ShortcutItem(type: 'work', localizedTitle: t('New thread'), icon: 'ic_s_work'),
      ShortcutItem(type: 'talk', localizedTitle: t('Talk'), icon: 'ic_s_talk'),
    ]);
  }

  void _open(Widget w) {
    if (mounted) go(context, w);
  }

  Future<void> _thread(String cid, String sid) async {
    for (var i = 0; i < 20 && Hubs.i.of(cid) == null; i++) {
      await Future<void>.delayed(const Duration(milliseconds: 300));
    }
    final h = Hubs.i.of(cid);
    if (h == null || !mounted || Notify.openThread == '$cid/$sid') return;
    openThread(context, h, sid);
  }

  @override
  void dispose() {
    _poll?.cancel();
    for (final c in _scrolls) {
      c.dispose();
    }
    super.dispose();
  }

  void _pick(int i) {
    if (i == _at) {
      if (_scrolls[i].hasClients) _scrolls[i].animateTo(0, duration: slow, curve: Curves.easeOutQuint);
      return;
    }
    Tap.tick();
    setState(() {
      _at = i;
      _built.add(i);
    });
  }

  Widget _tab(int i) => switch (i) {
    0 => HomeTab(controller: _scrolls[0]),
    1 => ChatsTab(controller: _scrolls[1]),
    2 => ThreadsTab(controller: _scrolls[2]),
    _ => YouTab(controller: _scrolls[3]),
  };

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    return PopScope(
      canPop: isIOS,
      onPopInvokedWithResult: (did, _) {
        if (did) return;
        _at == 0 ? Native.background() : _pick(0);
      },
      child: Scaffold(
        backgroundColor: p.bg,
        body: Stack(
          children: [
            for (var i = 0; i < 4; i++)
              if (_built.contains(i)) Positioned.fill(child: _Tab(on: i == _at, child: _tab(i))),
            // the content fades out under the dock
            Positioned(
              left: 0,
              right: 0,
              bottom: 0,
              height: 96 + MediaQuery.paddingOf(context).bottom,
              child: IgnorePointer(
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    gradient: LinearGradient(begin: Alignment.topCenter, end: Alignment.bottomCenter, colors: [p.bg.withValues(alpha: 0), p.bg.withValues(alpha: .92)], stops: const [0, .8]),
                  ),
                ),
              ),
            ),
            Positioned(
              left: 0,
              right: 0,
              bottom: 12 + MediaQuery.paddingOf(context).bottom,
              child: Center(
                child: ListenableBuilder(
                  listenable: Hubs.i,
                  builder: (context, _) => Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      _Dock(
                        at: _at,
                        onPick: _pick,
                        items: [
                          (LucideIcons.house, t('Home'), Hubs.i.asks.length),
                          (LucideIcons.messageCircle, t('Chats'), 0),
                          (LucideIcons.layers, t('Threads'), 0),
                          (LucideIcons.userRound, t('You'), 0),
                        ],
                      ),
                      const SizedBox(width: 10),
                      Press(
                        onTap: () => compose(context, where: _at == 1 ? 0 : (_at == 2 ? 1 : null)),
                        scale: .88,
                        label: t('New'),
                        child: Container(
                          width: 60,
                          height: 60,
                          decoration: BoxDecoration(
                            color: p.inv,
                            shape: BoxShape.circle,
                            boxShadow: [BoxShadow(color: Color(p.dark ? 0x66000000 : 0x26000000), blurRadius: 24, offset: const Offset(0, 8))],
                          ),
                          child: Icon(LucideIcons.plus, size: 25, color: p.onInv),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// A tab that stays alive; the one on top fades in and settles.
class _Tab extends StatelessWidget {
  const _Tab({required this.on, required this.child});
  final bool on;
  final Widget child;
  @override
  Widget build(BuildContext context) => IgnorePointer(
    ignoring: !on,
    child: ExcludeSemantics(
      excluding: !on,
      child: AnimatedOpacity(
        opacity: on ? 1 : 0,
        duration: on ? const Duration(milliseconds: 240) : const Duration(milliseconds: 90),
        curve: Curves.easeOut,
        child: AnimatedSlide(
          offset: on ? Offset.zero : const Offset(0, .012),
          duration: slow,
          curve: Curves.easeOutQuint,
          child: TickerMode(enabled: on, child: child),
        ),
      ),
    ),
  );
}

class _Dock extends StatelessWidget {
  const _Dock({required this.at, required this.onPick, required this.items});
  final int at;
  final ValueChanged<int> onPick;
  final List<(IconData, String, int)> items;
  static const _w = 62.0;

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    return DecoratedBox(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(30),
        boxShadow: [BoxShadow(color: Color(p.dark ? 0x59000000 : 0x1A000000), blurRadius: 28, offset: const Offset(0, 10))],
      ),
      child: Glass(
        r: BorderRadius.circular(30),
        child: SizedBox(
          height: 60,
          width: _w * items.length + 12,
          child: Padding(
            padding: const EdgeInsets.all(6),
            child: Stack(
              children: [
                AnimatedPositionedDirectional(
                  duration: const Duration(milliseconds: 480),
                  curve: spring,
                  start: at * _w,
                  top: 0,
                  bottom: 0,
                  width: _w - 2,
                  child: DecoratedBox(
                    decoration: BoxDecoration(color: p.fill2.withValues(alpha: p.dark ? .8 : .75), borderRadius: BorderRadius.circular(24)),
                  ),
                ),
                Row(
                  children: [
                    for (final (i, (icon, label, n)) in items.indexed)
                      Press(
                        onTap: () => onPick(i),
                        label: label,
                        scale: .9,
                        child: SizedBox(
                          width: i == items.length - 1 ? _w - 2 : _w,
                          height: 48,
                          child: Stack(
                            alignment: Alignment.center,
                            children: [
                              Column(
                                mainAxisAlignment: MainAxisAlignment.center,
                                children: [
                                  Icon(icon, size: 21, color: i == at ? p.text : p.text3),
                                  const SizedBox(height: 3),
                                  Text(
                                    label,
                                    maxLines: 1,
                                    textScaler: TextScaler.noScaling,
                                    style: T.tiny.copyWith(fontSize: 10, height: 1, color: i == at ? p.text : p.text3),
                                  ),
                                ],
                              ),
                              if (n > 0) PositionedDirectional(top: 3, end: 11, child: Count(n)),
                            ],
                          ),
                        ),
                      ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
