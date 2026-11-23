// The Chats and Threads tabs.
import 'package:flutter/material.dart';

import '../core/hub.dart';
import '../core/l10n.dart';
import '../core/relay.dart';
import '../core/runs.dart';
import '../core/store.dart';
import '../ui/kit.dart';
import '../ui/look.dart';
import '../ui/motion.dart';
import 'account.dart';
import 'assistants.dart';
import 'chat.dart';
import 'compose.dart';
import 'home.dart' show ComputerCard;
import 'rows.dart';
import 'search.dart';

class ChatsTab extends StatelessWidget {
  const ChatsTab({super.key, required this.controller});
  final ScrollController controller;

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: Listenable.merge([Chats.i, Runs.i, Settings.i]),
    builder: (context, _) {
      final p = context.p;
      final list = Chats.i.shown.toList();
      final pinned = [for (final c in list) if (c.pinned) c];
      final groups = <String, List<Chat>>{};
      for (final c in list) {
        if (!c.pinned) (groups[dayGroup(c.updated)] ??= []).add(c);
      }
      final old = Chats.i.all.where((c) => c.archived).length;
      return AppPage(
        title: t('Chats'),
        back: false,
        controller: controller,
        bottom: 110,
        actions: [
          if (old > 0) Ic(LucideIcons.archive, tip: t('Archive'), color: p.text2, onTap: () => go(context, const ArchiveScreen())),
          Ic(LucideIcons.search, tip: t('Search'), color: p.text2, onTap: () => go(context, const SearchScreen())),
        ],
        slivers: [
          SliverToBoxAdapter(
            child: SizedBox(
              height: 40,
              child: ListView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: gutter),
                children: [
                  for (final a in Settings.i.assistants) ...[
                    Pill(a.name, icon: assistantIcon(a.icon), onTap: () => go(context, ChatScreen(newChat(assistant: a), focus: true))),
                    const SizedBox(width: 8),
                  ],
                  Pill(Settings.i.assistants.isEmpty ? t('Make an assistant') : t('Assistants'), icon: LucideIcons.sparkles, onTap: () => go(context, const AssistantsScreen())),
                  const SizedBox(width: 8),
                  Pill(t('Temporary chat'), icon: LucideIcons.ghost, onTap: () => go(context, ChatScreen(newChat(temporary: true), focus: true))),
                ],
              ),
            ),
          ),
          pad([
            if (list.isEmpty)
              Empty(LucideIcons.messageCircle, t('No chats yet'), t('Ask anything. Send a photo, a file or your voice.'), action: t('New chat'), onTap: () => go(context, ChatScreen(newChat(), focus: true))),
            if (pinned.isNotEmpty) ...[Head(t('Pinned')), ChatGroup(pinned)],
            for (final e in groups.entries) ...[Head(e.key), ChatGroup(e.value)],
          ]),
        ],
      );
    },
  );
}

class ArchiveScreen extends StatelessWidget {
  const ArchiveScreen({super.key});
  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: Chats.i,
    builder: (context, _) {
      final list = [for (final c in Chats.i.all) if (c.archived) c];
      return AppPage(
        title: t('Archive'),
        sub: t('Put away, still searchable.'),
        slivers: [
          pad([if (list.isEmpty) Empty(LucideIcons.archive, t('Nothing archived'), '') else ChatGroup(list)]),
        ],
      );
    },
  );
}

class ThreadsTab extends StatefulWidget {
  const ThreadsTab({super.key, required this.controller});
  final ScrollController controller;
  @override
  State<ThreadsTab> createState() => _ThreadsTabState();
}

