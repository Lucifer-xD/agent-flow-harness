// The home screen: a chat with a model. Replies stream in as they're written, thinking folds away,
// and every reply can be copied or tried again. "Run on PC" sends the message to AFH on one of the
// user's computers instead, as a new thread there.
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../ai.dart';
import '../remote.dart';
import '../store.dart';
import '../theme.dart';
import '../widgets/common.dart';
import '../widgets/composer.dart';
import '../widgets/logo.dart';
import '../widgets/md.dart';
import 'model_picker.dart';
import 'providers.dart';
import 'session.dart';

typedef Target = ({Computer computer, String dir});

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key, this.chat, this.onMenu, this.onNew, this.onStarted, this.onComputers});
  final Chat? chat;
  final VoidCallback? onMenu, onNew, onComputers;
  final ValueChanged<Chat>? onStarted; // the first message of a new chat was sent
  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  late Chat _chat;
  Run? _run;
  Msg? _live;
  Target? _target;
  bool _starting = false;
  final _input = TextEditingController();
  final _focus = FocusNode();
  final _scroll = ScrollController();
  bool _frame = false;

  bool get _busy => _run != null || _starting;

  @override
  void initState() {
    super.initState();
    if (widget.chat != null) {
      _chat = widget.chat!;
    } else {
      final d = defaultModel();
      _chat = Chats.i.create(d?.$1 ?? 'openai', d?.$2 ?? '');
    }
    _input.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _run?.cancel();
    if (_chat.messages.isNotEmpty) Chats.i.save(_chat, now: true);
    _input.dispose();
    _focus.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Provider get _provider => providerById(_chat.provider);

  Future<void> _pickModel() async {
    final got = await pickModel(context, provider: _chat.provider, model: _chat.model);
    if (got == null) return;
    setState(() {
      _chat.provider = got.$1;
      _chat.model = got.$2;
    });
    if (_chat.messages.isNotEmpty) Chats.i.save(_chat);
  }

  Future<bool> _ensureReady() async {
    if (_provider.ready && _chat.model.isNotEmpty) return true;
    final d = defaultModel();
    if (d != null) {
      setState(() {
        _chat.provider = d.$1;
        _chat.model = d.$2;
      });
      return true;
    }
    await Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ProvidersScreen()));
    final again = defaultModel();
    if (again == null) return false;
    setState(() {
      _chat.provider = again.$1;
      _chat.model = again.$2;
    });
    return true;
  }

  Future<void> _send([String? text]) async {
    final t = (text ?? _input.text).trim();
    if (t.isEmpty || _busy) return;
    if (_target != null) return _runOnPc(t);
    if (!await _ensureReady()) return;
    HapticFeedback.lightImpact();
    _input.clear();
    if (_chat.title.isEmpty) _chat.title = titleFrom(t);
    final first = _chat.messages.isEmpty;
    _chat.messages.add(Msg(role: 'user', text: t));
    if (first) widget.onStarted?.call(_chat);
    await _reply();
  }

  /// Starts a thread with this message on the picked computer and opens it.
  Future<void> _runOnPc(String text) async {
    final t = _target!;
    setState(() => _starting = true);
    try {
      final pc = Pc(t.computer);
      final s = Map<String, dynamic>.from(await pc.post('/api/sessions', {'directory': t.dir}) as Map);
      await pc.post('/api/sessions/${s['id']}/prompt', {'text': text});
      HapticFeedback.mediumImpact();
      _input.clear();
      if (!mounted) return;
      setState(() => _starting = false);
      await Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => SessionScreen(computer: t.computer, session: {...s, 'running': true}),
        ),
      );
    } on ApiError catch (e) {
      if (!mounted) return;
      setState(() => _starting = false);
      showToast(context, e.message, error: true);
    }
  }

  Future<void> _pickTarget() async {
    if (!Account.i.signedIn) {
      widget.onComputers?.call();
      return;
    }
    if (!Account.i.computers.any((c) => c.online)) {
      await Account.i.refresh();
      if (!mounted) return;
      if (!Account.i.computers.any((c) => c.online)) {
        showToast(context, 'None of your computers is online. Open AFH on one and try again.', error: true);
        return;
      }
    }
    final got = await showModalBottomSheet<Object>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => _TargetSheet(current: _target),
    );
    if (!mounted || got == null) return;
    setState(() => _target = got is Target ? got : null);
  }

  Future<void> _reply() async {
    final m = Msg(role: 'assistant', model: _chat.model);
    final history = [..._chat.messages];
    _chat.messages.add(m);
    _chat.updated = DateTime.now();
    final run = Run(_provider, _chat.model, history, system: Settings.i.system);
    setState(() {
      _run = run;
      _live = m;
    });
    Chats.i.save(_chat);
    try {
      await for (final d in run.start()) {
        m.text += d.text;
        m.reasoning += d.reasoning;
        _redraw();
      }
      if (m.text.isEmpty && m.reasoning.isEmpty && !run.cancelled) m.error = 'The model sent an empty reply.';
    } on AiError catch (e) {
      m.error = e.message;
      HapticFeedback.heavyImpact();
    }
    if (!mounted) return;
    setState(() {
      _run = null;
      _live = null;
    });
    _chat.updated = DateTime.now();
    Chats.i.save(_chat, now: true);
  }

  /// One redraw per frame, however fast tokens arrive.
  void _redraw() {
    if (_frame || !mounted) return;
    _frame = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _frame = false;
      if (mounted) setState(() {});
    });
    WidgetsBinding.instance.scheduleFrame();
  }

  void _stop() {
    HapticFeedback.mediumImpact();
    _run?.cancel();
  }

  Future<void> _regenerate() async {
    if (_busy || _chat.messages.isEmpty) return;
    if (_chat.messages.last.role == 'assistant') _chat.messages.removeLast();
    if (_chat.messages.isEmpty || _chat.messages.last.role != 'user') return;
    if (!await _ensureReady()) return;
    await _reply();
  }

  void _editLast(Msg m) {
    if (_busy) return;
    final i = _chat.messages.indexOf(m);
    if (i < 0) return;
    setState(() => _chat.messages.removeRange(i, _chat.messages.length));
    _input.text = m.text;
    _input.selection = TextSelection.collapsed(offset: m.text.length);
    _focus.requestFocus();
  }

  @override
  Widget build(BuildContext context) {
    final msgs = _chat.messages;
    final empty = msgs.isEmpty;
    return Scaffold(
      resizeToAvoidBottomInset: true,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            _TopBar(
              onMenu: widget.onMenu,
              onNew: empty ? null : widget.onNew,
              center: _target != null
                  ? _Pill(dot: Afh.good, label: _target!.computer.name, onTap: _pickTarget)
                  : _Pill(
                      dot: _provider.ready ? _provider.color : Afh.text3,
                      label: _provider.ready && _chat.model.isNotEmpty ? _chat.model : 'Choose a model',
                      onTap: _busy ? null : _pickModel,
                    ),
            ),
            Expanded(
              child: AnimatedSwitcher(
                duration: Afh.med,
                child: empty
                    ? _Hero(
                        key: const ValueKey('hero'),
                        target: _target,
                        // a task for the PC is put in the box to look over first; a chat question is just asked
                        onPrompt: _target == null
                            ? _send
                            : (t) {
                                _input.text = t;
                                _input.selection = TextSelection.collapsed(offset: t.length);
                                _focus.requestFocus();
                              },
                      )
                    : ListView.builder(
                        key: const ValueKey('list'),
                        controller: _scroll,
                        reverse: true,
                        keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
                        padding: const EdgeInsets.fromLTRB(18, 8, 18, 12),
                        itemCount: msgs.length,
                        itemBuilder: (_, i) {
                          final m = msgs[msgs.length - 1 - i];
                          final isLast = i == 0;
                          final fresh = DateTime.now().difference(m.at).inMilliseconds < 1200;
                          Widget w = m.role == 'user'
                              ? _UserBubble(msg: m, onEdit: !_busy && (isLast || (i == 1 && msgs.last.role == 'assistant')) ? () => _editLast(m) : null)
                              : _Reply(msg: m, live: identical(m, _live), onRetry: isLast && !_busy ? _regenerate : null);
                          if (fresh) w = w.animate().fadeIn(duration: 240.ms).moveY(begin: 10, end: 0, curve: Afh.ease, duration: 360.ms);
                          return KeyedSubtree(key: ObjectKey(m), child: w);
                        },
                      ),
              ),
            ),
            if (empty && _target == null) _StatusPill(onTap: widget.onComputers),
            Composer(
              controller: _input,
              focus: _focus,
              busy: _busy,
              onSend: () => _send(),
              onStop: _stop,
              bottom: safeBottom(context),
              hint: _target != null ? 'Ask AFH on ${_target!.computer.name}' : 'Message AFH',
              tools: [
                if (empty)
                  ComposerChip(
                    icon: LucideIcons.squareTerminal,
                    label: _target == null ? 'Run on PC' : baseName(_target!.dir),
                    on: _target != null,
                    onTap: _starting ? null : _pickTarget,
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _TopBar extends StatelessWidget {
  const _TopBar({required this.center, this.onMenu, this.onNew});
  final Widget center;
  final VoidCallback? onMenu, onNew;
  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 52,
      child: Stack(
        alignment: Alignment.center,
        children: [
          Positioned(left: 6, child: _MenuButton(onTap: onMenu)),
          Positioned(right: 6, child: IconBtn(LucideIcons.squarePen, tooltip: 'New chat', size: 44, onTap: onNew)),
          Padding(padding: const EdgeInsets.symmetric(horizontal: 60), child: center),
        ],
      ),
    );
  }
}

/// Two lines, the lower one shorter: opens the drawer.
class _MenuButton extends StatelessWidget {
  const _MenuButton({this.onTap});
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) {
    Widget line(double w) => Container(width: w, height: 2, decoration: BoxDecoration(color: Afh.text, borderRadius: BorderRadius.circular(2)));
    return Semantics(
      button: true,
      label: 'Open menu',
      child: Pressable(
        onTap: onTap,
        scale: 0.9,
        child: SizedBox(
          width: 44,
          height: 44,
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(padding: const EdgeInsets.only(left: 12), child: line(19)),
              const SizedBox(height: 6),
              Padding(padding: const EdgeInsets.only(left: 12), child: line(12)),
            ],
          ),
        ),
      ),
    );
  }
}

