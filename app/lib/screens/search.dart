// Search everything: chats (what was said in them) and threads.
import 'dart:async';

import 'package:flutter/material.dart';

import '../core/hub.dart';
import '../core/l10n.dart';
import '../core/relay.dart';
import '../core/store.dart';
import '../ui/kit.dart';
import '../ui/look.dart';
import '../ui/motion.dart';
import 'rows.dart';

class SearchScreen extends StatefulWidget {
  const SearchScreen({super.key});
  @override
  State<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends State<SearchScreen> {
  final _q = TextEditingController();
  Timer? _t;
  List<Chat> _chats = const [];
  Map<String, String> _found = const {};
  List<(Hub, J)> _threads = const [];
  String _done = '';

  @override
  void dispose() {
    _t?.cancel();
    _q.dispose();
    super.dispose();
  }

  void _run(String s) {
    _t?.cancel();
    _t = Timer(const Duration(milliseconds: 120), () {
      final q = s.trim().toLowerCase();
      final chats = <Chat>[];
      final found = <String, String>{};
      if (q.isNotEmpty) {
        for (final c in Chats.i.all) {
          final hit = c.find(q);
          if (hit == null && !c.title.toLowerCase().contains(q)) continue;
          chats.add(c);
          if (hit != null) found[c.id] = hit;
        }
      }
      setState(() {
        _done = q;
        _chats = chats.take(40).toList();
        _found = found;
        _threads = q.isEmpty
            ? const []
            : [
                for (final (h, s) in Hubs.i.threads())
                  if (titleOf(s).toLowerCase().contains(q) || baseName(dirOf(s)).toLowerCase().contains(q)) (h, s),
              ].take(40).toList();
      });
    });
  }

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final mq = MediaQuery.paddingOf(context);
    return Scaffold(
      backgroundColor: p.bg,
      body: Column(
        children: [
          Padding(
            padding: EdgeInsets.fromLTRB(8, mq.top + 8, gutter, 6),
            child: Row(
              children: [
                const BackBtn(),
                const SizedBox(width: 4),
                Expanded(child: Field(_q, hint: t('Search chats and threads'), icon: LucideIcons.search, auto: true, onChanged: _run)),
              ],
            ),
          ),
          Expanded(
            child: ListView(
              padding: EdgeInsets.fromLTRB(gutter, 4, gutter, 30 + mq.bottom),
              keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
              children: [
                if (_done.isNotEmpty && _chats.isEmpty && _threads.isEmpty) Empty(LucideIcons.searchX, t('Nothing found'), t('Try other words.')),
                if (_threads.isNotEmpty) ...[
                  Head(t('Threads'), count: _threads.length),
                  Group(children: [for (final (h, s) in _threads) ThreadTile(h, s, icon: true)]),
                ],
                if (_chats.isNotEmpty) ...[
                  Head(t('Chats'), count: _chats.length),
                  Group(children: [for (final c in _chats) ChatTile(c, found: _found[c.id])]),
                ],
                if (_done.isEmpty)
                  Rise(
                    0,
                    child: Padding(
                      padding: const EdgeInsets.only(top: 40),
                      child: Text(t('Everything said in your chats, and the threads on your computers.'), textAlign: TextAlign.center, style: T.sub.copyWith(color: p.text3)),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
