// The Chats tab: every direct chat on this phone, grouped by day, with search, pinning and
// swipe-to-delete. The gradient button starts a new chat.
import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';

import '../ai.dart';
import '../store.dart';
import '../theme.dart';
import '../widgets/badge.dart';
import '../widgets/common.dart';
import '../widgets/logo.dart';
import 'chat.dart';
import 'providers.dart';

class ChatsScreen extends StatefulWidget {
  const ChatsScreen({super.key});
  @override
  State<ChatsScreen> createState() => _ChatsScreenState();
}

class _ChatsScreenState extends State<ChatsScreen> {
  String _query = '';
  final _search = TextEditingController();

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  void _open(Chat? chat, {String? prompt}) {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => ChatScreen(chat: chat, prompt: prompt),
      ),
    );
  }

  Future<void> _menu(Chat c) async {
    final pick = await showModalBottomSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 0, 24, 12),
              child: Text(c.title.isEmpty ? 'New chat' : c.title, maxLines: 2, overflow: TextOverflow.ellipsis, style: Afh.h3()),
            ),
            _sheetItem(ctx, c.pinned ? Icons.push_pin_outlined : Icons.push_pin_rounded, c.pinned ? 'Unpin' : 'Pin to top', 'pin'),
            _sheetItem(ctx, Icons.edit_rounded, 'Rename', 'rename'),
            _sheetItem(ctx, Icons.delete_outline_rounded, 'Delete', 'delete', color: Afh.bad),
            const SizedBox(height: 10),
          ],
        ),
      ),
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
        _delete(c);
    }
  }

  void _delete(Chat c) {
    Chats.i.delete(c);
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: const Text('Chat deleted'),
          action: SnackBarAction(label: 'Undo', textColor: Afh.orange, onPressed: () => Chats.i.restore(c)),
        ),
      );
  }

  @override
  Widget build(BuildContext context) {
    final top = MediaQuery.paddingOf(context).top;
    final bottom = MediaQuery.paddingOf(context).bottom;
    return Stack(
      children: [
        const Positioned.fill(child: Aurora()),
        ListenableBuilder(
          listenable: Listenable.merge([Chats.i, Settings.i]),
          builder: (context, _) {
            final q = _query.toLowerCase();
            final list = Chats.i.all.where((c) => q.isEmpty || c.title.toLowerCase().contains(q) || c.preview.toLowerCase().contains(q)).toList();
            final anyProvider = providers.any((p) => p.ready);
            return CustomScrollView(
              physics: const BouncingScrollPhysics(parent: AlwaysScrollableScrollPhysics()),
              slivers: [
                SliverToBoxAdapter(
                  child: Padding(
                    padding: EdgeInsets.fromLTRB(22, top + 18, 22, 6),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                _greeting(),
                                style: const TextStyle(color: Afh.text3, fontWeight: FontWeight.w600),
                              ).animate().fadeIn(duration: 400.ms),
                              const SizedBox(height: 4),
                              Text('Chats', style: Afh.h1()).animate().fadeIn(delay: 60.ms).moveX(begin: -12, end: 0, curve: Afh.ease),
                            ],
                          ),
                        ),
                        const AfhLogo(width: 64),
                      ],
                    ),
                  ),
                ),
                if (Chats.i.all.isNotEmpty)
                  SliverToBoxAdapter(
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(18, 14, 18, 6),
                      child: TextField(
                        controller: _search,
                        onChanged: (v) => setState(() => _query = v),
                        textInputAction: TextInputAction.search,
                        decoration: InputDecoration(
                          hintText: 'Search chats',
                          prefixIcon: const Icon(Icons.search_rounded, color: Afh.text3),
                          suffixIcon: _query.isEmpty
                              ? null
                              : IconButton(
                                  icon: const Icon(Icons.close_rounded, size: 20),
                                  onPressed: () => setState(() {
                                    _search.clear();
                                    _query = '';
                                  }),
                                ),
                          border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(999),
                            borderSide: const BorderSide(color: Afh.line),
                          ),
                          enabledBorder: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(999),
                            borderSide: const BorderSide(color: Afh.line),
                          ),
                          focusedBorder: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(999),
                            borderSide: const BorderSide(color: Afh.orange),
                          ),
                          contentPadding: const EdgeInsets.symmetric(vertical: 12),
                        ),
                      ),
                    ).animate().fadeIn(delay: 120.ms),
                  ),
                if (!anyProvider)
                  SliverToBoxAdapter(
                    child: _SetupCard(onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ProvidersScreen()))),
                  ),
                if (Chats.i.all.isEmpty)
                  SliverToBoxAdapter(
                    child: _Welcome(
                      onPrompt: (p) => _open(null, prompt: p),
                      enabled: anyProvider,
                    ),
                  )
                else if (list.isEmpty)
                  const SliverToBoxAdapter(
                    child: EmptyState(icon: Icons.search_off_rounded, title: 'Nothing found', text: 'No chat matches that search.'),
                  )
                else
                  ..._sections(list),
                SliverToBoxAdapter(child: SizedBox(height: 170 + bottom)),
              ],
            );
          },
        ),
        Positioned(
          right: 20,
          bottom: 96 + bottom,
          child: Pressable(
            onTap: () => _open(null),
            child: Container(
              height: 58,
              padding: const EdgeInsets.symmetric(horizontal: 22),
              decoration: BoxDecoration(
                gradient: Afh.grad,
                borderRadius: BorderRadius.circular(29),
                boxShadow: [BoxShadow(color: Afh.pink.withValues(alpha: 0.45), blurRadius: 26, offset: const Offset(0, 10), spreadRadius: -6)],
              ),
              child: const Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.edit_square, color: Color(0xFF1A0D05), size: 21),
                  SizedBox(width: 9),
                  Text(
                    'New chat',
                    style: TextStyle(fontFamily: Afh.display, fontWeight: FontWeight.w700, fontSize: 16, color: Color(0xFF1A0D05)),
                  ),
                ],
              ),
            ),
          ).animate().scale(delay: 250.ms, duration: 600.ms, curve: Afh.spring, begin: const Offset(0.5, 0.5)).fadeIn(),
        ),
      ],
    );
  }

  String _greeting() {
    final h = DateTime.now().hour;
    return h < 5
        ? 'Up late'
        : h < 12
        ? 'Good morning'
        : h < 18
        ? 'Good afternoon'
        : 'Good evening';
  }

  List<Widget> _sections(List<Chat> list) {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    String group(Chat c) {
      if (c.pinned) return 'Pinned';
      final d = DateTime(c.updated.year, c.updated.month, c.updated.day);
      final days = today.difference(d).inDays;
      return days <= 0
          ? 'Today'
          : days == 1
          ? 'Yesterday'
          : days < 7
          ? 'This week'
          : 'Earlier';
    }

    final out = <Widget>[];
    String? last;
    var i = 0;
    for (final c in list) {
      final g = group(c);
      if (g != last) {
        out.add(
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(26, 18, 26, 8),
              child: Text(g.toUpperCase(), style: Afh.label),
            ),
          ),
        );
        last = g;
      }
      out.add(
        SliverToBoxAdapter(
          child: _ChatTile(key: ValueKey(c.id), chat: c, index: i++, onTap: () => _open(c), onLongPress: () => _menu(c), onDelete: () => _delete(c)),
        ),
      );
    }
    return out;
  }
}