class _Pill extends StatelessWidget {
  const _Pill({required this.dot, required this.label, this.onTap});
  final Color dot;
  final String label;
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) {
    return Pressable(
      onTap: onTap ?? () {},
      child: Container(
        height: 36,
        padding: const EdgeInsets.symmetric(horizontal: 14),
        decoration: BoxDecoration(color: Afh.surface, borderRadius: BorderRadius.circular(18), border: Border.all(color: Afh.line)),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            AnimatedContainer(duration: Afh.med, width: 8, height: 8, decoration: BoxDecoration(color: dot, shape: BoxShape.circle)),
            const SizedBox(width: 8),
            Flexible(
              child: AnimatedSwitcher(
                duration: Afh.fast,
                child: Text(
                  label,
                  key: ValueKey(label),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontWeight: FontWeight.w500, fontSize: 14, color: Afh.text),
                ),
              ),
            ),
            const SizedBox(width: 6),
            Icon(LucideIcons.chevronDown, size: 15, color: Afh.text3),
          ],
        ),
      ),
    );
  }
}

const _chatIdeas = [
  (LucideIcons.lightbulb, 'Explain how vaccines train the immune system'),
  (LucideIcons.mail, 'Write a friendly follow-up email after an interview'),
  (LucideIcons.plane, 'Plan a relaxed three-day trip to Lisbon'),
];
const _pcIdeas = [
  (LucideIcons.wrench, 'Fix the failing tests in this project'),
  (LucideIcons.folder, 'Explain how this codebase is organized'),
  (LucideIcons.listChecks, 'Review my latest changes and suggest improvements'),
];

