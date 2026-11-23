// Home: what needs you, what's running, where you were.
import 'package:flutter/material.dart';

import '../core/ai.dart';
import '../core/hub.dart';
import '../core/l10n.dart';
import '../core/relay.dart';
import '../core/runs.dart';
import '../core/store.dart';
import '../ui/kit.dart';
import '../ui/look.dart';
import '../ui/mark.dart';
import '../ui/media.dart';
import '../ui/motion.dart';
import 'account.dart';
import 'asks.dart';
import 'compose.dart';
import 'computer.dart';
import 'providers.dart';
import 'rows.dart';
import 'search.dart';
import 'talk.dart';
import 'chat.dart';
import 'thread.dart';

class HomeTab extends StatelessWidget {
  const HomeTab({super.key, required this.controller});
  final ScrollController controller;

  String _hello() {
    final h = DateTime.now().hour;
    return h < 5
        ? t('Up late?')
        : h < 12
        ? t('Good morning')
        : h < 18
        ? t('Good afternoon')
        : t('Good evening');
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: Listenable.merge([Hubs.i, Account.i, Chats.i, Runs.i, Settings.i]),
    builder: (context, _) {
      final p = context.p;
      final mq = MediaQuery.paddingOf(context);
      final asks = Hubs.i.asks;
      final running = [for (final (h, s) in Hubs.i.threads(running: true)) if (s['parentID'] == null && !asks.any((a) => a.sid == '${s['id']}')) (h, s)];
      final writing = Runs.i.live.values.toList();
      final models = providers.any((x) => x.ready);
      final recent = _recent();
      final status = asks.isNotEmpty
          ? (asks.length == 1 ? t('One thing needs you.') : t('{} things need you.', asks.length))
          : running.isNotEmpty
          ? (running.length == 1 ? t('One thread is working.') : t('{} threads are working.', running.length))
          : t('All quiet.');
      var n = 0;
      return Stack(
        children: [
          RefreshIndicator(
        color: p.accent,
        backgroundColor: p.raised,
        edgeOffset: mq.top + 40,
        onRefresh: () async {
          await Account.i.refresh();
          await Future.wait([for (final h in Hubs.i.all.values) h.load()]);
        },
        child: ListView(
          controller: controller,
          physics: const AlwaysScrollableScrollPhysics(parent: BouncingScrollPhysics()),
          padding: EdgeInsets.fromLTRB(gutter, mq.top + 12, gutter, 120 + mq.bottom),
          children: [
            Row(
              children: [
                AfhLogo(width: 42, working: running.isNotEmpty || writing.isNotEmpty),
                const Spacer(),
                Ic(LucideIcons.search, tip: t('Search'), color: p.text2, onTap: () => go(context, const SearchScreen())),
              ],
            ),
            const SizedBox(height: 26),
            Rise(
              n++,
              child: Text(_hello(), style: T.display.copyWith(color: p.text, fontSize: 34)),
            ),
            const SizedBox(height: 4),
            Rise(
              n++,
              child: Swap(
                align: AlignmentDirectional.centerStart.resolve(Directionality.of(context)),
                child: Text(status, key: ValueKey(status), style: T.h2.copyWith(color: asks.isNotEmpty ? p.accent : p.text3, fontWeight: FontWeight.w400)),
              ),
            ),
            const SizedBox(height: 22),
            Rise(n++, child: _Ask()),
            if (!models || !Account.i.signedIn) ...[const SizedBox(height: 14), Rise(n++, child: _Setup(models: models))],
            if (asks.isNotEmpty) ...[
              Head(t('Needs you'), count: asks.length),
              for (final a in asks)
                Padding(
                  key: ValueKey(a.id),
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Rise(n++, child: AskCard(a, key: ValueKey(a.id), showThread: true, onOpen: () => openThread(context, a.hub, a.sid))),
                ),
            ],
            if (running.isNotEmpty || writing.isNotEmpty) ...[
              Head(t('Working now')),
              for (final (h, s) in running) Rise(n++, key: ValueKey('w${s['id']}'), child: WorkingCard(h, s)),
              if (writing.isNotEmpty) ChatGroup([for (final r in writing) if (!r.chat.temporary) r.chat]),
            ],
            if (Account.i.computers.isNotEmpty) ...[
              Head(t('Computers')),
              SizedBox(
                height: 104,
                child: ListView.separated(
                  scrollDirection: Axis.horizontal,
                  clipBehavior: Clip.none,
                  itemCount: Account.i.computers.length,
                  separatorBuilder: (_, _) => const SizedBox(width: 10),
                  itemBuilder: (_, i) => ComputerCard(Account.i.computers[i], width: Account.i.computers.length == 1 ? MediaQuery.sizeOf(context).width - gutter * 2 : 176),
                ),
              ),
            ],
            if (recent.isNotEmpty) ...[
              Head(t('Recent')),
              Rise(n++, child: Group(children: recent)),
            ],
          ],
        ),
          ),
          // what scrolls goes out of sight under the clock
          Positioned(
            top: 0,
            left: 0,
            right: 0,
            height: mq.top + 10,
            child: IgnorePointer(
              child: DecoratedBox(
                decoration: BoxDecoration(
                  gradient: LinearGradient(begin: Alignment.topCenter, end: Alignment.bottomCenter, colors: [p.bg, p.bg.withValues(alpha: .9), p.bg.withValues(alpha: 0)], stops: const [0, .7, 1]),
                ),
              ),
            ),
          ),
        ],
      );
    },
  );

