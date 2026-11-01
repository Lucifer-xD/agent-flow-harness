// The app's frame: it opens straight into a chat, and the drawer on the left holds chat history,
// Computers and Settings.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../remote.dart';
import '../store.dart';
import '../theme.dart';
import '../widgets/common.dart';
import 'chat.dart';
import 'computers.dart';
import 'settings.dart';

class Home extends StatefulWidget {
  const Home({super.key});
  @override
  State<Home> createState() => _HomeState();
}

class _HomeState extends State<Home> with WidgetsBindingObserver {
  final _scaffold = GlobalKey<ScaffoldState>();
  Chat? _chat; // the chat on screen; null for a new one
  int _gen = 0; // bumps whenever a different chat is opened, so the chat view starts fresh
  Timer? _poll;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    Account.i.refresh();
    _poll = Timer.periodic(const Duration(seconds: 30), (_) => Account.i.refresh());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _poll?.cancel();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) Account.i.refresh();
  }

  void _open(Chat? c) {
    _scaffold.currentState?.closeDrawer();
    if (identical(c, _chat) && c != null) return;
    setState(() {
      _chat = c;
      _gen++;
    });
  }

  void _push(Widget page) {
    _scaffold.currentState?.closeDrawer();
    Navigator.of(context).push(MaterialPageRoute(builder: (_) => page));
  }

  @override
  Widget build(BuildContext context) {
    final w = MediaQuery.sizeOf(context).width;
    return Scaffold(
      key: _scaffold,
      resizeToAvoidBottomInset: false, // the chat inside handles the keyboard itself
      drawerScrimColor: Colors.black.withValues(alpha: Afh.p.dark ? 0.5 : 0.25),
      drawerEdgeDragWidth: w * 0.18,
      onDrawerChanged: (open) {
        if (open) {
          FocusManager.instance.primaryFocus?.unfocus();
          HapticFeedback.selectionClick();
        }
      },
      drawer: AppDrawer(
        current: _chat,
        onOpen: _open,
        onComputers: () => _push(const ComputersScreen()),
        onSettings: () => _push(const SettingsScreen()),
      ),
      body: ChatScreen(
        key: ValueKey(_gen),
        chat: _chat,
        onMenu: () => _scaffold.currentState?.openDrawer(),
        onNew: () => _open(null),
        onStarted: (c) => setState(() => _chat = c),
        onComputers: () => _push(const ComputersScreen()),
      ),
    );
  }
}

class AppDrawer extends StatefulWidget {
  const AppDrawer({super.key, required this.current, required this.onOpen, required this.onComputers, required this.onSettings});
  final Chat? current;
  final ValueChanged<Chat?> onOpen;
  final VoidCallback onComputers, onSettings;
  @override
  State<AppDrawer> createState() => _AppDrawerState();
}

class _AppDrawerState extends State<AppDrawer> {
  final _search = TextEditingController();
  String _q = '';

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  Future<void> _menu(Chat c) async {
    final pick = await showActions<String>(
      context,
      title: c.title.isEmpty ? 'New chat' : c.title,
      actions: [
        SheetAction(c.pinned ? LucideIcons.pinOff : LucideIcons.pin, c.pinned ? 'Unpin' : 'Pin to top', 'pin'),
        const SheetAction(LucideIcons.pencil, 'Rename', 'rename'),
        const SheetAction(LucideIcons.trash2, 'Delete', 'delete', danger: true),
      ],
    );
    if (!mounted || pick == null) return;
    switch (pick) {
      case 'pin':
        c.pinned = !c.pinned;
        Chats.i.save(c, now: true);
      case 'rename':
        final name = await promptText(context, title: 'Rename chat', initial: c.title, hint: 'Chat name');
        if (name != null && name.trim().isNotEmpty) {
          c.title = name.trim();
          Chats.i.save(c, now: true);
        }
      case 'delete':
        final open = identical(c, widget.current);
        Chats.i.delete(c);
        if (open) widget.onOpen(null);
        if (!mounted) return;
        ScaffoldMessenger.of(context)
          ..hideCurrentSnackBar()
          ..showSnackBar(
            SnackBar(
              content: const Text('Chat deleted'),
              action: SnackBarAction(label: 'Undo', onPressed: () => Chats.i.restore(c)),
            ),
          );
    }
  }