class _ThreadsTabState extends State<ThreadsTab> {
  String _dir = ''; // '' all, '!' running, else a project's name

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: Listenable.merge([Hubs.i, Account.i, Settings.i]),
    builder: (context, _) {
      final p = context.p;
      final a = Account.i;
      final all = [for (final x in Hubs.i.threads()) if (x.$2['parentID'] == null) x];
      final dirs = <String>{for (final (_, s) in all) baseName(dirOf(s))}.take(8).toList();
      final running = all.where((x) => x.$2['running'] == true).length;
      final list = [
        for (final x in all)
          if (_dir.isEmpty || (_dir == '!' ? x.$2['running'] == true : baseName(dirOf(x.$2)) == _dir)) x,
      ];
      final groups = <String, List<(Hub, J)>>{};
      for (final x in [...list.where((x) => x.$2['running'] == true), ...list.where((x) => x.$2['running'] != true)]) {
        (groups[x.$2['running'] == true ? t('Working now') : dayGroup(updatedOf(x.$2))] ??= []).add(x);
      }
      final loading = Hubs.i.all.values.any((h) => !h.loaded && h.state == 'connecting');
      return AppPage(
        title: t('Threads'),
        back: false,
        controller: widget.controller,
        bottom: 110,
        onRefresh: () async {
          await a.refresh();
          await Future.wait([for (final h in Hubs.i.all.values) h.load()]);
        },
        actions: [
          if (a.signedIn) Ic(LucideIcons.monitor, tip: t('AFH account'), color: p.text2, onTap: () => go(context, const AccountScreen())),
          Ic(LucideIcons.search, tip: t('Search'), color: p.text2, onTap: () => go(context, const SearchScreen())),
        ],
        slivers: [
          if (!a.signedIn)
            pad([
              Empty(
                LucideIcons.monitorSmartphone,
                t('Your computer, in your pocket'),
                t('Follow every thread live, answer what it asks, see what it changed, and start new work. Sign in with your AFH account.'),
                action: t('Sign in'),
                onTap: () => go(context, const SignInScreen()),
              ),
            ])
          else if (a.computers.isEmpty && a.loaded)
            pad([const AddComputer()])
          else ...[
            if (a.computers.isNotEmpty)
              SliverToBoxAdapter(
                child: SizedBox(
                  height: 104,
                  child: ListView.separated(
                    scrollDirection: Axis.horizontal,
                    padding: const EdgeInsets.symmetric(horizontal: gutter),
                    itemCount: a.computers.length,
                    separatorBuilder: (_, _) => const SizedBox(width: 10),
                    itemBuilder: (_, i) => ComputerCard(a.computers[i], width: a.computers.length == 1 ? MediaQuery.sizeOf(context).width - gutter * 2 : 176),
                  ),
                ),
              ),
            if (all.isNotEmpty)
              SliverToBoxAdapter(
                child: Padding(
                  padding: const EdgeInsets.only(top: 16),
                  child: SizedBox(
                    height: 40,
                    child: ListView(
                      scrollDirection: Axis.horizontal,
                      padding: const EdgeInsets.symmetric(horizontal: gutter),
                      children: [
                        Pill(t('All'), on: _dir.isEmpty, onTap: () => setState(() => _dir = '')),
                        if (running > 0) ...[const SizedBox(width: 8), Pill(t('Working'), on: _dir == '!', onTap: () => setState(() => _dir = '!'))],
                        for (final d in dirs) ...[const SizedBox(width: 8), Pill(d, icon: LucideIcons.folder, on: _dir == d, onTap: () => setState(() => _dir = _dir == d ? '' : d))],
                      ],
                    ),
                  ),
                ),
              ),
            pad([
              if (a.error != null && a.computers.isEmpty) Empty(LucideIcons.cloudOff, t('Couldn\'t reach your account'), a.error!.message, action: t('Try again'), onTap: a.refresh),
              if (loading && all.isEmpty)
                for (var i = 0; i < 4; i++) const Padding(padding: EdgeInsets.only(top: 14), child: Bone(h: 64, r: 20)),
              if (!loading && all.isEmpty && Hubs.i.online.isNotEmpty)
                Empty(LucideIcons.gitCommitHorizontal, t('No threads yet'), t('Start some work on {}.', Hubs.i.online.first.computer.name), action: t('New thread'), onTap: () => compose(context, where: 1)),
              for (final e in groups.entries) ...[Head(e.key), ThreadGroup(e.value)],
            ]),
          ],
        ],
      );
    },
  );
}
