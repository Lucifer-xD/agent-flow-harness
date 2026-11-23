// The AFH account: signing in, the computers in it, how to add one.
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/hub.dart';
import '../core/l10n.dart';
import '../core/relay.dart';
import '../ui/kit.dart';
import '../ui/look.dart';
import '../ui/mark.dart';
import '../ui/motion.dart';
import 'computer.dart';

class SignInScreen extends StatefulWidget {
  const SignInScreen({super.key, this.create = false});
  final bool create;
  @override
  State<SignInScreen> createState() => _SignInScreenState();
}

class _SignInScreenState extends State<SignInScreen> {
  late bool _create = widget.create;
  final _email = TextEditingController(), _pw = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _email.dispose();
    _pw.dispose();
    super.dispose();
  }

  Future<void> _go() async {
    final email = _email.text.trim();
    if (!email.contains('@') || _pw.text.isEmpty) return setState(() => _error = t('Enter your email and password.'));
    if (_create && _pw.text.length < 8) return setState(() => _error = t('Use at least 8 characters for the password.'));
    setState(() {
      _busy = true;
      _error = null;
    });
    FocusScope.of(context).unfocus();
    try {
      await Account.i.signIn(email, _pw.text, create: _create);
      Tap.mid();
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = '$e';
          _busy = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final mq = MediaQuery.paddingOf(context);
    return Scaffold(
      backgroundColor: p.bg,
      body: SafeArea(
        child: Column(
          children: [
            const Align(
              alignment: AlignmentDirectional.centerStart,
              child: Padding(padding: EdgeInsets.all(8), child: BackBtn(icon: LucideIcons.x)),
            ),
            Expanded(
              child: ListView(
                padding: EdgeInsets.fromLTRB(gutter + 4, 18, gutter + 4, 24 + mq.bottom),
                keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
                children: [
                  const Align(alignment: AlignmentDirectional.centerStart, child: AfhLogo(width: 62)),
                  const SizedBox(height: 28),
                  Rise(1, child: Text(_create ? t('Create your AFH account') : t('Sign in to AFH'), style: T.display.copyWith(color: p.text))),
                  const SizedBox(height: 10),
                  Rise(2, child: Text(t('It\'s how this phone finds AFH on your computers. Chats on the phone work without it.'), style: T.sub.copyWith(color: p.text2))),
                  const SizedBox(height: 28),
                  Rise(3, child: Field(_email, label: t('Email'), icon: LucideIcons.mail, type: TextInputType.emailAddress, hints: const [AutofillHints.email])),
                  const SizedBox(height: 14),
                  Rise(
                    4,
                    child: Field(
                      _pw,
                      label: t('Password'),
                      icon: LucideIcons.lock,
                      secret: true,
                      hints: [_create ? AutofillHints.newPassword : AutofillHints.password],
                      onDone: _go,
                    ),
                  ),
                  Fold(
                    open: _error != null,
                    child: Padding(
                      padding: const EdgeInsets.only(top: 14),
                      child: Note(_error ?? '', icon: LucideIcons.circleAlert, color: p.bad),
                    ),
                  ),
                  const SizedBox(height: 24),
                  Rise(5, child: Btn(_create ? t('Create account') : t('Sign in'), busy: _busy, onTap: _go)),
                  const SizedBox(height: 8),
                  Rise(
                    6,
                    child: Btn(
                      _create ? t('I already have an account') : t('Create an account'),
                      kind: Kind.ghost,
                      onTap: () => setState(() {
                        _create = !_create;
                        _error = null;
                      }),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// How to bring a computer into the account.
class AddComputer extends StatelessWidget {
  const AddComputer({super.key});
  @override
  Widget build(BuildContext context) {
    final p = context.p;
    Widget step(int n, String a, String b) => Padding(
      padding: const EdgeInsets.only(bottom: 18),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 28,
            height: 28,
            alignment: Alignment.center,
            decoration: BoxDecoration(color: p.fill, shape: BoxShape.circle),
            child: Text('$n', style: T.label.copyWith(color: p.text)),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const SizedBox(height: 3),
                Text(a, style: T.row.copyWith(color: p.text)),
                const SizedBox(height: 3),
                Text(b, style: T.sub.copyWith(color: p.text2)),
              ],
            ),
          ),
        ],
      ),
    );
    return Panel(
      pad: const EdgeInsets.fromLTRB(18, 20, 18, 18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(t('Add a computer'), style: T.h2.copyWith(color: p.text)),
          const SizedBox(height: 18),
          step(1, t('Open AFH on your computer'), t('Get it at agentflowharness.com if it isn\'t there yet.')),
          step(2, t('Click Sign in'), t('The account button at the bottom of its sidebar.')),
          step(3, t('Approve it in the browser'), t('Sign in as {} and the computer appears here.', Account.i.email)),
          Btn(t('Get AFH for your computer'), kind: Kind.soft, icon: LucideIcons.download, onTap: () => launchUrl(Uri.parse('$server/download'), mode: LaunchMode.externalApplication)),
        ],
      ),
    );
  }
}

class AccountScreen extends StatelessWidget {
  const AccountScreen({super.key});
  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: Listenable.merge([Account.i, Hubs.i]),
    builder: (context, _) {
      final p = context.p;
      final a = Account.i;
      return AppPage(
        title: t('AFH account'),
        sub: a.email,
        onRefresh: a.refresh,
        slivers: [
          pad([
            if (a.error != null) Note(a.error!.message, icon: LucideIcons.cloudOff, color: p.warn, action: t('Try again'), onTap: a.refresh),
            if (a.computers.isNotEmpty)
              Group(
                title: t('Computers'),
                children: [
                  for (final c in a.computers)
                    Tile(
                      c.name,
                      sub: [c.online ? t('Online') : t('Offline'), if (c.version != null) 'AFH ${c.version}'].join(' · '),
                      lead: Square(LucideIcons.monitor, color: c.online ? p.good : null),
                      arrow: true,
                      onTap: () => go(context, ComputerScreen(c)),
                    ),
                ],
              ),
            if (a.computers.isEmpty) const AddComputer(),
            Group(
              title: t('Account'),
              children: [
                Tile(t('Manage account'), sub: t('Password, sign-ins, deleting the account'), icon: LucideIcons.externalLink, onTap: () => launchUrl(Uri.parse('$server/account'), mode: LaunchMode.externalApplication)),
                Tile(
                  t('Sign out'),
                  icon: LucideIcons.logOut,
                  color: p.bad,
                  onTap: () async {
                    if (!await confirm(context, t('Sign out?'), t('Your computers stay in your account. Chats on this phone stay too.'), t('Sign out'), danger: true)) return;
                    await a.signOut();
                    if (context.mounted) Navigator.pop(context);
                  },
                ),
              ],
            ),
          ]),
        ],
      );
    },
  );
}
