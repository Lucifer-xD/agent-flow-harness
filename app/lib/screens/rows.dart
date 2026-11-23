// Rows and cards for chats and threads, wherever they're listed.
import 'package:flutter/material.dart';

import '../core/ai.dart';
import '../core/hub.dart';
import '../core/l10n.dart';
import '../core/relay.dart';
import '../core/runs.dart';
import '../core/store.dart';
import '../ui/badge.dart';
import '../ui/kit.dart';
import '../ui/look.dart';
import '../ui/motion.dart';
import 'assistants.dart';
import 'chat.dart';
import 'thread.dart';

/// A thread that's running: what it's doing this second, how far its plan is, stop.
class WorkingCard extends StatelessWidget {
  const WorkingCard(this.h, this.s, {super.key});
  final Hub h;
  final J s;

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final sid = '${s['id']}';
    final todos = todosOf(s);
    final done = todos.where((x) => x['status'] == 'completed').length;
    final waiting = s['waiting'] == true;
    final now = t(h.now[sid] ?? (waiting ? 'Waiting for you' : 'Working'));
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Panel(
        onTap: () => openThread(context, h, sid),
        pad: const EdgeInsets.fromLTRB(16, 14, 8, 15),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(titleOf(s), maxLines: 1, overflow: TextOverflow.ellipsis, style: T.h3.copyWith(color: p.text)),
                      const SizedBox(height: 2),
                      Text('${baseName(dirOf(s))} · ${h.computer.name}', maxLines: 1, overflow: TextOverflow.ellipsis, style: T.small.copyWith(color: p.text3)),
                    ],
                  ),
                ),
                Ic(
                  LucideIcons.square,
                  size: 38,
                  icon_: 14,
                  color: p.text2,
                  tip: t('Stop'),
                  onTap: () async {
                    try {
                      await h.stop(sid);
                    } catch (e) {
                      if (context.mounted) toast(context, '$e', bad: true);
                    }
                  },
                ),
              ],
            ),
            const SizedBox(height: 12),
            Padding(
              padding: const EdgeInsetsDirectional.only(end: 8),
              child: Column(
                children: [
                  Row(
                    children: [
                      waiting ? Icon(LucideIcons.hand, size: 14, color: p.accent) : const Pulse(size: 13),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Swap(
                          align: AlignmentDirectional.centerStart.resolve(Directionality.of(context)),
                          child: Text(now, key: ValueKey(now), maxLines: 1, overflow: TextOverflow.ellipsis, style: T.sub.copyWith(color: waiting ? p.accent : p.text2)),
                        ),
                      ),
                      if (todos.isNotEmpty) ...[const SizedBox(width: 8), Text('$done/${todos.length}', style: T.tiny.copyWith(color: p.text3))],
                    ],
                  ),
                  if (todos.isNotEmpty) const SizedBox(height: 11),
                  if (todos.isNotEmpty)
                    Row(
                      children: [
                        for (final (i, x) in todos.indexed) ...[
                          if (i > 0) const SizedBox(width: 3),
                          Expanded(
                            child: x['status'] == 'in_progress' && !waiting
                                ? const StrandLine(height: 3)
                                : AnimatedContainer(
                                    duration: slow,
                                    height: 3,
                                    decoration: BoxDecoration(color: x['status'] == 'completed' ? p.accent : p.fill2, borderRadius: BorderRadius.circular(2)),
                                  ),
                          ),
                        ],
                      ],
                    )
                  else if (!waiting)
                    const StrandLine(height: 3),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

String titleOf(J s) => '${s['title'] ?? ''}'.trim().isEmpty ? t('New thread') : '${s['title']}';

bool unseen(J s) {
  final seen = int.tryParse(Settings.i.str('seen.${s['id']}'));
  return seen != null && s['running'] != true && updatedOf(s).millisecondsSinceEpoch > seen + 1500;
}

class ThreadTile extends StatelessWidget {
  const ThreadTile(this.h, this.s, {super.key, this.icon = false});
  final Hub h;
  final J s;
  final bool icon;

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final running = s['running'] == true, waiting = s['waiting'] == true, failed = s['failed'] == true;
    return Press(
      onTap: () => openThread(context, h, '${s['id']}'),
      onLong: () => threadActions(context, h, s),
      scale: .985,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Row(
          children: [
            Square(
              icon ? LucideIcons.monitor : LucideIcons.gitCommitHorizontal,
              size: 38,
              child: running && !waiting
                  ? const Pulse(size: 15)
                  : waiting
                  ? Icon(LucideIcons.hand, size: 17, color: p.accent)
                  : failed
                  ? Icon(LucideIcons.circleAlert, size: 17, color: p.bad)
                  : Logo('${asMap(s['model'])['providerID'] ?? ''}', name: h.providerNames['${asMap(s['model'])['providerID']}'] ?? '', model: '${asMap(s['model'])['id'] ?? ''}', size: 18, family: true),
            ),
            const SizedBox(width: 13),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    titleOf(s),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: T.row.copyWith(color: p.text, fontWeight: unseen(s) ? FontWeight.w600 : FontWeight.w500),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    waiting ? t('Waiting for you') : running ? t(h.now['${s['id']}'] ?? 'Working') : [baseName(dirOf(s)), if (Hubs.i.all.length > 1 || icon) h.computer.name].join(' · '),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: T.small.copyWith(color: waiting ? p.accent : p.text3),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 10),
            Text(ago(updatedOf(s)), style: T.tiny.copyWith(color: p.text3)),
            if (unseen(s)) ...[const SizedBox(width: 7), Dot(p.accent, size: 7)],
          ],
        ),
      ),
    );
  }
}

