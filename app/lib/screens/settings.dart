// Settings: the AFH account, appearance, providers and instructions, the phone's data, and about.
import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'package:url_launcher/url_launcher.dart';

import '../ai.dart';
import '../main.dart' show appVersion;
import '../palettes.dart';
import '../remote.dart';
import '../store.dart';
import '../theme.dart';
import '../widgets/badge.dart';
import '../widgets/common.dart';
import '../widgets/logo.dart';
import 'computers.dart';
import 'providers.dart';

void _go(BuildContext context, Widget page) => Navigator.of(context).push(MaterialPageRoute(builder: (_) => page));

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.paddingOf(context).bottom;
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListenableBuilder(
        listenable: Listenable.merge([Settings.i, Account.i, Chats.i]),
        builder: (context, _) {
          final ready = providers.where((p) => p.ready).toList();
          final a = Account.i;
          final s = Settings.i;
          final mode = switch (s.themeMode) {
            'dark' => 'Dark',
            'light' => 'Light',
            _ => 'System',
          };
          var n = 0;
          return ListView(
            padding: EdgeInsets.fromLTRB(16, 4, 16, 24 + bottom),
            children: [
              Group(
                inset: 66,
                children: [
                  a.signedIn
                      ? Tile(
                          leading: Avatar(a.email, size: 36),
                          title: a.email,
                          subtitle: '${a.computers.length} computer${a.computers.length == 1 ? '' : 's'} in your AFH account',
                          onTap: () => _go(context, const ComputersScreen()),
                        )
                      : Tile(
                          leading: IconTile(LucideIcons.userRound, size: 36),
                          title: 'Sign in to AFH',
                          subtitle: 'Reach AFH on your computers from this phone',
                          onTap: () => _go(context, const ComputersScreen()),
                        ),
                ],
              ).enter(n++),
              SectionLabel('General').enter(n++),
              Group(
                children: [
                  Tile(icon: LucideIcons.palette, title: 'Appearance', subtitle: '$mode · ${Afh.p.name}', onTap: () => _go(context, const AppearanceScreen())),
                  Tile(
                    icon: LucideIcons.keyRound,
                    title: 'Providers',
                    subtitle: ready.isEmpty ? 'Add an API key to start chatting' : ready.map((p) => p.name).join(', '),
                    trailing: ready.isEmpty
                        ? null
                        : SizedBox(
                            width: 16.0 * ready.length.clamp(1, 4) + 10,
                            height: 26,
                            child: Stack(
                              children: [
                                for (final (i, p) in ready.take(4).indexed)
                                  Positioned(
                                    left: i * 16.0,
                                    child: Container(
                                      decoration: BoxDecoration(
                                        shape: BoxShape.circle,
                                        border: Border.all(color: Afh.surface, width: 2),
                                      ),
                                      child: ProviderBadge(p, size: 22),
                                    ),
                                  ),
                              ],
                            ),
                          ),
                    chevron: true,
                    onTap: () => _go(context, const ProvidersScreen()),
                  ),
                  Tile(
                    icon: LucideIcons.slidersHorizontal,
                    title: 'Custom instructions',
                    subtitle: s.system.isEmpty ? 'Tell every model how you like answers' : s.system,
                    onTap: () async {
                      final v = await promptText(
                        context,
                        title: 'Custom instructions',
                        initial: s.system,
                        hint: 'e.g. Answer briefly. I\'m a web developer.',
                        lines: 5,
                      );
                      if (v != null) s.system = v.trim();
                    },
                  ),
                  Tile(
                    icon: LucideIcons.wandSparkles,
                    title: 'Tools',
                    subtitle: s.tools ? 'Web search, weather, location, reminders, calendar, contacts, your PC…' : 'Off: models only chat',
                    trailing: Switch.adaptive(value: s.tools, onChanged: (v) => s.tools = v),
                    onTap: () => s.tools = !s.tools,
                  ),
                  Tile(
                    icon: LucideIcons.brain,
                    title: 'Memory',
                    subtitle: s.memory.isEmpty ? 'Ask "remember that…" in any chat' : '${s.memory.length} thing${s.memory.length == 1 ? '' : 's'} remembered',
                    chevron: true,
                    onTap: () => _go(context, const MemoryScreen()),
                  ),
                ],
              ).enter(n++),
              if (a.signedIn) ...[
                SectionLabel('Account').enter(n++),
                Group(
                  children: [
                    Tile(
                      icon: LucideIcons.circleUser,
                      title: 'Manage account',
                      subtitle: 'Password, computers and deleting the account',
                      trailing: Icon(LucideIcons.externalLink, size: 16, color: Afh.text3),
                      onTap: () => launchUrl(Uri.parse('$server/account'), mode: LaunchMode.externalApplication),
                    ),
                    Tile(
                      icon: LucideIcons.logOut,
                      title: 'Sign out',
                      danger: true,
                      onTap: () async {
                        if (await confirm(
                          context,
                          title: 'Sign out?',
                          text: 'Your computers stay in your account. Direct chats aren\'t affected.',
                          action: 'Sign out',
                          danger: true,
                        )) {
                          Account.i.signOut();
                        }
                      },
                    ),
                  ],
                ).enter(n++),
              ],
              SectionLabel('Data').enter(n++),
              Group(
                children: [
                  Tile(
                    icon: LucideIcons.trash2,
                    title: 'Delete all chats',
                    subtitle: '${Chats.i.all.length} chat${Chats.i.all.length == 1 ? '' : 's'} on this phone',
                    danger: true,
                    onTap: Chats.i.all.isEmpty
                        ? null
                        : () async {
                            if (await confirm(
                              context,
                              title: 'Delete all chats?',
                              text: 'This removes every direct chat from this phone. It can\'t be undone.',
                              action: 'Delete all',
                              danger: true,
                            )) {
                              Chats.i.deleteAll();
                              if (context.mounted) showToast(context, 'All chats deleted');
                            }
                          },
                  ),
                  Tile(
                    icon: LucideIcons.history,
                    title: 'Show the welcome again',
                    chevron: false,
                    onTap: () {
                      s.onboarded = false;
                      showToast(context, 'You\'ll see it next time the app opens');
                    },
                  ),
                ],
              ).enter(n++),
              SectionLabel('About').enter(n++),
              Group(
                children: [
                  Tile(
                    icon: LucideIcons.globe,
                    title: 'agentflowharness.com',
                    trailing: Icon(LucideIcons.externalLink, size: 16, color: Afh.text3),
                    onTap: () => launchUrl(Uri.parse(server), mode: LaunchMode.externalApplication),
                  ),
                  Tile(
                    icon: LucideIcons.monitor,
                    title: 'Get AFH for your computer',
                    trailing: Icon(LucideIcons.externalLink, size: 16, color: Afh.text3),
                    onTap: () => launchUrl(Uri.parse('$server/download'), mode: LaunchMode.externalApplication),
                  ),
                ],
              ).enter(n++),
              const SizedBox(height: 34),
              Column(
                children: [
                  const AfhLogo(width: 52, intro: false),
                  const SizedBox(height: 12),
                  Text(
                    'AFH $appVersion',
                    style: TextStyle(fontWeight: FontWeight.w600, color: Afh.text2, fontSize: 13.5),
                  ),
                  const SizedBox(height: 3),
                  Text('Keys and chats stay on this phone. No tracking.', style: TextStyle(color: Afh.text3, fontSize: 12.5)),
                ],
              ).enter(n++),
            ],
          );
        },
      ),
    );
  }
}