class _Hero extends StatelessWidget {
  const _Hero({super.key, required this.target, required this.onPrompt});
  final Target? target;
  final ValueChanged<String> onPrompt;

  String _greeting() {
    final h = DateTime.now().hour;
    return h < 5
        ? 'Up late?'
        : h < 12
        ? 'Good morning'
        : h < 18
        ? 'Good afternoon'
        : 'Good evening';
  }

  @override
  Widget build(BuildContext context) {
    final noProvider = target == null && !providers.any((p) => p.ready);
    final ideas = target != null ? _pcIdeas : _chatIdeas;
    return LayoutBuilder(
      builder: (context, box) => SingleChildScrollView(
        keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
        padding: const EdgeInsets.symmetric(horizontal: 24),
        child: ConstrainedBox(
          constraints: BoxConstraints(minHeight: box.maxHeight),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 16),
              const AfhLogo(width: 58),
              const SizedBox(height: 18),
              Text(_greeting(), style: TextStyle(color: Afh.text3, fontSize: 14, fontWeight: FontWeight.w500)).enter(1),
              const SizedBox(height: 4),
              AnimatedSwitcher(
                duration: Afh.med,
                child: Text(
                  target != null ? 'What should AFH do\non ${target!.computer.name}?' : 'What are we\nbuilding today?',
                  key: ValueKey(target?.computer.id),
                  style: Afh.h1(),
                ),
              ).enter(2),
              const SizedBox(height: 10),
              Text(
                target != null
                    ? 'It works in ${baseName(target!.dir)} and you can follow along live.'
                    : 'Chat with any model, or hand a task to AFH on your computer.',
                style: TextStyle(fontSize: 15, height: 1.5, color: Afh.text2),
              ).enter(3),
              const SizedBox(height: 26),
              if (noProvider)
                _Idea(
                  icon: LucideIcons.keyRound,
                  text: 'Add a model provider to start chatting',
                  accent: true,
                  onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ProvidersScreen())),
                ).enter(4),
              for (final (i, s) in ideas.indexed)
                _Idea(icon: s.$1, text: s.$2, onTap: noProvider ? null : () => onPrompt(s.$2)).enter(4 + i + (noProvider ? 1 : 0)),
              const SizedBox(height: 16),
            ],
          ),
        ),
      ),
    );
  }
}