class _ChatTile extends StatelessWidget {
  const _ChatTile({super.key, required this.chat, required this.index, required this.onTap, required this.onLongPress, required this.onDelete});
  final Chat chat;
  final int index;
  final VoidCallback onTap, onLongPress, onDelete;

  @override
  Widget build(BuildContext context) {
    final p = providerById(chat.provider);
    return Dismissible(
          key: ValueKey('d${chat.id}'),
          direction: DismissDirection.endToStart,
          onDismissed: (_) => onDelete(),
          background: Container(
            margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
            decoration: BoxDecoration(color: Afh.bad.withValues(alpha: 0.18), borderRadius: BorderRadius.circular(22)),
            alignment: Alignment.centerRight,
            padding: const EdgeInsets.only(right: 26),
            child: const Icon(Icons.delete_outline_rounded, color: Afh.bad),
          ),
          child: Pressable(
            onTap: onTap,
            onLongPress: onLongPress,
            child: Container(
              margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
              padding: const EdgeInsets.fromLTRB(14, 14, 16, 14),
              decoration: BoxDecoration(
                color: Afh.surface.withValues(alpha: 0.78),
                borderRadius: BorderRadius.circular(22),
                border: Border.all(color: Afh.line),
              ),
              child: Row(
                children: [
                  ProviderBadge(p, size: 44),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            if (chat.pinned)
                              const Padding(
                                padding: EdgeInsets.only(right: 5),
                                child: Icon(Icons.push_pin_rounded, size: 14, color: Afh.orange),
                              ),
                            Expanded(
                              child: Text(
                                chat.title.isEmpty ? 'New chat' : chat.title,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15.5),
                              ),
                            ),
                            const SizedBox(width: 8),
                            Text(ago(chat.updated), style: const TextStyle(color: Afh.text3, fontSize: 12)),
                          ],
                        ),
                        const SizedBox(height: 4),
                        Text(
                          chat.preview,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(color: Afh.text2, fontSize: 13.5, height: 1.35),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        )
        .animate()
        .fadeIn(delay: (40 * index.clamp(0, 10)).ms, duration: 350.ms)
        .moveY(begin: 14, end: 0, delay: (40 * index.clamp(0, 10)).ms, curve: Afh.ease, duration: 500.ms);
  }
}

class _SetupCard extends StatelessWidget {
  const _SetupCard({required this.onTap});
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
      child: Pressable(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.all(18),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(24),
            gradient: const LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [Color(0x38FFB11F), Color(0x30FF3D8A)]),
            border: Border.all(color: Afh.orange.withValues(alpha: 0.35)),
          ),
          child: Row(
            children: [
              const IconTile(Icons.key_rounded, size: 50),
              const SizedBox(width: 14),
              const Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Add a model provider',
                      style: TextStyle(fontFamily: Afh.display, fontWeight: FontWeight.w700, fontSize: 17),
                    ),
                    SizedBox(height: 3),
                    Text(
                      'Paste an API key from OpenAI, Anthropic, Gemini, OpenRouter… to start chatting.',
                      style: TextStyle(color: Afh.text2, fontSize: 13.5, height: 1.35),
                    ),
                  ],
                ),
              ),
              const Icon(
                Icons.arrow_forward_ios_rounded,
                size: 16,
                color: Afh.text2,
              ).animate(onPlay: (c) => c.repeat(reverse: true)).moveX(begin: 0, end: 4, duration: 700.ms, curve: Curves.easeInOut),
            ],
          ),
        ),
      ),
    ).animate().fadeIn(delay: 150.ms).moveY(begin: 16, end: 0, curve: Afh.ease);
  }
}