/// Light, dark or follow the phone, and a theme for each: the same themes as AFH on the PC.
class AppearanceScreen extends StatelessWidget {
  const AppearanceScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.paddingOf(context).bottom;
    return Scaffold(
      appBar: AppBar(title: const Text('Appearance')),
      body: ListenableBuilder(
        listenable: Settings.i,
        builder: (context, _) {
          final s = Settings.i;
          final mode = s.themeMode;
          return ListView(
            padding: EdgeInsets.fromLTRB(16, 4, 16, 24 + bottom),
            children: [
              const _Preview().enter(0),
              const SizedBox(height: 18),
              _Segmented(
                value: mode,
                options: const [('system', 'System', LucideIcons.sunMoon), ('dark', 'Dark', LucideIcons.moon), ('light', 'Light', LucideIcons.sun)],
                onChanged: (v) => s.setTheme(mode: v),
              ).enter(1),
              // the grid for the look on screen now comes first
              for (final (i, dark) in (Afh.p.dark ? [true, false] : [false, true]).indexed)
                if (mode == 'system' || (mode == 'dark') == dark) ...[
                  SectionLabel(mode != 'system' ? 'Theme' : (dark ? 'When your phone is dark' : 'When your phone is light')).enter(2 + i),
                  _ThemeGrid(
                    dark: dark,
                    picked: dark ? s.darkTheme : s.lightTheme,
                    onPick: (id) => dark ? s.setTheme(dark: id) : s.setTheme(light: id),
                  ).enter(2 + i),
                ],
            ],
          );
        },
      ),
    );
  }
}