class _Idea extends StatelessWidget {
  const _Idea({required this.icon, required this.text, this.onTap, this.accent = false});
  final IconData icon;
  final String text;
  final VoidCallback? onTap;
  final bool accent;
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Pressable(
        onTap: onTap,
        scale: 0.98,
        child: AnimatedOpacity(
          duration: Afh.fast,
          opacity: onTap == null ? 0.45 : 1,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 13),
            decoration: BoxDecoration(
              color: accent ? Afh.tint : Colors.transparent,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: accent ? Afh.accent.withValues(alpha: 0.4) : Afh.line),
            ),
            child: Row(
              children: [
                Icon(icon, size: 18, color: accent ? Afh.accent : Afh.text2),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(text, style: TextStyle(fontSize: 14.5, height: 1.3, color: accent ? Afh.text : Afh.text, fontWeight: accent ? FontWeight.w500 : FontWeight.w400)),
                ),
                if (accent) Icon(LucideIcons.chevronRight, size: 17, color: Afh.accent),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// "My-PC is online" over the composer of a new chat; opens Computers.
class _StatusPill extends StatelessWidget {
  const _StatusPill({this.onTap});
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: Account.i,
      builder: (context, _) {
        final a = Account.i;
        final online = a.computers.where((c) => c.online).toList();
        final (Widget lead, String label) = !a.signedIn
            ? (Icon(LucideIcons.laptop, size: 14, color: Afh.text2), 'Connect your computer')
            : a.computers.isEmpty
            ? (Icon(LucideIcons.laptop, size: 14, color: Afh.text2), 'Add AFH on your computer')
            : online.isEmpty
            ? (PulseDot(color: Afh.text3, live: false, size: 7), a.computers.length == 1 ? '${a.computers.first.name} is offline' : 'Your computers are offline')
            : (PulseDot(color: Afh.good, size: 7), online.length == 1 ? '${online.first.name} is online' : '${online.length} computers online');
        return Align(
          alignment: Alignment.centerLeft,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(14, 0, 14, 6),
            child: Pressable(
              onTap: onTap,
              child: Container(
                height: 30,
                padding: const EdgeInsets.only(left: 8, right: 12),
                decoration: BoxDecoration(color: Afh.surface, borderRadius: BorderRadius.circular(15)),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    lead,
                    const SizedBox(width: 6),
                    Text(label, style: TextStyle(fontSize: 12.5, color: Afh.text2)),
                  ],
                ),
              ),
            ),
          ),
        ).animate().fadeIn(delay: 250.ms);
      },
    );
  }
}