const suggestions = [
  (Icons.lightbulb_outline_rounded, 'Explain', 'how vaccines train the immune system'),
  (Icons.mail_outline_rounded, 'Write', 'a friendly follow-up email after an interview'),
  (Icons.flight_takeoff_rounded, 'Plan', 'a relaxed three-day trip to Lisbon'),
  (Icons.code_rounded, 'Code', 'a Python script that renames photos by date'),
];

class _Welcome extends StatelessWidget {
  const _Welcome({required this.onPrompt, required this.enabled});
  final ValueChanged<String> onPrompt;
  final bool enabled;
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 26, 16, 0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 6),
            child: Text('Try asking', style: Afh.h3(Afh.text2)),
          ).animate().fadeIn(delay: 200.ms),
          const SizedBox(height: 12),
          for (final (i, s) in suggestions.indexed)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Pressable(
                onTap: enabled ? () => onPrompt('${s.$2} ${s.$3}') : null,
                child: Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: Afh.surface.withValues(alpha: 0.7),
                    borderRadius: BorderRadius.circular(20),
                    border: Border.all(color: Afh.line),
                  ),
                  child: Row(
                    children: [
                      IconTile(s.$1, size: 40),
                      const SizedBox(width: 14),
                      Expanded(
                        child: Text.rich(
                          TextSpan(
                            children: [
                              TextSpan(
                                text: '${s.$2} ',
                                style: const TextStyle(fontWeight: FontWeight.w700),
                              ),
                              TextSpan(
                                text: s.$3,
                                style: const TextStyle(color: Afh.text2),
                              ),
                            ],
                          ),
                          style: const TextStyle(fontSize: 15, height: 1.35),
                        ),
                      ),
                      const Icon(Icons.north_east_rounded, size: 18, color: Afh.text3),
                    ],
                  ),
                ),
              ),
            ).animate().fadeIn(delay: (260 + i * 70).ms).moveY(begin: 16, end: 0, delay: (260 + i * 70).ms, curve: Afh.ease, duration: 500.ms),
        ],
      ),
    );
  }
}

Widget _sheetItem(BuildContext ctx, IconData icon, String label, String value, {Color? color}) => ListTile(
  contentPadding: const EdgeInsets.symmetric(horizontal: 24),
  leading: Icon(icon, color: color ?? Afh.text2),
  title: Text(
    label,
    style: TextStyle(color: color ?? Afh.text, fontWeight: FontWeight.w500),
  ),
  onTap: () => Navigator.pop(ctx, value),
);

/// A small dialog with one text field.
Future<String?> promptText(BuildContext context, {required String title, String initial = '', String hint = '', int lines = 1, String action = 'Save'}) {
  final ctl = TextEditingController(text: initial);
  return showDialog<String>(
    context: context,
    builder: (ctx) => AlertDialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(26)),
      title: Text(title, style: Afh.h3()),
      content: TextField(
        controller: ctl,
        autofocus: true,
        minLines: lines,
        maxLines: lines == 1 ? 1 : 10,
        decoration: InputDecoration(hintText: hint),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(ctx),
          child: const Text('Cancel', style: TextStyle(color: Afh.text2)),
        ),
        FilledButton(onPressed: () => Navigator.pop(ctx, ctl.text), child: Text(action)),
      ],
    ),
  );
}