  @override
  Widget build(BuildContext context) {
    final top = MediaQuery.paddingOf(context).top;
    final bottom = MediaQuery.paddingOf(context).bottom;
    final w = MediaQuery.sizeOf(context).width;
    return Drawer(
      width: (w * 0.86).clamp(0, 360),
      backgroundColor: Afh.bg2,
      surfaceTintColor: Colors.transparent,
      shape: Border(right: BorderSide(color: Afh.line)),
      child: ListenableBuilder(
        listenable: Listenable.merge([Chats.i, Account.i, Settings.i]),
        builder: (context, _) {
          final q = _q.toLowerCase();
          final list = Chats.i.all.where((c) => q.isEmpty || c.title.toLowerCase().contains(q) || c.preview.toLowerCase().contains(q)).toList();
          final online = Account.i.computers.where((c) => c.online).length;
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              SizedBox(height: top + 10),
              Padding(
                padding: const EdgeInsets.fromLTRB(14, 0, 14, 6),
                child: Row(
                  children: [
                    Expanded(
                      child: SizedBox(
                        height: 40,
                        child: TextField(
                          controller: _search,
                          onChanged: (v) => setState(() => _q = v),
                          textInputAction: TextInputAction.search,
                          style: const TextStyle(fontSize: 15),
                          decoration: InputDecoration(
                            hintText: 'Search',
                            isDense: true,
                            fillColor: Afh.surface,
                            prefixIcon: Icon(LucideIcons.search, size: 17, color: Afh.text3),
                            prefixIconConstraints: const BoxConstraints(minWidth: 40),
                            suffixIcon: _q.isEmpty
                                ? null
                                : IconBtn(
                                    LucideIcons.x,
                                    size: 36,
                                    iconSize: 16,
                                    color: Afh.text3,
                                    onTap: () => setState(() {
                                      _search.clear();
                                      _q = '';
                                    }),
                                  ),
                            contentPadding: const EdgeInsets.symmetric(vertical: 10),
                            border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
                            enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
                            focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: Afh.line2)),
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              _NavRow(icon: LucideIcons.squarePen, label: 'New chat', onTap: () => widget.onOpen(null)),
              _NavRow(
                icon: LucideIcons.laptop,
                label: 'Computers',
                onTap: widget.onComputers,
                trailing: !Account.i.signedIn
                    ? null
                    : online > 0
                    ? Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          PulseDot(color: Afh.good, size: 7),
                          Text('$online online', style: TextStyle(fontSize: 12.5, color: Afh.text3)),
                        ],
                      )
                    : null,
              ),
              const SizedBox(height: 6),
              Expanded(
                child: list.isEmpty
                    ? Center(
                        child: Padding(
                          padding: const EdgeInsets.all(28),
                          child: Text(
                            Chats.i.all.isEmpty ? 'Your chats will show up here.' : 'No chat matches "$_q".',
                            textAlign: TextAlign.center,
                            style: TextStyle(color: Afh.text3, fontSize: 13.5),
                          ),
                        ),
                      )
                    : ListView(padding: const EdgeInsets.fromLTRB(8, 0, 8, 12), children: _history(list)),
              ),
              Container(
                decoration: BoxDecoration(border: Border(top: BorderSide(color: Afh.line))),
                padding: EdgeInsets.fromLTRB(8, 6, 8, bottom > 0 ? bottom : 10),
                child: _AccountRow(onTap: widget.onSettings),
              ),
            ],
          );
        },
      ),
    );
  }

  List<Widget> _history(List<Chat> list) {
    final out = <Widget>[];
    String? last;
    for (final c in list) {
      final g = c.pinned ? 'Pinned' : dayGroup(c.updated);
      if (g != last) {
        out.add(SectionLabel(g, padding: const EdgeInsets.fromLTRB(12, 16, 12, 6)));
        last = g;
      }
      final on = widget.current != null && c.id == widget.current!.id;
      out.add(
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 1),
          child: Material(
            color: on ? Afh.surface2 : Colors.transparent,
            borderRadius: BorderRadius.circular(10),
            child: InkWell(
              borderRadius: BorderRadius.circular(10),
              onTap: () => widget.onOpen(c),
              onLongPress: () => _menu(c),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                child: Row(
                  children: [
                    if (c.pinned) ...[Icon(LucideIcons.pin, size: 13, color: Afh.text3), const SizedBox(width: 8)],
                    Expanded(
                      child: Text(
                        c.title.isEmpty ? 'New chat' : c.title,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontSize: 14.5, color: on ? Afh.text : Afh.text2, fontWeight: on ? FontWeight.w500 : FontWeight.w400),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      );
    }
    return out;
  }
}

class _NavRow extends StatelessWidget {
  const _NavRow({required this.icon, required this.label, required this.onTap, this.trailing});
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final Widget? trailing;
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8),
      child: Material(
        color: Colors.transparent,
        borderRadius: BorderRadius.circular(10),
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
            child: Row(
              children: [
                Icon(icon, size: 19, color: Afh.text),
                const SizedBox(width: 14),
                Expanded(child: Text(label, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w500, color: Afh.text))),
                ?trailing,
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _AccountRow extends StatelessWidget {
  const _AccountRow({required this.onTap});
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final a = Account.i;
    return Material(
      color: Colors.transparent,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
          child: Row(
            children: [
              a.signedIn ? Avatar(a.email, size: 32) : IconTile(LucideIcons.userRound, size: 32),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      a.signedIn ? a.email : 'Settings',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w500, color: Afh.text),
                    ),
                    Text(a.signedIn ? 'AFH account' : 'Not signed in', style: TextStyle(fontSize: 12.5, color: Afh.text3)),
                  ],
                ),
              ),
              Icon(LucideIcons.settings, size: 19, color: Afh.text2),
              const SizedBox(width: 4),
            ],
          ),
        ),
      ),
    );
  }
}