/// Picks the computer and project a "Run on PC" message goes to. Pops a Target, or false to turn it off.
class _TargetSheet extends StatefulWidget {
  const _TargetSheet({this.current});
  final Target? current;
  @override
  State<_TargetSheet> createState() => _TargetSheetState();
}

class _TargetSheetState extends State<_TargetSheet> {
  final Map<String, List<String>?> _projects = {}; // computer id → its project folders (null while loading)
  final Map<String, String> _errors = {};

  @override
  void initState() {
    super.initState();
    for (final c in Account.i.computers.where((c) => c.online)) {
      _load(c);
    }
  }

  Future<void> _load(Computer c) async {
    setState(() {
      _projects[c.id] = null;
      _errors.remove(c.id);
    });
    try {
      final s = await Pc(c).get('/api/settings');
      _projects[c.id] = [
        for (final p in (s['projects'] as List? ?? []))
          if (p is String && p.isNotEmpty) p,
      ];
    } on ApiError catch (e) {
      _errors[c.id] = e.message;
      _projects[c.id] = [];
    }
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final online = Account.i.computers.where((c) => c.online).toList();
    return SafeArea(
      child: ConstrainedBox(
        constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(context).height * 0.75),
        child: ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 4),
              child: Text('Run on a computer', style: Afh.h2()),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(4, 6, 4, 4),
              child: Text('AFH starts a new thread there with your message, in the project you pick.', style: Afh.small),
            ),
            for (final c in online) ...[
              SectionLabel(c.name),
              if (_projects[c.id] == null)
                const Padding(padding: EdgeInsets.all(18), child: Center(child: SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))))
              else if (_errors[c.id] != null)
                Group(children: [Tile(icon: LucideIcons.circleAlert, title: 'Couldn\'t load projects', subtitle: _errors[c.id], onTap: () => _load(c), trailing: Icon(LucideIcons.refreshCw, size: 16, color: Afh.text3))])
              else if (_projects[c.id]!.isEmpty)
                Group(children: [Tile(icon: LucideIcons.folder, title: 'No projects yet', subtitle: 'Open a project folder in AFH on ${c.name} first.')])
              else
                Group(
                  children: [
                    for (final p in _projects[c.id]!)
                      Tile(
                        icon: LucideIcons.folder,
                        title: baseName(p),
                        subtitle: p,
                        trailing: widget.current?.computer.id == c.id && widget.current?.dir == p ? Icon(LucideIcons.check, size: 18, color: Afh.accent) : null,
                        chevron: false,
                        onTap: () => Navigator.pop(context, (computer: c, dir: p)),
                      ),
                  ],
                ),
            ],
            if (widget.current != null) ...[
              const SizedBox(height: 18),
              SecondaryButton(label: 'Chat with a model instead', icon: LucideIcons.messageCircle, expand: true, onTap: () => Navigator.pop(context, false)),
            ],
          ],
        ),
      ),
    );
  }
}

