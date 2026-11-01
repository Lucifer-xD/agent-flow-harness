// A direct chat with a model: replies stream in word by word, thinking folds away, and every
// reply can be copied or tried again. The model chip at the top switches model mid-chat.
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_animate/flutter_animate.dart';

import '../ai.dart';
import '../store.dart';
import '../theme.dart';
import '../widgets/badge.dart';
import '../widgets/common.dart';
import '../widgets/composer.dart';
import '../widgets/logo.dart';
import '../widgets/md.dart';
import 'chats.dart' show promptText, suggestions;
import 'model_picker.dart';
import 'providers.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key, this.chat, this.prompt});
  final Chat? chat;
  final String? prompt;
  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  late Chat _chat;
  Run? _run;
  Msg? _live;
  final _input = TextEditingController();
  final _focus = FocusNode();
  final _scroll = ScrollController();
  bool _frame = false;

  bool get _busy => _run != null;

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
    if (widget.prompt != null) WidgetsBinding.instance.addPostFrameCallback((_) => _send(widget.prompt!));
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
    if (!await _ensureReady()) return;
    HapticFeedback.lightImpact();
    _input.clear();
    if (_chat.title.isEmpty) _chat.title = titleFrom(t);
    _chat.messages.add(Msg(role: 'user', text: t));
    await _reply();
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

  Future<void> _menu(String v) async {
    switch (v) {
      case 'rename':
        final name = await promptText(context, title: 'Rename chat', initial: _chat.title, hint: 'Chat name');
        if (name != null && name.trim().isNotEmpty) {
          setState(() => _chat.title = name.trim());
          Chats.i.save(_chat, now: true);
        }
      case 'copy':
        final all = _chat.messages.map((m) => '${m.role == 'user' ? 'You' : (m.model ?? 'AI')}:\n${m.text}').join('\n\n');
        await Clipboard.setData(ClipboardData(text: all));
        if (mounted) showToast(context, 'Chat copied');
      case 'delete':
        _run?.cancel();
        Chats.i.delete(_chat);
        _chat.messages.clear();
        if (mounted) Navigator.pop(context);
    }
  }

  @override
  Widget build(BuildContext context) {
    final msgs = _chat.messages;
    final bottomInset = MediaQuery.paddingOf(context).bottom;
    return Scaffold(
      extendBodyBehindAppBar: true,
      resizeToAvoidBottomInset: true,
      appBar: AppBar(
        toolbarHeight: 60,
        flexibleSpace: const _TopFade(),
        titleSpacing: 0,
        centerTitle: true,
        title: _ModelChip(provider: _provider, model: _chat.model, onTap: _busy ? null : _pickModel),
        actions: [
          IconButton(
            tooltip: 'New chat',
            onPressed: msgs.isEmpty ? null : () => Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => const ChatScreen())),
            icon: const Icon(Icons.edit_square, size: 21),
          ),
          PopupMenuButton<String>(
            onSelected: _menu,
            color: Afh.surface2,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
            enabled: msgs.isNotEmpty,
            itemBuilder: (_) => const [
              PopupMenuItem(value: 'rename', child: Text('Rename')),
              PopupMenuItem(value: 'copy', child: Text('Copy chat')),
              PopupMenuItem(
                value: 'delete',
                child: Text('Delete', style: TextStyle(color: Afh.bad)),
              ),
            ],
          ),
        ],
      ),
      body: Stack(
        children: [
          const Positioned.fill(child: Aurora(intensity: 0.55)),
          Column(
            children: [
              Expanded(
                child: msgs.isEmpty
                    ? _Empty(provider: _provider, onPrompt: _send)
                    : ListView.builder(
                        controller: _scroll,
                        reverse: true,
                        keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
                        padding: EdgeInsets.fromLTRB(16, MediaQuery.paddingOf(context).top + 70, 16, 12),
                        itemCount: msgs.length,
                        itemBuilder: (_, i) {
                          final m = msgs[msgs.length - 1 - i];
                          final isLast = i == 0;
                          final fresh = DateTime.now().difference(m.at).inMilliseconds < 1200;
                          Widget w = m.role == 'user'
                              ? _UserBubble(msg: m, onEdit: !_busy && (isLast || (i == 1 && msgs.last.role == 'assistant')) ? () => _editLast(m) : null)
                              : _Reply(
                                  msg: m,
                                  provider: providerById(_chat.provider),
                                  live: identical(m, _live),
                                  last: isLast,
                                  onRetry: isLast && !_busy ? _regenerate : null,
                                );
                          if (fresh) w = w.animate().fadeIn(duration: 300.ms).moveY(begin: 14, end: 0, curve: Afh.ease, duration: 450.ms);
                          return KeyedSubtree(key: ObjectKey(m), child: w);
                        },
                      ),
              ),
              Composer(
                controller: _input,
                focus: _focus,
                busy: _busy,
                onSend: () => _send(),
                onStop: _stop,
                bottom: bottomInset,
                hint: _provider.ready ? 'Message ${_chat.model.isEmpty ? _provider.name : _chat.model}' : 'Add a provider to start',
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _TopFade extends StatelessWidget {
  const _TopFade();
  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [Afh.bg, Color(0xE60B0908), Color(0x000B0908)],
          stops: [0, 0.6, 1],
        ),
      ),
    );
  }
}

class _ModelChip extends StatelessWidget {
  const _ModelChip({required this.provider, required this.model, this.onTap});
  final Provider provider;
  final String model;
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) {
    return Pressable(
      onTap: onTap ?? () {},
      child: Container(
        padding: const EdgeInsets.fromLTRB(6, 6, 12, 6),
        decoration: BoxDecoration(
          color: Afh.surface2.withValues(alpha: 0.9),
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: Afh.line2),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            ProviderBadge(provider, size: 26),
            const SizedBox(width: 8),
            ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 170),
              child: AnimatedSwitcher(
                duration: const Duration(milliseconds: 250),
                child: Text(
                  model.isEmpty ? 'Choose a model' : model,
                  key: ValueKey(model),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14),
                ),
              ),
            ),
            const SizedBox(width: 4),
            const Icon(Icons.keyboard_arrow_down_rounded, size: 20, color: Afh.text2),
          ],
        ),
      ),
    );
  }
}