  List<Widget> _recent() {
    final all = <(DateTime, Widget)>[
      for (final c in Chats.i.shown.take(6)) if (Runs.i.of(c.id) == null) (c.updated, ChatTile(c)),
      for (final (h, s) in Hubs.i.threads().where((x) => x.$2['running'] != true && x.$2['parentID'] == null).take(6)) (updatedOf(s), ThreadTile(h, s, icon: true)),
    ]..sort((a, b) => b.$1.compareTo(a.$1));
    return [for (final x in all.take(6)) x.$2];
  }
}

/// The box that isn't a box yet: tap it to write, or go straight to a photo or to talking.
class _Ask extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final p = context.p;
    Future<void> photo(bool camera) async {
      try {
        final got = await pickPhotos(camera: camera);
        if (got.isNotEmpty && context.mounted) await compose(context, files: got);
      } catch (_) {
        if (context.mounted) toast(context, t('Couldn\'t open that. Check the app\'s permissions.'), bad: true);
      }
    }

    return Press(
      onTap: () => compose(context),
      scale: .985,
      child: Container(
        padding: const EdgeInsets.fromLTRB(18, 17, 10, 8),
        decoration: BoxDecoration(
          color: p.surface,
          borderRadius: BorderRadius.circular(26),
          border: Border.all(color: p.line),
          boxShadow: p.dark ? null : const [BoxShadow(color: Color(0x0A000000), blurRadius: 24, offset: Offset(0, 8))],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(t('Ask, or start some work'), style: T.body.copyWith(color: p.text3)),
            const SizedBox(height: 18),
            Row(
              children: [
                Transform.translate(
                  offset: Offset(Directionality.of(context) == TextDirection.rtl ? 9 : -9, 0),
                  child: Row(
                    children: [
                      Ic(LucideIcons.image, size: 38, icon_: 19, color: p.text2, tip: t('Photos'), onTap: () => photo(false)),
                      Ic(LucideIcons.camera, size: 38, icon_: 19, color: p.text2, tip: t('Camera'), onTap: () => photo(true)),
                    ],
                  ),
                ),
                const Spacer(),
                Ic(
                  LucideIcons.audioLines,
                  size: 40,
                  icon_: 18,
                  color: p.onInv,
                  fill: p.inv,
                  tip: t('Talk'),
                  onTap: () => firstModel() == null ? go(context, const ProvidersScreen()) : go(context, TalkScreen(newChat()), over: true),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _Setup extends StatelessWidget {
  const _Setup({required this.models});
  final bool models;
  @override
  Widget build(BuildContext context) {
    final p = context.p;
    return Group(
      children: [
        if (!models)
          Tile(
            t('Connect a model'),
            sub: t('ChatGPT, Gemini, Claude or any key, to chat on the phone'),
            lead: Square(LucideIcons.sparkles, color: p.accent),
            arrow: true,
            onTap: () => go(context, const ProvidersScreen()),
          ),
        if (!Account.i.signedIn)
          Tile(
            t('Connect your computer'),
            sub: t('Start work there and follow it from here'),
            lead: Square(LucideIcons.monitorSmartphone, color: p.accent),
            arrow: true,
            onTap: () => go(context, const SignInScreen()),
          ),
      ],
    );
  }
}

class ComputerCard extends StatelessWidget {
  const ComputerCard(this.c, {super.key, required this.width});
  final Computer c;
  final double width;
  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final h = Hubs.i.of(c.id);
    final live = c.online && h != null && h.state != 'offline';
    final n = h?.sessions.where((s) => s['running'] == true).length ?? 0;
    final sub = !live
        ? (c.lastSeen == null ? t('Offline') : t('Last online {}', ago(c.lastSeen!)))
        : h.state == 'live'
        ? (n > 0 ? (n == 1 ? t('1 thread working') : t('{} threads working', n)) : t('Ready'))
        : t('Connecting');
    return SizedBox(
      width: width,
      child: Panel(
        onTap: () => go(context, ComputerScreen(c)),
        pad: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(LucideIcons.monitor, size: 20, color: live ? p.text : p.text3),
                const Spacer(),
                n > 0 && live ? const Pulse(size: 14) : Dot(live ? (h.state == 'live' ? p.good : p.warn) : p.fill2),
              ],
            ),
            const Spacer(),
            Text(c.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: T.row.copyWith(color: live ? p.text : p.text2)),
            const SizedBox(height: 1),
            Text(sub, maxLines: 1, overflow: TextOverflow.ellipsis, style: T.small.copyWith(color: p.text3)),
          ],
        ),
      ),
    );
  }
}