class _UserBubble extends StatelessWidget {
  const _UserBubble({required this.msg, this.onEdit});
  final Msg msg;
  final VoidCallback? onEdit;
  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerRight,
      child: GestureDetector(
        onLongPress: () => _bubbleMenu(context),
        child: Container(
          constraints: BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * 0.8),
          margin: const EdgeInsets.only(top: 14, bottom: 4),
          padding: const EdgeInsets.symmetric(horizontal: 15, vertical: 10),
          decoration: BoxDecoration(
            color: Afh.p.bubble,
            borderRadius: const BorderRadius.only(
              topLeft: Radius.circular(20),
              topRight: Radius.circular(20),
              bottomLeft: Radius.circular(20),
              bottomRight: Radius.circular(6),
            ),
          ),
          child: Text(msg.text, style: TextStyle(fontSize: 15.5, height: 1.45, color: Afh.text)),
        ),
      ),
    );
  }

  Future<void> _bubbleMenu(BuildContext context) async {
    final v = await showActions<String>(
      context,
      actions: [
        const SheetAction(LucideIcons.copy, 'Copy', 'copy'),
        if (onEdit != null) const SheetAction(LucideIcons.pencil, 'Edit and resend', 'edit'),
      ],
    );
    if (v == 'copy') {
      await Clipboard.setData(ClipboardData(text: msg.text));
      if (context.mounted) showToast(context, 'Copied');
    } else if (v == 'edit') {
      onEdit?.call();
    }
  }
}

class _Reply extends StatefulWidget {
  const _Reply({required this.msg, required this.live, this.onRetry});
  final Msg msg;
  final bool live;
  final VoidCallback? onRetry;
  @override
  State<_Reply> createState() => _ReplyState();
}

class _ReplyState extends State<_Reply> {
  bool _thoughtsOpen = false;
  bool _copied = false;

