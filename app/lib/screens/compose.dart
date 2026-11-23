// Something new: a chat on the phone, or work on one of your computers.
import 'dart:async';

import 'package:flutter/material.dart';

import '../core/ai.dart';
import '../core/hub.dart';
import '../core/l10n.dart';
import '../core/native.dart';
import '../core/relay.dart';
import '../core/runs.dart';
import '../core/store.dart';
import '../ui/badge.dart';
import '../ui/composer.dart';
import '../ui/kit.dart';
import '../ui/look.dart';
import '../ui/motion.dart';
import 'account.dart';
import 'assistants.dart';
import 'chat.dart';
import 'computer.dart' show rememberPlace;
import 'pick.dart';
import 'providers.dart';
import 'talk.dart';
import 'thread.dart';

Future<void> compose(BuildContext context, {Hub? hub, String? dir, String? text, List<Att>? files, int? where}) =>
    go(context, ComposeScreen(hub: hub, dir: dir, text: text, files: files, where: where), over: true);

class ComposeScreen extends StatefulWidget {
  const ComposeScreen({super.key, this.hub, this.dir, this.text, this.files, this.where});
  final Hub? hub;
  final String? dir, text;
  final List<Att>? files;
  final int? where; // 0 phone, 1 computer
  @override
  State<ComposeScreen> createState() => _ComposeScreenState();
}

class _ComposeScreenState extends State<ComposeScreen> {
  late int _where = widget.where ?? (widget.hub != null ? 1 : (Settings.i.str('last.where') == 'computer' && Hubs.i.online.isNotEmpty ? 1 : 0));
  late final _text = TextEditingController(text: widget.text ?? '');
  late final List<Att> _files = [...?widget.files];
  final _focus = FocusNode();
  bool _busy = false;

  // on the phone
  late Chat _chat = newChat();

  // on a computer
  Hub? _hub;
  String? _dir;
  J? _model;
  String? _agent, _mode;
  bool _copy = false;

  @override
  void initState() {
    super.initState();
    _hub = widget.hub ?? Hubs.i.online.where((h) => h.computer.id == Settings.i.str('last.computer')).firstOrNull ?? Hubs.i.online.firstOrNull;
    _dir = widget.dir;
    _place();
    Hubs.i.addListener(_redraw);
    Settings.i.addListener(_redraw);
  }

  void _place() {
    final h = _hub;
    if (h == null) return;
    final last = Settings.i.str('last.dir.${h.computer.id}');
    _dir ??= h.projects.contains(last) ? last : (h.sessions.map(dirOf).where(h.projects.contains).firstOrNull ?? h.projects.firstOrNull);
    _mode ??= Settings.i.str('last.mode').isEmpty ? null : Settings.i.str('last.mode');
  }

  void _redraw() {
    if (!mounted) return;
    _hub ??= Hubs.i.online.firstOrNull;
    _place();
    setState(() {});
  }

  @override
  void dispose() {
    Hubs.i.removeListener(_redraw);
    Settings.i.removeListener(_redraw);
    _text.dispose();
    _focus.dispose();
    super.dispose();
  }

  void _pick(int i) {
    setState(() => _where = i);
    Settings.i.put('last.where', i == 1 ? 'computer' : 'phone', quiet: true);
  }

  bool get _ready => providers.any((p) => p.id == _chat.provider && p.ready) && _chat.model.isNotEmpty;

