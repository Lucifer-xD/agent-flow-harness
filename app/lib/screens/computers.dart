// Computers: sign in with the AFH account, then every computer in it, live. Tap one to see its
// threads and take over from your phone.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'package:url_launcher/url_launcher.dart';

import '../remote.dart';
import '../store.dart';
import '../theme.dart';
import '../widgets/common.dart';
import '../widgets/logo.dart';
import 'threads.dart';

class ComputersScreen extends StatefulWidget {
  const ComputersScreen({super.key});
  @override
  State<ComputersScreen> createState() => _ComputersScreenState();
}

class _ComputersScreenState extends State<ComputersScreen> {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    Account.i.refresh();
    _timer = Timer.periodic(const Duration(seconds: 15), (_) {
      if (Account.i.signedIn) Account.i.refresh();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: Listenable.merge([Account.i, Settings.i]),
      builder: (context, _) => Scaffold(
        appBar: AppBar(
          title: Text(Account.i.signedIn ? 'Computers' : ''),
          actions: [
            if (Account.i.signedIn)
              Padding(
                padding: const EdgeInsets.only(right: 6),
                child: Account.i.loading
                    ? const Padding(padding: EdgeInsets.all(12), child: SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)))
                    : IconBtn(LucideIcons.refreshCw, tooltip: 'Refresh', iconSize: 19, onTap: Account.i.refresh),
              ),
          ],
        ),
        body: AnimatedSwitcher(
          duration: Afh.med,
          child: Account.i.signedIn ? const _List(key: ValueKey('list')) : const _SignIn(key: ValueKey('signin')),
        ),
      ),
    );
  }
}

class _List extends StatelessWidget {
  const _List({super.key});

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.paddingOf(context).bottom;
    final a = Account.i;
    final online = a.computers.where((c) => c.online).length;
    return RefreshIndicator(
      color: Afh.accent,
      backgroundColor: Afh.surface2,
      onRefresh: a.refresh,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: EdgeInsets.fromLTRB(16, 4, 16, 24 + bottom),
        children: [
          if (a.computers.isNotEmpty)
            SectionLabel('$online of ${a.computers.length} online', padding: const EdgeInsets.fromLTRB(4, 4, 4, 10)),
          if (a.error != null && a.computers.isEmpty)
            EmptyState(
              icon: LucideIcons.wifiOff,
              title: 'Couldn\'t reach your account',
              text: a.error!.message,
              action: SecondaryButton(label: 'Try again', icon: LucideIcons.refreshCw, onTap: a.refresh),
            )
          else if (a.computers.isEmpty && a.loading)
            for (var i = 0; i < 2; i++) const _Skeleton()
          else if (a.computers.isEmpty)
            const _NoComputers()
          else
            for (final (i, c) in a.computers.indexed) _ComputerCard(computer: c).enter(i),
        ],
      ),
    );
  }
}

class _ComputerCard extends StatelessWidget {
  const _ComputerCard({required this.computer});
  final Computer computer;
  @override
  Widget build(BuildContext context) {
    final c = computer;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Pressable(
        scale: 0.98,
        onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => ThreadsScreen(computer: c))),
        child: Container(
          padding: const EdgeInsets.fromLTRB(14, 14, 12, 14),
          decoration: BoxDecoration(color: Afh.surface, borderRadius: BorderRadius.circular(16), border: Border.all(color: Afh.line)),
          child: Row(
            children: [
              IconTile(c.online ? LucideIcons.laptop : LucideIcons.laptop, size: 44, active: c.online),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      c.name,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontWeight: FontWeight.w600, fontSize: 16, color: Afh.text),
                    ),
                    const SizedBox(height: 4),
                    Row(
                      children: [
                        PulseDot(color: c.online ? Afh.good : Afh.text3, live: c.online, size: 7),
                        const SizedBox(width: 2),
                        Flexible(
                          child: Text(
                            c.online ? 'Online' : 'Last seen ${ago(c.lastSeen).isEmpty ? 'a while ago' : ago(c.lastSeen)}',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(color: c.online ? Afh.text2 : Afh.text3, fontSize: 13),
                          ),
                        ),
                        if (c.version != null) ...[
                          Text('  ·  ', style: TextStyle(color: Afh.text3, fontSize: 13)),
                          Text('AFH ${c.version}', style: TextStyle(fontFamily: Afh.mono, color: Afh.text3, fontSize: 11.5)),
                        ],
                      ],
                    ),
                  ],
                ),
              ),
              Icon(LucideIcons.chevronRight, size: 18, color: Afh.text3),
            ],
          ),
        ),
      ),
    );
  }
}

class _Skeleton extends StatelessWidget {
  const _Skeleton();
  @override
  Widget build(BuildContext context) {
    return Container(
      height: 74,
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(color: Afh.surface, borderRadius: BorderRadius.circular(16), border: Border.all(color: Afh.line)),
    ).animate(onPlay: (c) => c.repeat()).shimmer(duration: 1300.ms, color: Afh.text.withValues(alpha: 0.04));
  }
}