  @override
  Widget build(BuildContext context) {
    final m = widget.msg;
    final thinking = widget.live && m.text.isEmpty;
    return Padding(
      padding: const EdgeInsets.only(top: 16, bottom: 2),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (m.reasoning.trim().isNotEmpty) _thoughts(m),
          if (thinking && m.reasoning.trim().isEmpty) const Padding(padding: EdgeInsets.symmetric(vertical: 8, horizontal: 2), child: TypingDots()),
          if (m.text.isNotEmpty) Md(m.text),
          if (m.error != null) _error(m.error!),
          if (!widget.live && m.text.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Row(
                children: [
                  _Act(
                    icon: _copied ? LucideIcons.check : LucideIcons.copy,
                    tooltip: 'Copy',
                    color: _copied ? Afh.good : null,
                    onTap: () async {
                      await Clipboard.setData(ClipboardData(text: m.text));
                      setState(() => _copied = true);
                      await Future.delayed(const Duration(milliseconds: 1500));
                      if (mounted) setState(() => _copied = false);
                    },
                  ),
                  _Act(icon: LucideIcons.textSelect, tooltip: 'Select text', onTap: () => _selectSheet(context, m.text)),
                  if (widget.onRetry != null) _Act(icon: LucideIcons.refreshCw, tooltip: 'Try again', onTap: widget.onRetry!),
                  const SizedBox(width: 6),
                  if (m.model != null)
                    Flexible(
                      child: Text(m.model!, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: Afh.text3, fontSize: 12)),
                    ),
                ],
              ),
            ).animate().fadeIn(duration: 250.ms),
        ],
      ),
    );
  }

  Widget _thoughts(Msg m) {
    final live = widget.live && m.text.isEmpty;
    final label = Text(live ? 'Thinking' : 'Thoughts', style: TextStyle(fontWeight: FontWeight.w500, fontSize: 14, color: Afh.text2));
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Pressable(
            scale: 0.98,
            onTap: () => setState(() => _thoughtsOpen = !_thoughtsOpen),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(LucideIcons.brain, size: 16, color: Afh.text3),
                  const SizedBox(width: 8),
                  live ? label.animate(onPlay: (c) => c.repeat()).shimmer(duration: 1500.ms, color: Afh.text) : label,
                  const SizedBox(width: 4),
                  AnimatedRotation(
                    turns: _thoughtsOpen ? 0.25 : 0,
                    duration: Afh.fast,
                    child: Icon(LucideIcons.chevronRight, size: 15, color: Afh.text3),
                  ),
                ],
              ),
            ),
          ),
          AnimatedSize(
            duration: Afh.med,
            curve: Afh.ease,
            alignment: Alignment.topCenter,
            child: _thoughtsOpen || live
                ? Container(
                    margin: const EdgeInsets.only(top: 6, left: 7),
                    padding: const EdgeInsets.only(left: 14),
                    decoration: BoxDecoration(border: Border(left: BorderSide(color: Afh.line2, width: 2))),
                    child: Text(
                      live && !_thoughtsOpen && m.reasoning.length > 280 ? '…${m.reasoning.substring(m.reasoning.length - 280)}' : m.reasoning.trim(),
                      style: TextStyle(color: Afh.text3, fontSize: 13.5, height: 1.5),
                    ),
                  )
                : const SizedBox(width: double.infinity),
          ),
        ],
      ),
    );
  }

  Widget _error(String e) {
    return Container(
      margin: const EdgeInsets.only(top: 6),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Afh.bad.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(Afh.r),
        border: Border.all(color: Afh.bad.withValues(alpha: 0.3)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(padding: const EdgeInsets.only(top: 1), child: Icon(LucideIcons.circleAlert, color: Afh.bad, size: 18)),
          const SizedBox(width: 10),
          Expanded(child: Text(e, style: TextStyle(color: Afh.text, height: 1.4, fontSize: 14))),
          if (widget.onRetry != null) ...[
            const SizedBox(width: 8),
            GestureDetector(
              onTap: widget.onRetry,
              child: Text('Retry', style: TextStyle(color: Afh.accent, fontWeight: FontWeight.w600)),
            ),
          ],
        ],
      ),
    ).animate().shakeX(hz: 4, amount: 2, duration: 350.ms);
  }

  void _selectSheet(BuildContext context, String text) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (ctx) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.7,
        maxChildSize: 0.95,
        builder: (_, scroll) => SingleChildScrollView(
          controller: scroll,
          padding: const EdgeInsets.fromLTRB(22, 0, 22, 30),
          child: SelectableText(text, style: TextStyle(fontSize: 15.5, height: 1.55, color: Afh.text)),
        ),
      ),
    );
  }
}

class _Act extends StatelessWidget {
  const _Act({required this.icon, required this.tooltip, required this.onTap, this.color});
  final IconData icon;
  final String tooltip;
  final VoidCallback onTap;
  final Color? color;
  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: Semantics(
        button: true,
        label: tooltip,
        child: Pressable(
          onTap: onTap,
          scale: 0.85,
          child: SizedBox(
            width: 36,
            height: 36,
            child: AnimatedSwitcher(
              duration: Afh.fast,
              child: Icon(icon, key: ValueKey(icon), size: 16, color: color ?? Afh.text3),
            ),
          ),
        ),
      ),
    );
  }
}
