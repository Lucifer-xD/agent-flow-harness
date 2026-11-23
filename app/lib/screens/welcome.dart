// The first minute: what AFH is here, and the two things worth connecting.
import 'package:flutter/material.dart';

import '../core/ai.dart';
import '../core/l10n.dart';
import '../core/relay.dart';
import '../core/store.dart';
import '../ui/badge.dart';
import '../ui/kit.dart';
import '../ui/look.dart';
import '../ui/mark.dart';
import '../ui/motion.dart';
import 'account.dart';
import 'providers.dart';

class Welcome extends StatefulWidget {
  const Welcome({super.key});
  @override
  State<Welcome> createState() => _WelcomeState();
}

class _WelcomeState extends State<Welcome> {
  final _pages = PageController();
  int _at = 0;

  @override
  void dispose() {
    _pages.dispose();
    super.dispose();
  }

  void _next() {
    if (_at < 2) {
      _pages.nextPage(duration: const Duration(milliseconds: 520), curve: Curves.easeOutQuint);
    } else {
      Settings.i.onboarded = true;
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final mq = MediaQuery.paddingOf(context);
    return Scaffold(
      backgroundColor: p.bg,
      body: Column(
        children: [
          SizedBox(height: mq.top + 10),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: gutter),
            child: Row(
              children: [
                for (var i = 0; i < 3; i++)
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 3),
                      child: AnimatedContainer(
                        duration: slow,
                        curve: Curves.easeOutQuint,
                        height: 3,
                        decoration: BoxDecoration(color: i <= _at ? p.text : p.fill2, borderRadius: BorderRadius.circular(2)),
                      ),
                    ),
                  ),
              ],
            ),
          ),
          Expanded(
            child: PageView(
              controller: _pages,
              onPageChanged: (i) => setState(() => _at = i),
              children: const [_Hello(), _Work(), _Connect()],
            ),
          ),
          Padding(
            padding: EdgeInsets.fromLTRB(gutter, 8, gutter, 18 + mq.bottom),
            child: ListenableBuilder(
              listenable: Listenable.merge([Settings.i, Account.i]),
              builder: (_, _) => Btn(
                _at < 2 ? t('Continue') : (providers.any((x) => x.ready) || Account.i.signedIn ? t('Start') : t('Look around first')),
                kind: _at == 2 && !providers.any((x) => x.ready) && !Account.i.signedIn ? Kind.soft : Kind.main,
                onTap: _next,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _Text extends StatelessWidget {
  const _Text(this.title, this.text);
  final String title, text;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(gutter + 4, 0, gutter + 4, 26),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Rise(3, child: Text(title, style: T.display.copyWith(color: context.p.text, fontSize: 34))),
        const SizedBox(height: 12),
        Rise(4, child: Text(text, style: T.body.copyWith(color: context.p.text2))),
      ],
    ),
  );
}

class _Hello extends StatelessWidget {
  const _Hello();
  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      const Expanded(child: Center(child: AfhLogo(width: 190))),
      _Text(t('AFH,\nin your pocket'), t('Every model you use in one place, with photos, files and your voice. And your computer, wherever you are.')),
    ],
  );
}

class _Work extends StatelessWidget {
  const _Work();

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    Widget step(IconData i, String s, {bool done = true}) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        children: [
          Icon(i, size: 15, color: p.text3),
          const SizedBox(width: 11),
          Expanded(child: Text(s, style: T.small.copyWith(color: p.text2))),
          if (done) Icon(LucideIcons.check, size: 14, color: p.good),
        ],
      ),
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: gutter + 4),
              child: Rise(
                0,
                dy: 30,
                child: Panel(
                  pad: const EdgeInsets.fromLTRB(18, 18, 18, 18),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(t('Fix the checkout total'), style: T.h3.copyWith(color: p.text)),
                      const SizedBox(height: 2),
                      Text('shop · Studio PC', style: T.small.copyWith(color: p.text3)),
                      const SizedBox(height: 12),
                      step(LucideIcons.fileText, t('Read {}', 'pricing.py')),
                      step(LucideIcons.pencil, t('Edited {}', 'pricing.py')),
                      step(LucideIcons.terminal, t('Wants to run the tests'), done: false),
                      const SizedBox(height: 12),
                      const StrandLine(height: 3),
                      const SizedBox(height: 16),
                      IgnorePointer(
                        child: Row(
                          children: [
                            Expanded(child: Btn(t('Deny'), kind: Kind.soft, small: true, onTap: () {})),
                            const SizedBox(width: 10),
                            Expanded(child: Btn(t('Allow'), small: true, onTap: () {})),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
        _Text(t('Work goes on\nwithout the desk'), t('Start agents on your own computer, watch each step, answer what they ask, and see exactly what changed.')),
      ],
    );
  }
}

class _Connect extends StatelessWidget {
  const _Connect();
  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: Listenable.merge([Settings.i, Account.i]),
    builder: (context, _) {
      final p = context.p;
      final ready = [for (final x in providers) if (x.ready) x];
      Widget card(int i, {required IconData icon, required String title, required String sub, required bool done, required VoidCallback onTap, Widget? under}) => Rise(
        i,
        child: Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Panel(
            onTap: onTap,
            pad: const EdgeInsets.fromLTRB(18, 18, 18, 18),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(icon, size: 24, color: p.text),
                    const Spacer(),
                    AnimatedSwitcher(
                      duration: med,
                      transitionBuilder: (c, a) => ScaleTransition(scale: CurvedAnimation(parent: a, curve: springy), child: c),
                      child: done
                          ? Container(
                              key: const ValueKey(1),
                              width: 26,
                              height: 26,
                              decoration: BoxDecoration(color: p.good, shape: BoxShape.circle),
                              child: Icon(LucideIcons.check, size: 15, color: p.bg),
                            )
                          : Icon(LucideIcons.arrowUpRight, key: const ValueKey(0), size: 20, color: p.text3),
                    ),
                  ],
                ),
                const SizedBox(height: 18),
                Text(title, style: T.h2.copyWith(color: p.text)),
                const SizedBox(height: 4),
                Text(sub, style: T.sub.copyWith(color: p.text2)),
                ?under,
              ],
            ),
          ),
        ),
      );
      return ListView(
        padding: const EdgeInsets.fromLTRB(gutter, 34, gutter, 10),
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4),
            child: Text(t('Connect\nwhat you use'), style: T.display.copyWith(color: p.text, fontSize: 34)),
          ),
          const SizedBox(height: 26),
          card(
            1,
            icon: LucideIcons.sparkles,
            title: t('Models'),
            sub: ready.isEmpty ? t('Sign in with ChatGPT, or use a key from Google, Anthropic, OpenAI and the rest.') : ready.map((x) => x.name).join(', '),
            done: ready.isNotEmpty,
            onTap: () => go(context, const ProvidersScreen()),
            under: Padding(
              padding: const EdgeInsets.only(top: 18),
              child: Row(
                children: [
                  for (final id in ['openai', 'google', 'anthropic', 'xai', 'deepseek', 'moonshotai', 'openrouter']) ...[Logo(id, size: 21, color: p.text2), const SizedBox(width: 18)],
                ],
              ),
            ),
          ),
          card(
            2,
            icon: LucideIcons.monitorSmartphone,
            title: t('Your computers'),
            sub: Account.i.signedIn ? Account.i.email : t('Sign in with the AFH account you use on them.'),
            done: Account.i.signedIn,
            onTap: () => go(context, Account.i.signedIn ? const AccountScreen() : const SignInScreen()),
          ),
        ],
      );
    },
  );
}