class _Empty extends StatelessWidget {
  const _Empty({required this.provider, required this.onPrompt});
  final Provider provider;
  final ValueChanged<String> onPrompt;
  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: EdgeInsets.fromLTRB(20, MediaQuery.paddingOf(context).top + 90, 20, 20),
      children: [
        const Center(child: AfhLogo(width: 130, working: true)),
        const SizedBox(height: 26),
        Center(child: GradText('How can I help?', style: Afh.h1())).animate().fadeIn(delay: 300.ms).moveY(begin: 10, end: 0, curve: Afh.ease),
        const SizedBox(height: 8),
        Text(
          'Chatting with ${provider.name} straight from your phone.',
          textAlign: TextAlign.center,
          style: const TextStyle(color: Afh.text2),
        ).animate().fadeIn(delay: 380.ms),
        const SizedBox(height: 28),
        GridView.count(
          crossAxisCount: 2,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          mainAxisSpacing: 10,
          crossAxisSpacing: 10,
          childAspectRatio: 1.25,
          children: [
            for (final (i, s) in suggestions.indexed)
              Pressable(
                    onTap: () => onPrompt('${s.$2} ${s.$3}'),
                    child: Container(
                      padding: const EdgeInsets.all(14),
                      decoration: BoxDecoration(
                        color: Afh.surface.withValues(alpha: 0.75),
                        borderRadius: BorderRadius.circular(22),
                        border: Border.all(color: Afh.line),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          IconTile(s.$1, size: 36),
                          const Spacer(),
                          Text(s.$2, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
                          const SizedBox(height: 2),
                          Text(
                            s.$3,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(color: Afh.text2, fontSize: 12.5, height: 1.3),
                          ),
                        ],
                      ),
                    ),
                  )
                  .animate()
                  .fadeIn(delay: (420 + i * 70).ms)
                  .scale(begin: const Offset(0.92, 0.92), delay: (420 + i * 70).ms, curve: Afh.spring, duration: 550.ms),
          ],
        ),
      ],
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
          margin: const EdgeInsets.only(left: 48, top: 10, bottom: 6),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 11),
          decoration: BoxDecoration(
            gradient: const LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [Color(0xFF3B2416), Color(0xFF3A1928)]),
            borderRadius: const BorderRadius.only(
              topLeft: Radius.circular(22),
              topRight: Radius.circular(22),
              bottomLeft: Radius.circular(22),
              bottomRight: Radius.circular(7),
            ),
            border: Border.all(color: Afh.orange.withValues(alpha: 0.28)),
          ),
          child: Text(msg.text, style: const TextStyle(fontSize: 15.5, height: 1.45, color: Color(0xFFFFF3EA))),
        ),
      ),
    );
  }

  Future<void> _bubbleMenu(BuildContext context) async {
    HapticFeedback.mediumImpact();
    final v = await showModalBottomSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(leading: const Icon(Icons.copy_rounded), title: const Text('Copy'), onTap: () => Navigator.pop(ctx, 'copy')),
            if (onEdit != null)
              ListTile(leading: const Icon(Icons.edit_rounded), title: const Text('Edit and resend'), onTap: () => Navigator.pop(ctx, 'edit')),
            const SizedBox(height: 8),
          ],
        ),
      ),
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
  const _Reply({required this.msg, required this.provider, required this.live, required this.last, this.onRetry});
  final Msg msg;
  final Provider provider;
  final bool live;
  final bool last;
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
      padding: const EdgeInsets.only(top: 14, bottom: 4, right: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              ProviderBadge(widget.provider, size: 24),
              const SizedBox(width: 8),
              Flexible(
                child: Text(
                  m.model ?? widget.provider.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: Afh.text3, fontSize: 12.5, fontWeight: FontWeight.w600),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          if (m.reasoning.trim().isNotEmpty) _thoughts(m),
          if (thinking && m.reasoning.trim().isEmpty) const Padding(padding: EdgeInsets.symmetric(vertical: 8, horizontal: 2), child: TypingDots()),
          if (m.text.isNotEmpty) Md(m.text),
          if (m.error != null) _error(m.error!),
          if (!widget.live && m.text.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Row(
                children: [
                  _Act(
                    icon: _copied ? Icons.check_rounded : Icons.copy_rounded,
                    label: _copied ? 'Copied' : 'Copy',
                    color: _copied ? Afh.good : null,
                    onTap: () async {
                      await Clipboard.setData(ClipboardData(text: m.text));
                      setState(() => _copied = true);
                      await Future.delayed(const Duration(milliseconds: 1500));
                      if (mounted) setState(() => _copied = false);
                    },
                  ),
                  _Act(icon: Icons.text_fields_rounded, label: 'Select', onTap: () => _selectSheet(context, m.text)),
                  if (widget.onRetry != null) _Act(icon: Icons.refresh_rounded, label: 'Retry', onTap: widget.onRetry!),
                ],
              ),
            ).animate().fadeIn(duration: 300.ms),
        ],
      ),
    );
  }

  Widget _thoughts(Msg m) {
    final live = widget.live && m.text.isEmpty;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Pressable(
        scale: 0.99,
        onTap: () => setState(() => _thoughtsOpen = !_thoughtsOpen),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 300),
          curve: Afh.ease,
          width: double.infinity,
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: Colors.white.withValues(alpha: 0.035),
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: Afh.line),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(Icons.psychology_alt_rounded, size: 18, color: Afh.amber),
                  const SizedBox(width: 8),
                  live
                      ? const Text(
                          'Thinking…',
                          style: TextStyle(fontWeight: FontWeight.w600, color: Afh.text2),
                        ).animate(onPlay: (c) => c.repeat()).shimmer(duration: 1400.ms, color: Afh.amber)
                      : const Text(
                          'Thoughts',
                          style: TextStyle(fontWeight: FontWeight.w600, color: Afh.text2),
                        ),
                  const Spacer(),
                  AnimatedRotation(
                    turns: _thoughtsOpen ? 0.5 : 0,
                    duration: const Duration(milliseconds: 250),
                    child: const Icon(Icons.keyboard_arrow_down_rounded, size: 20, color: Afh.text3),
                  ),
                ],
              ),
              AnimatedSize(
                duration: const Duration(milliseconds: 320),
                curve: Afh.ease,
                alignment: Alignment.topCenter,
                child: _thoughtsOpen || live
                    ? Padding(
                        padding: const EdgeInsets.only(top: 8),
                        child: Text(
                          live && !_thoughtsOpen && m.reasoning.length > 280 ? '…${m.reasoning.substring(m.reasoning.length - 280)}' : m.reasoning.trim(),
                          style: const TextStyle(color: Afh.text3, fontSize: 13.5, height: 1.45),
                        ),
                      )
                    : const SizedBox(width: double.infinity),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _error(String e) {
    return Container(
      margin: const EdgeInsets.only(top: 6),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Afh.bad.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Afh.bad.withValues(alpha: 0.35)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.error_outline_rounded, color: Afh.bad, size: 20),
          const SizedBox(width: 10),
          Expanded(
            child: Text(e, style: const TextStyle(color: Color(0xFFFFC2CD), height: 1.4)),
          ),
          if (widget.onRetry != null) ...[
            const SizedBox(width: 6),
            GestureDetector(
              onTap: widget.onRetry,
              child: const Text(
                'Retry',
                style: TextStyle(color: Afh.orange, fontWeight: FontWeight.w700),
              ),
            ),
          ],
        ],
      ),
    ).animate().shakeX(hz: 4, amount: 3, duration: 400.ms);
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
          child: SelectableText(text, style: const TextStyle(fontSize: 15.5, height: 1.55)),
        ),
      ),
    );
  }
}

class _Act extends StatelessWidget {
  const _Act({required this.icon, required this.label, required this.onTap, this.color});
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final Color? color;
  @override
  Widget build(BuildContext context) {
    return Pressable(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(2, 6, 14, 6),
        child: AnimatedSwitcher(
          duration: const Duration(milliseconds: 200),
          child: Row(
            key: ValueKey(label),
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 16, color: color ?? Afh.text3),
              const SizedBox(width: 5),
              Text(
                label,
                style: TextStyle(fontSize: 12.5, color: color ?? Afh.text3, fontWeight: FontWeight.w600),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