/// A little chat drawn in the current theme.
class _Preview extends StatelessWidget {
  const _Preview();
  @override
  Widget build(BuildContext context) {
    return AnimatedContainer(
      duration: Afh.med,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Afh.surface,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: Afh.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Align(
            alignment: Alignment.centerRight,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
              decoration: BoxDecoration(
                color: Afh.p.bubble,
                borderRadius: const BorderRadius.only(
                  topLeft: Radius.circular(18),
                  topRight: Radius.circular(18),
                  bottomLeft: Radius.circular(18),
                  bottomRight: Radius.circular(6),
                ),
              ),
              child: Text('Make the nav bar feel native', style: TextStyle(fontSize: 14, color: Afh.text)),
            ),
          ),
          const SizedBox(height: 10),
          Text(
            'Done: icons and labels now sit on one baseline, and the active tab uses your accent.',
            style: TextStyle(fontSize: 14, height: 1.45, color: Afh.text2),
          ),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.fromLTRB(14, 6, 6, 6),
            decoration: BoxDecoration(
              color: Afh.bg,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: Afh.line),
            ),
            child: Row(
              children: [
                Expanded(
                  child: Text('Message AFH', style: TextStyle(fontSize: 14, color: Afh.text3)),
                ),
                Container(
                  width: 30,
                  height: 30,
                  decoration: BoxDecoration(color: Afh.accent, shape: BoxShape.circle),
                  child: Icon(LucideIcons.arrowUp, size: 16, color: Afh.onAccent),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _Segmented extends StatelessWidget {
  const _Segmented({required this.value, required this.options, required this.onChanged});
  final String value;
  final List<(String, String, IconData)> options;
  final ValueChanged<String> onChanged;
  @override
  Widget build(BuildContext context) {
    final i = options.indexWhere((o) => o.$1 == value).clamp(0, options.length - 1);
    return Container(
      height: 42,
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        color: Afh.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Afh.line),
      ),
      child: LayoutBuilder(
        builder: (context, box) {
          final w = box.maxWidth / options.length;
          return Stack(
            children: [
              AnimatedPositioned(
                duration: Afh.med,
                curve: Afh.ease,
                left: w * i,
                top: 0,
                bottom: 0,
                width: w,
                child: Container(
                  decoration: BoxDecoration(color: Afh.surface3, borderRadius: BorderRadius.circular(9)),
                ),
              ),
              Positioned.fill(
                child: Row(
                  children: [
                    for (final o in options)
                      Expanded(
                        child: Semantics(
                          button: true,
                          selected: o.$1 == value,
                          child: Pressable(
                            onTap: () => onChanged(o.$1),
                            scale: 0.96,
                            child: Row(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                Icon(o.$3, size: 15, color: o.$1 == value ? Afh.text : Afh.text3),
                                const SizedBox(width: 6),
                                Text(
                                  o.$2,
                                  style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600, color: o.$1 == value ? Afh.text : Afh.text3),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}

class _ThemeGrid extends StatelessWidget {
  const _ThemeGrid({required this.dark, required this.picked, required this.onPick});
  final bool dark;
  final String picked;
  final ValueChanged<String> onPick;
  @override
  Widget build(BuildContext context) {
    final list = palettes.where((p) => p.dark == dark).toList();
    return GridView.builder(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(crossAxisCount: 3, mainAxisSpacing: 14, crossAxisSpacing: 10, childAspectRatio: 0.98),
      itemCount: list.length,
      itemBuilder: (_, i) => _Swatch(p: list[i], on: list[i].id == picked || (picked.isEmpty && i == 0), onTap: () => onPick(list[i].id)),
    );
  }
}

class _Swatch extends StatelessWidget {
  const _Swatch({required this.p, required this.on, required this.onTap});
  final Palette p;
  final bool on;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      selected: on,
      label: '${p.name} theme',
      child: Pressable(
        onTap: onTap,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(
              child: AnimatedContainer(
                duration: Afh.fast,
                padding: const EdgeInsets.all(2.5),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: on ? Afh.accent : Colors.transparent, width: 2),
                ),
                child: Container(
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: p.bg,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: p.line),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      FractionallySizedBox(
                        widthFactor: 0.62,
                        child: Container(
                          height: 6,
                          decoration: BoxDecoration(color: p.surface3, borderRadius: BorderRadius.circular(3)),
                        ),
                      ),
                      Align(
                        alignment: Alignment.centerRight,
                        child: Container(
                          width: 34,
                          height: 10,
                          decoration: BoxDecoration(color: p.bubble, borderRadius: BorderRadius.circular(5)),
                        ),
                      ),
                      Row(
                        children: [
                          Expanded(
                            child: Container(
                              height: 6,
                              margin: const EdgeInsets.only(right: 18),
                              decoration: BoxDecoration(color: p.line2, borderRadius: BorderRadius.circular(3)),
                            ),
                          ),
                          Container(
                            width: 16,
                            height: 16,
                            decoration: BoxDecoration(color: p.accent, shape: BoxShape.circle),
                            child: on ? Icon(LucideIcons.check, size: 10, color: p.onAccent) : null,
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            ),
            const SizedBox(height: 6),
            Text(
              p.name,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12.5, fontWeight: on ? FontWeight.w600 : FontWeight.w500, color: on ? Afh.text : Afh.text2),
            ),
          ],
        ),
      ),
    );
  }
}

/// What the assistant was asked to remember; it's added to every chat.
class MemoryScreen extends StatelessWidget {
  const MemoryScreen({super.key});
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Memory'),
        actions: [
          IconBtn(
            LucideIcons.plus,
            tooltip: 'Add',
            onTap: () async {
              final v = await promptText(context, title: 'Remember', hint: "e.g. I live in Cairo and I'm vegetarian");
              if (v != null && v.trim().isNotEmpty) Settings.i.memory = [...Settings.i.memory, v.trim()];
            },
          ),
          const SizedBox(width: 6),
        ],
      ),
      body: ListenableBuilder(
        listenable: Settings.i,
        builder: (context, _) {
          final m = Settings.i.memory;
          if (m.isEmpty) {
            return const EmptyState(
              icon: LucideIcons.brain,
              title: 'Nothing remembered yet',
              text: 'Tell AFH "remember that…" in a chat, or add something with +. It goes along with every chat on this phone.',
            );
          }
          return ListView(
            padding: EdgeInsets.fromLTRB(16, 8, 16, 30 + MediaQuery.paddingOf(context).bottom),
            children: [
              Group(
                inset: 16,
                children: [
                  for (final f in m)
                    Tile(
                      title: f,
                      trailing: IconBtn(
                        LucideIcons.x,
                        tooltip: 'Forget',
                        size: 36,
                        iconSize: 16,
                        color: Afh.text3,
                        onTap: () => Settings.i.memory = [...m]..remove(f),
                      ),
                    ),
                ],
              ),
            ],
          );
        },
      ),
    );
  }
}
