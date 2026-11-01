// The Computers tab: sign in with the AFH account, then every computer in it, live. Tap one to see
// its threads and take over from your phone.
import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:url_launcher/url_launcher.dart';

import '../remote.dart';
import '../store.dart';
import '../theme.dart';
import '../widgets/common.dart';
import 'shell.dart';
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
      if (Shell.tab.value == 1 && Account.i.signedIn) Account.i.refresh();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        const Positioned.fill(child: Aurora(intensity: 0.8)),
        ListenableBuilder(
          listenable: Listenable.merge([Account.i, Settings.i]),
          builder: (context, _) => AnimatedSwitcher(
            duration: const Duration(milliseconds: 450),
            switchInCurve: Afh.ease,
            transitionBuilder: (c, a) => FadeTransition(
              opacity: a,
              child: SlideTransition(
                position: Tween(begin: const Offset(0, 0.04), end: Offset.zero).animate(a),
                child: c,
              ),
            ),
            child: Account.i.signedIn ? const _List(key: ValueKey('list')) : const _SignIn(key: ValueKey('signin')),
          ),
        ),
      ],
    );
  }
}

class _List extends StatelessWidget {
  const _List({super.key});

  @override
  Widget build(BuildContext context) {
    final top = MediaQuery.paddingOf(context).top;
    final bottom = MediaQuery.paddingOf(context).bottom;
    final a = Account.i;
    final online = a.computers.where((c) => c.online).length;
    return RefreshIndicator(
      color: Afh.orange,
      backgroundColor: Afh.surface2,
      edgeOffset: top,
      onRefresh: a.refresh,
      child: ListView(
        physics: const BouncingScrollPhysics(parent: AlwaysScrollableScrollPhysics()),
        padding: EdgeInsets.fromLTRB(16, top + 18, 16, 120 + bottom),
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 6),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  a.computers.isEmpty ? 'Remote control' : '$online of ${a.computers.length} online',
                  style: const TextStyle(color: Afh.text3, fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 4),
                Text('Computers', style: Afh.h1()).animate().fadeIn().moveX(begin: -12, end: 0, curve: Afh.ease),
              ],
            ),
          ),
          const SizedBox(height: 20),
          if (a.error != null && a.computers.isEmpty)
            EmptyState(
              icon: Icons.cloud_off_rounded,
              title: 'Couldn\'t reach your account',
              text: a.error!.message,
              action: GhostButton(label: 'Try again', icon: Icons.refresh_rounded, onTap: a.refresh),
            )
          else if (a.computers.isEmpty && a.loading)
            for (var i = 0; i < 3; i++) const _Skeleton()
          else if (a.computers.isEmpty)
            const _NoComputers()
          else
            for (final (i, c) in a.computers.indexed)
              _ComputerCard(computer: c)
                  .animate()
                  .fadeIn(delay: (i * 60).ms, duration: 350.ms)
                  .moveY(begin: 18, end: 0, delay: (i * 60).ms, curve: Afh.ease, duration: 500.ms),
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
    final status = c.online
        ? 'Online${c.version != null ? ' · AFH ${c.version}' : ''}'
        : 'Offline · last seen ${ago(c.lastSeen).isEmpty ? 'a while ago' : ago(c.lastSeen)}';
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Pressable(
        onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => ThreadsScreen(computer: c))),
        child: Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: Afh.surface.withValues(alpha: 0.85),
            borderRadius: BorderRadius.circular(26),
            border: Border.all(color: c.online ? Afh.good.withValues(alpha: 0.3) : Afh.line),
            boxShadow: c.online ? [BoxShadow(color: Afh.good.withValues(alpha: 0.08), blurRadius: 30, spreadRadius: -4)] : null,
          ),
          child: Row(
            children: [
              Hero(
                tag: 'pc-${c.id}',
                child: Container(
                  width: 58,
                  height: 58,
                  decoration: BoxDecoration(
                    gradient: c.online ? Afh.gradSoft : null,
                    color: c.online ? null : Colors.white.withValues(alpha: 0.04),
                    borderRadius: BorderRadius.circular(19),
                    border: Border.all(color: c.online ? Afh.orange.withValues(alpha: 0.3) : Afh.line),
                  ),
                  child: Icon(Icons.laptop_chromebook_rounded, size: 28, color: c.online ? const Color(0xFFFFB48A) : Afh.text3),
                ),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      c.name,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontFamily: Afh.display, fontWeight: FontWeight.w700, fontSize: 18),
                    ),
                    const SizedBox(height: 6),
                    Row(
                      children: [
                        PulseDot(color: c.online ? Afh.good : Afh.text3, live: c.online, size: 8),
                        const SizedBox(width: 8),
                        Flexible(
                          child: Text(
                            status,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(color: c.online ? Afh.text2 : Afh.text3, fontSize: 13),
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              const Icon(Icons.arrow_forward_ios_rounded, size: 16, color: Afh.text3),
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
      height: 90,
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(color: Afh.surface, borderRadius: BorderRadius.circular(26)),
    ).animate(onPlay: (c) => c.repeat()).shimmer(duration: 1300.ms, color: Colors.white.withValues(alpha: 0.05));
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
            width: 30,
            height: 30,
            alignment: Alignment.center,
            decoration: const BoxDecoration(gradient: Afh.grad, shape: BoxShape.circle),
            child: Text(
              '$n',
              style: const TextStyle(fontWeight: FontWeight.w800, color: Color(0xFF1A0D05)),
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15.5)),
                const SizedBox(height: 3),
                Text(text, style: const TextStyle(color: Afh.text2, height: 1.4)),
              ],
            ),
          ),
        ],
      ),
    ).animate().fadeIn(delay: (n * 120).ms).moveX(begin: 14, end: 0, delay: (n * 120).ms, curve: Afh.ease);
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: Afh.surface.withValues(alpha: 0.8),
        borderRadius: BorderRadius.circular(26),
        border: Border.all(color: Afh.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const IconTile(Icons.add_link_rounded, size: 54),
          const SizedBox(height: 16),
          Text('Connect your first computer', style: Afh.h3()),
          const SizedBox(height: 18),
          step(1, 'Open AFH on your computer', 'Version 1.9.1 or newer. Get it at agentflowharness.com/download.'),
          step(2, 'Click Sign in', 'It\'s the account button at the bottom of AFH\'s sidebar.'),
          step(3, 'Approve it in your browser', 'Sign in as ${Account.i.email} and the computer appears here.'),
          GhostButton(
            label: 'Download AFH',
            icon: Icons.download_rounded,
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
    final top = MediaQuery.paddingOf(context).top;
    final bottom = MediaQuery.paddingOf(context).bottom;
    return ListView(
      padding: EdgeInsets.fromLTRB(22, top + 18, 22, 120 + bottom),
      children: [
        Text(
          'Remote control',
          style: const TextStyle(color: Afh.text3, fontWeight: FontWeight.w600),
        ).animate().fadeIn(),
        const SizedBox(height: 4),
        Text('Computers', style: Afh.h1()).animate().fadeIn().moveX(begin: -12, end: 0, curve: Afh.ease),
        const SizedBox(height: 22),
        const _Orbit(),
        const SizedBox(height: 22),
        Text('Run AFH on your PC from anywhere', style: Afh.h2()).animate().fadeIn(delay: 150.ms),
        const SizedBox(height: 8),
        const Text(
          'Follow every thread live, approve steps, answer questions and start new tasks. Sign in with your AFH account.',
          style: TextStyle(color: Afh.text2, height: 1.45),
        ).animate().fadeIn(delay: 200.ms),
        const SizedBox(height: 22),
        AnimatedSwitcher(
          duration: const Duration(milliseconds: 300),
          child: Row(
            key: ValueKey(_create),
            children: [Text(_create ? 'Create your account' : 'Sign in', style: Afh.h3())],
          ),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _email,
          keyboardType: TextInputType.emailAddress,
          autocorrect: false,
          autofillHints: const [AutofillHints.email],
          textInputAction: TextInputAction.next,
          decoration: const InputDecoration(
            hintText: 'Email',
            prefixIcon: Icon(Icons.alternate_email_rounded, color: Afh.text3),
          ),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _password,
          obscureText: _hidden,
          autofillHints: [_create ? AutofillHints.newPassword : AutofillHints.password],
          textInputAction: TextInputAction.done,
          onSubmitted: (_) => _go(),
          decoration: InputDecoration(
            hintText: 'Password',
            prefixIcon: const Icon(Icons.lock_outline_rounded, color: Afh.text3),
            suffixIcon: IconButton(
              onPressed: () => setState(() => _hidden = !_hidden),
              icon: Icon(_hidden ? Icons.visibility_rounded : Icons.visibility_off_rounded, color: Afh.text3, size: 20),
            ),
          ),
        ),
        AnimatedSize(
          duration: const Duration(milliseconds: 280),
          curve: Afh.ease,
          child: _error == null
              ? const SizedBox(width: double.infinity)
              : Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Row(
                    children: [
                      const Icon(Icons.error_outline_rounded, color: Afh.bad, size: 18),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(_error!, style: const TextStyle(color: Color(0xFFFFC2CD))),
                      ),
                    ],
                  ),
                ).animate().shakeX(hz: 4, amount: 3, duration: 400.ms),
        ),
        const SizedBox(height: 20),
        GradButton(label: _create ? 'Create account' : 'Sign in', busy: _busy, onTap: _go),
        const SizedBox(height: 10),
        Center(
          child: TextButton(
            onPressed: () => setState(() {
              _create = !_create;
              _error = null;
            }),
            child: Text.rich(
              TextSpan(
                children: [
                  TextSpan(
                    text: _create ? 'Already have an account? ' : 'New to AFH? ',
                    style: const TextStyle(color: Afh.text2),
                  ),
                  TextSpan(
                    text: _create ? 'Sign in' : 'Create an account',
                    style: const TextStyle(color: Afh.orange, fontWeight: FontWeight.w700),
                  ),
                ],
              ),
            ),
          ),
        ),
        const SizedBox(height: 6),
        const Text(
          'Direct chat works without an account. The account is only for reaching your own computers.',
          textAlign: TextAlign.center,
          style: TextStyle(color: Afh.text3, fontSize: 12.5, height: 1.4),
        ),
      ],
    );
  }
}

