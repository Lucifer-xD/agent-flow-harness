// The Settings tab: providers, the AFH account, how chats behave, and the app itself.
import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:url_launcher/url_launcher.dart';

import '../ai.dart';
import '../main.dart' show appVersion;
import '../remote.dart';
import '../store.dart';
import '../theme.dart';
import '../widgets/badge.dart';
import '../widgets/common.dart';
import '../widgets/logo.dart';
import 'chats.dart' show promptText;
import 'providers.dart';
import 'shell.dart';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final top = MediaQuery.paddingOf(context).top;
    final bottom = MediaQuery.paddingOf(context).bottom;
    return Stack(
      children: [
        const Positioned.fill(child: Aurora(intensity: 0.6)),
        ListenableBuilder(
          listenable: Listenable.merge([Settings.i, Account.i, Chats.i]),
          builder: (context, _) {
            final ready = providers.where((p) => p.ready).toList();
            var n = 0;
            Widget anim(Widget w) {
              final d = (n++ * 50).ms;
              return w.animate().fadeIn(delay: d, duration: 350.ms).moveY(begin: 14, end: 0, delay: d, curve: Afh.ease, duration: 500.ms);
            }

            return ListView(
              physics: const BouncingScrollPhysics(parent: AlwaysScrollableScrollPhysics()),
              padding: EdgeInsets.fromLTRB(16, top + 18, 16, 120 + bottom),
              children: [
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 6),
                  child: Text('Settings', style: Afh.h1()).animate().fadeIn().moveX(begin: -12, end: 0, curve: Afh.ease),
                ),
                const SizedBox(height: 22),
                anim(const _Label('Direct chat')),
                anim(
                  _Group(
                    children: [
                      _Row(
                        icon: Icons.key_rounded,
                        title: 'Providers',
                        sub: ready.isEmpty ? 'Add an API key to start chatting' : ready.map((p) => p.name).join(', '),
                        trailing: ready.isEmpty
                            ? null
                            : SizedBox(
                                width: 18.0 * ready.length.clamp(1, 4) + 10,
                                height: 28,
                                child: Stack(
                                  children: [for (final (i, p) in ready.take(4).indexed) Positioned(left: i * 18.0, child: ProviderBadge(p, size: 28))],
                                ),
                              ),
                        onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ProvidersScreen())),
                      ),
                      _Row(
                        icon: Icons.tune_rounded,
                        title: 'Custom instructions',
                        sub: Settings.i.system.isEmpty ? 'Tell every model how you like answers' : Settings.i.system,
                        onTap: () async {
                          final v = await promptText(
                            context,
                            title: 'Custom instructions',
                            initial: Settings.i.system,
                            hint: 'e.g. Answer briefly. I\'m a web developer.',
                            lines: 5,
                          );
                          if (v != null) Settings.i.system = v.trim();
                        },
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 22),
                anim(const _Label('Remote control')),
                anim(
                  _Group(
                    children: [
                      if (Account.i.signedIn) ...[
                        _Row(
                          icon: Icons.person_rounded,
                          title: Account.i.email,
                          sub: '${Account.i.computers.length} computer${Account.i.computers.length == 1 ? '' : 's'} in your AFH account',
                          onTap: () => Shell.tab.value = 1,
                        ),
                        _Row(
                          icon: Icons.manage_accounts_rounded,
                          title: 'Manage account',
                          sub: 'Password, computers and deleting the account',
                          external: true,
                          onTap: () => launchUrl(Uri.parse('$server/account'), mode: LaunchMode.externalApplication),
                        ),
                        _Row(
                          icon: Icons.logout_rounded,
                          title: 'Sign out',
                          color: Afh.bad,
                          onTap: () async {
                            if (await _confirm(context, 'Sign out?', 'Your computers stay in your account. Direct chats aren\'t affected.', 'Sign out')) {
                              Account.i.signOut();
                            }
                          },
                        ),
                      ] else
                        _Row(
                          icon: Icons.login_rounded,
                          title: 'Sign in to AFH',
                          sub: 'Reach AFH on your computers from this phone',
                          onTap: () => Shell.tab.value = 1,
                        ),
                    ],
                  ),
                ),
                const SizedBox(height: 22),
                anim(const _Label('App')),
                anim(
                  _Group(
                    children: [
                      _Row(
                        icon: Icons.delete_sweep_rounded,
                        title: 'Delete all chats',
                        sub: '${Chats.i.all.length} chat${Chats.i.all.length == 1 ? '' : 's'} on this phone',
                        color: Afh.bad,
                        onTap: Chats.i.all.isEmpty
                            ? null
                            : () async {
                                if (await _confirm(
                                  context,
                                  'Delete all chats?',
                                  'This removes every direct chat from this phone. It can\'t be undone.',
                                  'Delete all',
                                )) {
                                  Chats.i.deleteAll();
                                  if (context.mounted) showToast(context, 'All chats deleted');
                                }
                              },
                      ),
                      _Row(
                        icon: Icons.replay_rounded,
                        title: 'Show the welcome again',
                        onTap: () {
                          Settings.i.onboarded = false;
                          showToast(context, 'You\'ll see it next time the app opens');
                        },
                      ),
                      _Row(
                        icon: Icons.language_rounded,
                        title: 'agentflowharness.com',
                        external: true,
                        onTap: () => launchUrl(Uri.parse(server), mode: LaunchMode.externalApplication),
                      ),
                      _Row(
                        icon: Icons.download_rounded,
                        title: 'Get AFH for your computer',
                        external: true,
                        onTap: () => launchUrl(Uri.parse('$server/download'), mode: LaunchMode.externalApplication),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 34),
                anim(
                  Column(
                    children: [
                      const AfhLogo(width: 72, intro: false),
                      const SizedBox(height: 10),
                      const Text(
                        'AFH $appVersion',
                        style: TextStyle(fontWeight: FontWeight.w700, color: Afh.text2),
                      ),
                      const SizedBox(height: 4),
                      const Text('Keys and chats stay on this phone. No tracking.', style: TextStyle(color: Afh.text3, fontSize: 12.5)),
                    ],
                  ),
                ),
              ],
            );
          },
        ),
      ],
    );
  }
}