  Future<bool> _sendChat(String text, List<Att> files) async {
    if (!_ready) {
      await go(context, const ProvidersScreen());
      final m = firstModel();
      if (m == null || !mounted) return false;
      _chat.provider = m.$1;
      _chat.model = m.$2;
    }
    sendTo(_chat, text, files);
    if (!Settings.i.flag('asked.notify')) {
      Settings.i.put('asked.notify', true, quiet: true);
      Runs.i.of(_chat.id)?.whenDone(Notify.allowed);
    }
    Settings.i.put('draft.new', null, quiet: true);
    unawaited(Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => ChatScreen(_chat))));
    return true;
  }

  Future<bool> _sendWork(String text, List<Att> files) async {
    final h = _hub;
    if (h == null) return false;
    if (_dir == null) {
      _dir = await pickProject(context, h, null);
      if (_dir == null || !mounted) return false;
    }
    setState(() => _busy = true);
    try {
      final s = await h.create(dir: _dir!, model: _model, agent: _agent, mode: _mode, worktree: _copy);
      final sid = '${s['id']}';
      rememberPlace(h, _dir!);
      unawaited(Notify.allowed());
      final store = h.thread(sid);
      final sent = store.send(text, files: [for (final f in files) toAtt2(f)], model: _model, agent: _agent);
      if (!mounted) return true;
      unawaited(Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => ThreadScreen(h, sid))));
      unawaited(sent.catchError((Object e) => store.fail('$e', text)));
      return true;
    } catch (e) {
      if (mounted) {
        setState(() => _busy = false);
        toast(context, '$e', bad: true);
      }
      return false;
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final mq = MediaQuery.paddingOf(context);
    final kb = MediaQuery.viewInsetsOf(context).bottom;
    final h = _hub;
    final computer = _where == 1;
    final usable = !computer || (h != null && h.state != 'offline');
    return Scaffold(
      backgroundColor: p.bg,
      body: Column(
        children: [
          SizedBox(height: mq.top + 8),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 10),
            child: Row(
              children: [
                Ic(LucideIcons.x, tip: t('Close'), onTap: () => Navigator.maybePop(context)),
                Expanded(
                  child: Center(
                    child: ConstrainedBox(
                      constraints: const BoxConstraints(maxWidth: 250),
                      child: Seg([t('Chat'), t('Computer')], _where, _pick, icons: const [LucideIcons.messageCircle, LucideIcons.monitor]),
                    ),
                  ),
                ),
                const SizedBox(width: 40),
              ],
            ),
          ),
          Expanded(
            child: AnimatedSwitcher(
              duration: med,
              switchInCurve: Curves.easeOutQuint,
              transitionBuilder: (c, a) => FadeTransition(
                opacity: a,
                child: SlideTransition(position: Tween(begin: const Offset(0, .03), end: Offset.zero).animate(a), child: c),
              ),
              child: ListView(
                key: ValueKey('$_where${h?.computer.id}'),
                padding: const EdgeInsets.fromLTRB(gutter, 26, gutter, 20),
                keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
                children: computer ? _computerBody(h) : _chatBody(),
              ),
            ),
          ),
          if (usable)
            Padding(
              padding: EdgeInsets.fromLTRB(12, 0, 12, kb > 0 ? 8 : 10 + mq.bottom),
              child: Composer(
                controller: _text,
                files: _files,
                focus: _focus,
                auto: widget.files == null,
                busy: _busy,
                hint: computer ? t('What should it do?') : t('Ask anything'),
                draft: widget.text == null && widget.files == null ? 'compose' : null,
                onSend: computer ? _sendWork : _sendChat,
                onVoice: computer ? null : () => Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => TalkScreen(_chat), fullscreenDialog: true)),
                chips: computer ? _workChips(h!) : _chatChips(),
              ),
            ),
        ],
      ),
    );
  }

  List<Widget> _chatBody() {
    final p = context.p;
    final list = Settings.i.assistants;
    return [
      Rise(0, child: Text(t('What can I help with?'), style: T.display.copyWith(color: p.text))),
      const SizedBox(height: 8),
      Rise(1, child: Text(t('Photos, files, voice, the web: it can use them all.'), style: T.sub.copyWith(color: p.text2))),
      if (list.isNotEmpty) ...[
        const SizedBox(height: 22),
        Rise(
          2,
          child: Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final a in list)
                Pill(
                  a.name,
                  icon: assistantIcon(a.icon),
                  on: _chat.assistant == a.id,
                  onTap: () => setState(() => _chat = newChat(assistant: _chat.assistant == a.id ? null : a)),
                ),
            ],
          ),
        ),
      ],
      const SizedBox(height: 18),
      for (final (i, (icon, label, text)) in [
        (LucideIcons.globe, t('Find out something'), t('Search the web for ')),
        (LucideIcons.penLine, t('Write with me'), t('Help me write ')),
        (LucideIcons.code, t('Solve a bug'), t('Why does this code fail? ')),
      ].indexed)
        _Idea(i + 3, icon, label, () => _fill(text)),
    ];
  }

  void _fill(String s) {
    _text.value = TextEditingValue(text: s, selection: TextSelection.collapsed(offset: s.length));
    _focus.requestFocus();
  }

  List<Widget> _chatChips() {
    final provider = providers.where((x) => x.id == _chat.provider).firstOrNull;
    return [
      CChip(
        _ready ? prettyModel(_chat.model) : t('Choose a model'),
        lead: _ready ? Logo(_chat.provider, name: provider?.name ?? '', model: _chat.model, size: 15, family: true) : null,
        icon: _ready ? null : LucideIcons.keyRound,
        max: 170,
        onTap: () async {
          if (phoneModels().isEmpty) {
            await go(context, const ProvidersScreen());
            setState(() => _chat = newChat());
            return;
          }
          final got = await pickModel(context, phoneModels(), current: '${_chat.provider}/${_chat.model}', effort: _chat.effort, phone: true);
          if (got == null || !mounted) return;
          setState(() {
            _chat.provider = got.row.pid;
            _chat.model = got.row.id;
            _chat.effort = got.effort;
          });
        },
      ),
      if (_chat.effort != null) CChip(effortName(_chat.effort), icon: LucideIcons.brain),
      CChip('', icon: LucideIcons.ghost, on: _chat.temporary, onTap: () => setState(() => _chat.temporary = !_chat.temporary)),
    ];
  }

  List<Widget> _computerBody(Hub? h) {
    final p = context.p;
    if (!Account.i.signedIn) {
      return [
        Empty(
          LucideIcons.monitorSmartphone,
          t('Your computer, in your pocket'),
          t('Sign in with your AFH account to start work on your own computers and follow it here.'),
          action: t('Sign in'),
          onTap: () => go(context, const SignInScreen()),
        ),
      ];
    }
    if (h == null || h.state == 'offline') {
      return [
        Empty(
          LucideIcons.cloudOff,
          t('No computer is online'),
          t('Open AFH on a computer in your account. It shows up here by itself.'),
          action: t('Look again'),
          onTap: () async {
            await Account.i.refresh();
            _redraw();
          },
        ),
      ];
    }
    final agent = h.agents.where((a) => a['id'] == _agent).firstOrNull;
    final mode = _mode ?? 'ask';
    return [
      Rise(0, child: Text(t('What should it do?'), style: T.display.copyWith(color: p.text))),
      const SizedBox(height: 18),
      Rise(
        1,
        child: Group(
          children: [
            Tile(
              h.computer.name,
              lead: Square(LucideIcons.monitor, color: p.good),
              sub: t('Online'),
              arrow: Hubs.i.online.length > 1,
              onTap: Hubs.i.online.length < 2
                  ? null
                  : () async {
                      final got = await pickComputer(context, current: h.computer.id);
                      if (got == null || got == h) return;
                      setState(() {
                        _hub = got;
                        _dir = null;
                        _model = null;
                        _agent = null;
                        _place();
                      });
                    },
            ),
            Tile(
              _dir == null ? t('Choose a project') : baseName(_dir!),
              lead: const Square(LucideIcons.folder),
              sub: _dir == null ? null : parentOf(_dir!),
              subMax: 1,
              arrow: true,
              onTap: () async {
                final d = await pickProject(context, h, _dir);
                if (d != null) setState(() => _dir = d);
              },
            ),
          ],
        ),
      ),
      const SizedBox(height: 12),
      Rise(
        2,
        child: Group(
          children: [
            Tile(
              t('Agent'),
              icon: LucideIcons.hammer,
              value: agent == null ? t('Build') : '${agent['name'] ?? agent['id']}'.replaceFirstMapped(RegExp('^.'), (m) => m[0]!.toUpperCase()),
              arrow: true,
              onTap: () async {
                final a = await pickAgent(context, h, _agent ?? 'build');
                if (a != null) setState(() => _agent = a);
              },
            ),
            Tile(
              t('What it may do'),
              icon: modeOf_(mode).$1,
              value: t(modeOf_(mode).$2),
              arrow: true,
              onTap: () async {
                final m = await pickMode(context, mode);
                if (m == null) return;
                setState(() => _mode = m);
                Settings.i.put('last.mode', m, quiet: true);
              },
            ),
            ToggleTile(t('Work in its own copy'), _copy, (v) => setState(() => _copy = v), icon: LucideIcons.gitBranch, sub: t('A separate git worktree you can merge or throw away')),
          ],
        ),
      ),
    ];
  }

  List<Widget> _workChips(Hub h) {
    final ref = _model ?? h.defaultModel;
    final m = asMap(ref);
    final v = '${m['variant'] ?? ''}';
    return [
      CChip(
        ref == null ? t('Model') : h.modelName(ref),
        lead: ref == null ? null : Logo('${m['providerID']}', name: h.providerNames['${m['providerID']}'] ?? '', model: '${m['id']}', size: 15, family: true),
        icon: ref == null ? LucideIcons.cpu : null,
        max: 190,
        onTap: () async {
          final got = await pickModel(context, hubModels(h), current: '${m['providerID']}/${m['id']}', effort: v.isEmpty ? null : v);
          if (got != null) setState(() => _model = got.ref);
        },
      ),
      if (v.isNotEmpty && v != 'default') CChip(effortName(v), icon: LucideIcons.brain),
    ];
  }
}

class _Idea extends StatelessWidget {
  const _Idea(this.i, this.icon, this.label, this.onTap);
  final int i;
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => Rise(
    i,
    child: Press(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 11),
        child: Row(
          children: [
            Icon(icon, size: 19, color: context.p.text2),
            const SizedBox(width: 14),
            Text(label, style: T.row.copyWith(color: context.p.text)),
          ],
        ),
      ),
    ),
  );
}