/// A computer in the middle with small devices circling it.
class _Orbit extends StatefulWidget {
  const _Orbit();
  @override
  State<_Orbit> createState() => _OrbitState();
}

class _OrbitState extends State<_Orbit> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(seconds: 14))..repeat();
  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 190,
      child: AnimatedBuilder(
        animation: _c,
        builder: (_, _) {
          final a = _c.value * 2 * math.pi;
          Widget sat(double phase, IconData icon, Color color) {
            final x = 118 * math.cos(a + phase), y = 54 * math.sin(a + phase);
            final front = math.sin(a + phase) > 0;
            return Transform.translate(
              offset: Offset(x, y),
              child: Transform.scale(
                scale: front ? 1 : 0.8,
                child: Opacity(
                  opacity: front ? 1 : 0.55,
                  child: Container(
                    width: 42,
                    height: 42,
                    decoration: BoxDecoration(
                      color: color.withValues(alpha: 0.18),
                      shape: BoxShape.circle,
                      border: Border.all(color: color.withValues(alpha: 0.6)),
                    ),
                    child: Icon(icon, size: 20, color: color),
                  ),
                ),
              ),
            );
          }

          final sats = [(0.0, Icons.phone_iphone_rounded, Afh.amber), (2.09, Icons.check_rounded, Afh.good), (4.19, Icons.bolt_rounded, Afh.pink)];
          final behind = sats.where((s) => math.sin(a + s.$1) <= 0).map((s) => sat(s.$1, s.$2, s.$3));
          final ahead = sats.where((s) => math.sin(a + s.$1) > 0).map((s) => sat(s.$1, s.$2, s.$3));
          return Stack(
            alignment: Alignment.center,
            children: [
              Container(
                width: 250,
                height: 112,
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(200),
                  border: Border.all(color: Afh.line2),
                ),
              ),
              ...behind,
              Container(
                width: 92,
                height: 92,
                decoration: BoxDecoration(
                  gradient: Afh.grad,
                  borderRadius: BorderRadius.circular(30),
                  boxShadow: [BoxShadow(color: Afh.pink.withValues(alpha: 0.4), blurRadius: 40, spreadRadius: -6)],
                ),
                child: const Icon(Icons.laptop_chromebook_rounded, size: 44, color: Color(0xFF1A0D05)),
              ),
              ...ahead,
            ],
          );
        },
      ),
    ).animate().fadeIn(duration: 500.ms).scale(begin: const Offset(0.9, 0.9), curve: Afh.ease, duration: 600.ms);
  }
}