Future<bool> _confirm(BuildContext context, String title, String text, String action) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(26)),
      title: Text(title, style: Afh.h3()),
      content: Text(text, style: const TextStyle(color: Afh.text2, height: 1.4)),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(ctx, false),
          child: const Text('Cancel', style: TextStyle(color: Afh.text2)),
        ),
        FilledButton(
          style: FilledButton.styleFrom(backgroundColor: Afh.bad),
          onPressed: () => Navigator.pop(ctx, true),
          child: Text(action),
        ),
      ],
    ),
  );
  return ok == true;
}

class _Label extends StatelessWidget {
  const _Label(this.text);
  final String text;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(10, 0, 10, 8),
    child: Text(text.toUpperCase(), style: Afh.label),
  );
}

class _Group extends StatelessWidget {
  const _Group({required this.children});
  final List<Widget> children;
  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: Afh.surface.withValues(alpha: 0.85),
        borderRadius: BorderRadius.circular(24),
        border: Border.all(color: Afh.line),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: [
          for (var i = 0; i < children.length; i++) ...[if (i > 0) const Divider(indent: 64), children[i]],
        ],
      ),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row({required this.icon, required this.title, this.sub, this.onTap, this.trailing, this.color, this.external = false});
  final IconData icon;
  final String title;
  final String? sub;
  final VoidCallback? onTap;
  final Widget? trailing;
  final Color? color;
  final bool external;
  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 13),
        child: Row(
          children: [
            Container(
              width: 36,
              height: 36,
              decoration: BoxDecoration(
                color: color?.withValues(alpha: 0.12),
                gradient: color == null ? Afh.gradSoft : null,
                borderRadius: BorderRadius.circular(11),
              ),
              child: Icon(icon, size: 19, color: color ?? const Color(0xFFFFB48A)),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontWeight: FontWeight.w600, fontSize: 15, color: color ?? Afh.text),
                  ),
                  if (sub != null && sub!.isNotEmpty) ...[
                    const SizedBox(height: 2),
                    Text(
                      sub!,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(color: Afh.text3, fontSize: 13),
                    ),
                  ],
                ],
              ),
            ),
            if (trailing != null) ...[const SizedBox(width: 8), trailing!],
            const SizedBox(width: 6),
            Icon(external ? Icons.open_in_new_rounded : Icons.chevron_right_rounded, size: external ? 17 : 22, color: Afh.text3),
          ],
        ),
      ),
    );
  }
}