class _NoComputers extends StatelessWidget {
  const _NoComputers();
  @override
  Widget build(BuildContext context) {
    Widget step(int n, String title, String text) => Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 26,
            height: 26,
            alignment: Alignment.center,
            decoration: BoxDecoration(color: Afh.surface2, shape: BoxShape.circle, border: Border.all(color: Afh.line2)),
            child: Text('$n', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13, color: Afh.text)),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: TextStyle(fontWeight: FontWeight.w600, fontSize: 15, color: Afh.text)),
                const SizedBox(height: 3),
                Text(text, style: TextStyle(color: Afh.text2, height: 1.4, fontSize: 14)),
              ],
            ),
          ),
        ],
      ),
    ).enter(n);
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(color: Afh.surface, borderRadius: BorderRadius.circular(16), border: Border.all(color: Afh.line)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          IconTile(LucideIcons.monitorSmartphone, size: 44, active: true),
          const SizedBox(height: 14),
          Text('Connect your first computer', style: Afh.h3()),
          const SizedBox(height: 18),
          step(1, 'Open AFH on your computer', 'Version 1.9.1 or newer. Get it at agentflowharness.com/download.'),
          step(2, 'Click Sign in', 'It\'s the account button at the bottom of AFH\'s sidebar.'),
          step(3, 'Approve it in your browser', 'Sign in as ${Account.i.email} and the computer appears here.'),
          SecondaryButton(
            label: 'Download AFH',
            icon: LucideIcons.externalLink,
            onTap: () => launchUrl(Uri.parse('$server/download'), mode: LaunchMode.externalApplication),
          ),
        ],
      ),
    );
  }
}

class _SignIn extends StatefulWidget {
  const _SignIn({super.key});
  @override
  State<_SignIn> createState() => _SignInState();
}

class _SignInState extends State<_SignIn> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  bool _create = false;
  bool _busy = false;
  bool _hidden = true;
  String? _error;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _go() async {
    FocusScope.of(context).unfocus();
    final email = _email.text.trim();
    if (!email.contains('@') || _password.text.isEmpty) {
      setState(() => _error = 'Enter your email and password.');
      return;
    }
    if (_create && _password.text.length < 8) {
      setState(() => _error = 'Use at least 8 characters for the password.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await Account.i.signIn(email, _password.text, create: _create);
      HapticFeedback.mediumImpact();
      _password.clear();
    } on ApiError catch (e) {
      HapticFeedback.heavyImpact();
      if (mounted) setState(() => _error = e.message);
    }
    if (mounted) setState(() => _busy = false);
  }

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.paddingOf(context).bottom;
    return ListView(
      keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
      padding: EdgeInsets.fromLTRB(24, 8, 24, 24 + bottom),
      children: [
        const AfhLogo(width: 58),
        const SizedBox(height: 20),
        Text('Your computer,\nin your pocket', style: Afh.h1()).enter(1),
        const SizedBox(height: 10),
        Text(
          'Follow every thread live, approve steps, answer questions and start new tasks on AFH at home. Sign in with your AFH account.',
          style: TextStyle(color: Afh.text2, height: 1.5, fontSize: 15),
        ).enter(2),
        const SizedBox(height: 28),
        AnimatedSwitcher(
          duration: Afh.fast,
          child: Align(
            key: ValueKey(_create),
            alignment: Alignment.centerLeft,
            child: Text(_create ? 'Create your account' : 'Sign in', style: Afh.h3()),
          ),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _email,
          keyboardType: TextInputType.emailAddress,
          autocorrect: false,
          autofillHints: const [AutofillHints.email],
          textInputAction: TextInputAction.next,
          decoration: InputDecoration(
            hintText: 'Email',
            prefixIcon: Icon(LucideIcons.mail, size: 18, color: Afh.text3),
          ),
        ),
        const SizedBox(height: 10),
        TextField(
          controller: _password,
          obscureText: _hidden,
          autofillHints: [_create ? AutofillHints.newPassword : AutofillHints.password],
          textInputAction: TextInputAction.done,
          onSubmitted: (_) => _go(),
          decoration: InputDecoration(
            hintText: 'Password',
            prefixIcon: Icon(LucideIcons.lock, size: 18, color: Afh.text3),
            suffixIcon: IconBtn(
              _hidden ? LucideIcons.eye : LucideIcons.eyeOff,
              tooltip: _hidden ? 'Show password' : 'Hide password',
              iconSize: 18,
              color: Afh.text3,
              onTap: () => setState(() => _hidden = !_hidden),
            ),
          ),
        ),
        AnimatedSize(
          duration: Afh.med,
          curve: Afh.ease,
          child: _error == null
              ? const SizedBox(width: double.infinity)
              : Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Row(
                    children: [
                      Icon(LucideIcons.circleAlert, color: Afh.bad, size: 16),
                      const SizedBox(width: 8),
                      Expanded(child: Text(_error!, style: TextStyle(color: Afh.bad, fontSize: 13.5))),
                    ],
                  ),
                ).animate().shakeX(hz: 4, amount: 2, duration: 350.ms),
        ),
        const SizedBox(height: 18),
        PrimaryButton(label: _create ? 'Create account' : 'Sign in', busy: _busy, onTap: _go),
        const SizedBox(height: 8),
        Center(
          child: TextButton(
            onPressed: () => setState(() {
              _create = !_create;
              _error = null;
            }),
            child: Text.rich(
              TextSpan(
                children: [
                  TextSpan(text: _create ? 'Already have an account? ' : 'New to AFH? ', style: TextStyle(color: Afh.text2)),
                  TextSpan(
                    text: _create ? 'Sign in' : 'Create an account',
                    style: TextStyle(color: Afh.accent, fontWeight: FontWeight.w600),
                  ),
                ],
              ),
            ),
          ),
        ),
        const SizedBox(height: 6),
        Text(
          'Direct chat works without an account. The account is only for reaching your own computers.',
          textAlign: TextAlign.center,
          style: TextStyle(color: Afh.text3, fontSize: 12.5, height: 1.4),
        ),
      ],
    );
  }
}