Future<void> threadActions(BuildContext context, Hub h, J s) {
  final sid = '${s['id']}';
  Future<void> run(Future<void> Function() f) async {
    try {
      await f();
    } catch (e) {
      if (context.mounted) toast(context, '$e', bad: true);
    }
  }

  return actions(context, title: titleOf(s), [
    if (s['running'] == true) Act(t('Stop'), LucideIcons.square, () => run(() => h.stop(sid))),
    Act(t('Rename'), LucideIcons.pencil, () async {
      final n = await askText(context, t('Rename'), value: titleOf(s));
      if (n != null && n.isNotEmpty) await run(() => h.change(sid, {'title': n}));
    }),
    Act(t('Archive'), LucideIcons.archive, () => run(() => h.change(sid, {'archived': true}))),
    Act(t('Delete'), LucideIcons.trash2, () async {
      if (!await confirm(context, t('Delete this thread?'), t('It is removed from {} for good. The files it changed stay as they are.', h.computer.name), t('Delete'), danger: true)) return;
      await run(() => h.remove(sid));
    }, danger: true),
  ]);
}

/// Threads in one card, with lines between.
class ThreadGroup extends StatelessWidget {
  const ThreadGroup(this.items, {super.key});
  final List<(Hub, J)> items;
  @override
  Widget build(BuildContext context) => Group(
    children: [
      for (final (h, s) in items)
        SwipeRow(
          id: 't${s['id']}',
          endLabel: t('Archive'),
          onEnd: () async {
            try {
              await h.change('${s['id']}', {'archived': true});
              if (context.mounted) {
                toast(context, t('Archived'), icon: LucideIcons.archive, action: t('Undo'), onTap: () => h.change('${s['id']}', {'archived': false}).then((_) => h.load()).catchError((_) {}));
              }
              return true;
            } catch (e) {
              if (context.mounted) toast(context, '$e', bad: true);
              return false;
            }
          },
          child: ThreadTile(h, s),
        ),
    ],
  );
}

class ChatTile extends StatelessWidget {
  const ChatTile(this.c, {super.key, this.found});
  final Chat c;
  final String? found;

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final live = Runs.i.of(c.id) != null;
    final a = Settings.i.assistant(c.assistant);
    return Press(
      onTap: () => go(context, ChatScreen(c)),
      onLong: () => chatActions(context, c),
      scale: .985,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Row(
          children: [
            Square(
              a == null ? null : assistantIcon(a.icon),
              size: 38,
              child: live ? const Pulse(size: 15) : (a == null ? Logo(c.provider, name: providers.where((x) => x.id == c.provider).firstOrNull?.name ?? '', model: c.model, size: 18, family: true) : null),
            ),
            const SizedBox(width: 13),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Flexible(
                        child: Text(
                          c.title.isEmpty ? t('New chat') : c.title,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          textDirection: isRtl(c.title) ? TextDirection.rtl : TextDirection.ltr,
                          style: T.row.copyWith(color: p.text),
                        ),
                      ),
                      if (c.pinned) ...[const SizedBox(width: 6), Icon(LucideIcons.pin, size: 12, color: p.text3)],
                    ],
                  ),
                  const SizedBox(height: 2),
                  Text(found ?? (live ? t('Writing') : c.preview), maxLines: 1, overflow: TextOverflow.ellipsis, style: T.small.copyWith(color: p.text3)),
                ],
              ),
            ),
            const SizedBox(width: 10),
            Text(ago(c.updated), style: T.tiny.copyWith(color: p.text3)),
          ],
        ),
      ),
    );
  }
}

Future<void> chatActions(BuildContext context, Chat c) => actions(context, title: c.title, [
  Act(c.pinned ? t('Unpin') : t('Pin'), c.pinned ? LucideIcons.pinOff : LucideIcons.pin, () {
    c.pinned = !c.pinned;
    Chats.i.save(c);
  }),
  Act(t('Rename'), LucideIcons.pencil, () async {
    final n = await askText(context, t('Rename'), value: c.title);
    if (n == null || n.isEmpty) return;
    c.title = n;
    Chats.i.save(c);
  }),
  Act(t('Save as Markdown'), LucideIcons.fileDown, () => exportChat(c)),
  Act(c.archived ? t('Move out of the archive') : t('Archive'), LucideIcons.archive, () {
    c.archived = !c.archived;
    Chats.i.save(c, now: true);
  }),
  Act(t('Delete'), LucideIcons.trash2, () async {
    if (!await confirm(context, t('Delete this chat?'), t('It is removed from this phone for good.'), t('Delete'), danger: true)) return;
    Runs.i.of(c.id)?.stop();
    Chats.i.delete(c);
  }, danger: true),
]);

/// Chats in one card: swipe to pin or delete.
class ChatGroup extends StatelessWidget {
  const ChatGroup(this.items, {super.key, this.found = const {}});
  final List<Chat> items;
  final Map<String, String> found;
  @override
  Widget build(BuildContext context) => Group(
    children: [
      for (final c in items)
        SwipeRow(
          id: 'c${c.id}',
          startLabel: c.pinned ? t('Unpin') : t('Pin'),
          startIcon: c.pinned ? LucideIcons.pinOff : LucideIcons.pin,
          onStart: () {
            c.pinned = !c.pinned;
            Chats.i.save(c);
            return false;
          },
          endLabel: t('Delete'),
          endIcon: LucideIcons.trash2,
          endBad: true,
          onEnd: () {
            Runs.i.of(c.id)?.stop();
            Chats.i.delete(c, keepMedia: true);
            toast(context, t('Chat deleted'), icon: LucideIcons.trash2, action: t('Undo'), onTap: () => Chats.i.save(c, now: true));
            return true;
          },
          child: ChatTile(c, found: found[c.id]),
        ),
    ],
  );
}
