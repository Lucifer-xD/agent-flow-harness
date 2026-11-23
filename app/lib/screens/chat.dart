// A chat on the phone.
import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:share_plus/share_plus.dart';

import '../core/ai.dart';
import '../core/l10n.dart';
import '../core/native.dart';
import '../core/runs.dart';
import '../core/store.dart';
import '../core/voice.dart';
import '../ui/badge.dart';
import '../ui/composer.dart';
import '../ui/convo.dart';
import '../ui/kit.dart';
import '../ui/look.dart';
import '../ui/media.dart';
import '../ui/motion.dart';
import 'assistants.dart';
import 'pick.dart';
import 'providers.dart';
import 'talk.dart';

Chat newChat({Assistant? assistant, bool temporary = false}) {
  var m = firstModel();
  final own = assistant?.model;
  if (own != null && own.contains('/')) {
    final pid = own.substring(0, own.indexOf('/'));
    if (providers.any((p) => p.id == pid && p.ready)) m = (pid, own.substring(pid.length + 1));
  }
  return Chat(id: newId(), provider: m?.$1 ?? '', model: m?.$2 ?? '', assistant: assistant?.id, temporary: temporary);
}

/// Adds the user's message and starts the reply.
void sendTo(Chat c, String text, List<Att> files) {
  c.messages.add(Msg(role: 'user', text: text, files: files));
  if (c.title.isEmpty) c.title = text.isEmpty ? (files.firstOrNull?.label ?? t('Photo')) : titleFrom(text);
  c.updated = DateTime.now();
  Chats.i.save(c);
  Settings.i.lastModel = '${c.provider}/${c.model}';
  Runs.i.start(c);
}

class ChatScreen extends StatefulWidget {
  const ChatScreen(this.chat, {super.key, this.text, this.files, this.focus = false, this.at});
  final Chat chat;
  final String? text; // put in the box, not sent
  final List<Att>? files;
  final bool focus;
  final String? at;
  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  late Chat c = widget.chat;
  final _scroll = ScrollController();
  final _text = TextEditingController();
  final _focus = FocusNode();
  late final List<Att> _files = [...?widget.files];
  Msg? _editing;

  @override
  void initState() {
    super.initState();
    if (widget.text != null) {
      _text.text = widget.text!;
    } else {
      _text.text = Settings.i.str('draft.${c.messages.isEmpty ? 'new' : c.id}');
    }
    Runs.i.addListener(_redraw);
    Chats.i.addListener(_redraw);
  }

  void _redraw() => mounted ? setState(() {}) : null;

  @override
  void dispose() {
    Runs.i.removeListener(_redraw);
    Chats.i.removeListener(_redraw);
    if (c.temporary) {
      Runs.i.of(c.id)?.stop();
      for (final m in c.messages) {
        m.files.forEach(Media.drop);
      }
    }
    _scroll.dispose();
    _text.dispose();
    _focus.dispose();
    super.dispose();
  }

  LiveRun? get _run => Runs.i.of(c.id);
  bool get _ready => providers.any((p) => p.id == c.provider && p.ready) && c.model.isNotEmpty;

  Future<bool> _send(String text, List<Att> files) async {
    if (!_ready) {
      final m = firstModel();
      if (m == null) {
        await go(context, const ProvidersScreen());
        final again = firstModel();
        if (again == null) return false;
        c.provider = again.$1;
        c.model = again.$2;
      } else {
        c.provider = m.$1;
        c.model = m.$2;
      }
    }
    if (_run != null) return false;
    final e = _editing;
    if (e != null) {
      final at = c.messages.indexOf(e);
      if (at >= 0) {
        final kept = e.files;
        c.messages.removeRange(at, c.messages.length);
        files = [...kept, ...files];
      }
      _editing = null;
    }
    Settings.i.put('draft.new', null, quiet: true);
    sendTo(c, text, files);
    setState(() {});
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) _scroll.animateTo(0, duration: slow, curve: Curves.easeOutQuint);
    });
    if (!Settings.i.flag('asked.notify')) {
      Settings.i.put('asked.notify', true, quiet: true);
      Runs.i.of(c.id)?.whenDone(Notify.allowed);
    }
    return true;
  }

  Future<void> _model() async {
    final got = await pickModel(context, phoneModels(), current: '${c.provider}/${c.model}', effort: c.effort, phone: true);
    if (got == null || !mounted) return;
    setState(() {
      c.provider = got.row.pid;
      c.model = got.row.id;
      c.effort = got.effort;
    });
    Settings.i.lastModel = got.row.key;
    if (c.messages.isNotEmpty) Chats.i.save(c);
  }

  void _again({bool ask = false}) async {
    if (_run != null) return;
    if (ask) {
      await _model();
      if (!mounted) return;
    }
    while (c.messages.isNotEmpty && c.messages.last.role == 'assistant') {
      c.messages.removeLast();
    }
    if (c.messages.isEmpty) return;
    Runs.i.start(c);
    setState(() {});
  }

  void _edit(Msg m) {
    setState(() {
      _editing = m;
      _text.text = m.text;
    });
    _focus.requestFocus();
  }

  void _cutFrom(Msg m) {
    final at = c.messages.indexOf(m);
    if (at < 0) return;
    setState(() => c.messages.removeRange(at, c.messages.length));
    c.messages.isEmpty ? Chats.i.delete(c) : Chats.i.save(c);
  }

  void _branch(Msg m) {
    final at = c.messages.indexOf(m);
    final n = Chat(
      id: newId(),
      provider: c.provider,
      model: c.model,
      title: c.title,
      effort: c.effort,
      assistant: c.assistant,
      messages: [for (final x in c.messages.take(at + 1)) Msg.fromJson(x.toJson())],
    );
    Chats.i.save(n, now: true);
    setState(() => c = n);
    toast(context, t('This is a copy of the chat up to here'), icon: LucideIcons.gitBranch);
  }

  Future<void> _menuMine(Msg m) => actions(context, [
    Act(t('Copy'), LucideIcons.copy, () => copyText(context, m.text)),
    Act(t('Edit and send again'), LucideIcons.pencil, () => _edit(m)),
    Act(t('Select text'), LucideIcons.textSelect, () => selectSheet(context, m.text)),
    Act(t('Branch from here'), LucideIcons.gitBranch, () => _branch(m)),
    Act(t('Delete from here'), LucideIcons.trash2, () => _cutFrom(m), danger: true),
  ]);

  Future<void> _menuReply(Msg m) => actions(context, [
    Act(t('Select text'), LucideIcons.textSelect, () => selectSheet(context, m.text)),
    Act(t('Share'), LucideIcons.share2, () => SharePlus.instance.share(ShareParams(text: m.text))),
    Act(t('Try again with another model'), LucideIcons.shuffle, () => _again(ask: true)),
    Act(t('Branch from here'), LucideIcons.gitBranch, () => _branch(m)),
    Act(t('Delete from here'), LucideIcons.trash2, () => _cutFrom(m), danger: true),
  ]);

  Future<void> _menu() => actions(context, title: c.title, [
    Act(t('Rename'), LucideIcons.pencil, () async {
      final n = await askText(context, t('Rename'), value: c.title);
      if (n == null || n.isEmpty) return;
      setState(() => c.title = n);
      Chats.i.save(c);
    }),
    Act(c.pinned ? t('Unpin') : t('Pin'), c.pinned ? LucideIcons.pinOff : LucideIcons.pin, () {
      c.pinned = !c.pinned;
      Chats.i.save(c);
    }),
    Act(t('Assistant'), LucideIcons.sparkles, () async {
      final a = await pickAssistant(context, c.assistant);
      if (a == null) return;
      setState(() => c.assistant = a.id.isEmpty ? null : a.id);
      Chats.i.save(c);
    }),
    Act(t('Share the chat'), LucideIcons.share2, () => SharePlus.instance.share(ShareParams(text: c.export(), subject: c.title))),
    Act(t('Save as Markdown'), LucideIcons.fileDown, () => exportChat(c)),
    Act(c.archived ? t('Move out of the archive') : t('Archive'), LucideIcons.archive, () {
      c.archived = !c.archived;
      Chats.i.save(c, now: true);
      if (c.archived && mounted) Navigator.pop(context);
    }),
    Act(t('Delete'), LucideIcons.trash2, () async {
      if (!await confirm(context, t('Delete this chat?'), t('It is removed from this phone for good.'), t('Delete'), danger: true)) return;
      _run?.stop();
      Chats.i.delete(c);
      if (mounted) Navigator.pop(context);
    }, danger: true),
  ]);

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final mq = MediaQuery.paddingOf(context);
    final kb = MediaQuery.viewInsetsOf(context).bottom;
    final run = _run;
    final a = Settings.i.assistant(c.assistant);
    final provider = providers.where((x) => x.id == c.provider).firstOrNull;
    return Scaffold(
      backgroundColor: p.bg,
      resizeToAvoidBottomInset: true,
      body: Column(
        children: [
          Expanded(
            child: Stack(
              children: [
                ConvoScroll(
                  controller: _scroll,
                  top: mq.top + 60,
                  bottom: 14,
                  count: c.messages.length,
                  live: run != null,
                  empty: _Hello(assistant: a, temporary: c.temporary, onPick: (s) => _text.value = TextEditingValue(text: s, selection: TextSelection.collapsed(offset: s.length)), focus: _focus),
                  builder: (i) {
                    final m = c.messages[i];
                    if (m.role == 'user') {
                      return Mine(m.text, shots: [for (final f in m.files) Shot.local(f)], onLong: () => _menuMine(m));
                    }
                    return _Reply(
                      m,
                      key: ValueKey(m.at),
                      run: run?.msg == m ? run : null,
                      last: i == c.messages.length - 1,
                      onAgain: _again,
                      onMenu: () => _menuReply(m),
                      provider: c.provider,
                    );
                  },
                ),
                _Bar(
                  title: c.temporary ? t('Temporary chat') : (c.messages.isEmpty ? (a?.name ?? t('New chat')) : c.title),
                  sub: c.messages.isEmpty ? null : a?.name,
                  onTitle: c.messages.isEmpty || c.temporary ? null : _menu,
                  actions: [
                    if (c.messages.isEmpty)
                      Ic(LucideIcons.ghost, color: c.temporary ? p.accent : p.text2, tip: t('Temporary chat'), onTap: () => setState(() => c = newChat(temporary: !c.temporary)))
                    else ...[
                      Ic(LucideIcons.squarePen, tip: t('New chat'), color: p.text2, onTap: () => Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => ChatScreen(newChat(), focus: true)))),
                      if (!c.temporary) Ic(LucideIcons.ellipsis, tip: t('More'), color: p.text2, onTap: _menu),
                    ],
                  ],
                ),
                PositionedDirectional(end: gutter, bottom: 10, child: ToEnd(_scroll, live: run != null)),
              ],
            ),
          ),
          Padding(
            padding: EdgeInsets.fromLTRB(12, 0, 12, kb > 0 ? 8 : 10 + mq.bottom),
            child: Composer(
              controller: _text,
              files: _files,
              focus: _focus,
              auto: widget.focus,
              hint: a == null ? t('Ask anything') : t('Message {}', a.name),
              draft: c.temporary ? null : (c.messages.isEmpty ? 'new' : c.id),
              running: run != null,
              onStop: () => run?.stop(),
              onSend: _send,
              canSend: run == null,
              onVoice: () => go(context, TalkScreen(c), over: true).then((_) => _redraw()),
              above: _editing == null
                  ? null
                  : Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Note(
                        t('Editing. The messages after it will be replaced.'),
                        icon: LucideIcons.pencil,
                        action: t('Cancel'),
                        onTap: () => setState(() {
                          _editing = null;
                          _text.clear();
                        }),
                      ),
                    ),
              chips: [
                CChip(
                  !_ready ? t('Choose a model') : prettyModel(c.model),
                  lead: _ready ? Logo(c.provider, name: provider?.name ?? '', model: c.model, size: 15, family: true) : null,
                  icon: _ready ? null : LucideIcons.keyRound,
                  onTap: _model,
                ),
                if (effortsFor(provider ?? providers.first, c.model).isNotEmpty && _ready)
                  CChip(effortName(c.effort), icon: LucideIcons.gauge, onTap: _model, on: c.effort != null),
                if (a != null && c.messages.isEmpty)
                  CChip(
                    a.name,
                    icon: assistantIcon(a.icon),
                    on: true,
                    onTap: () async {
                      final n = await pickAssistant(context, c.assistant);
                      if (n != null) setState(() => c = newChat(assistant: n.id.isEmpty ? null : n));
                    },
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// The bar over a conversation: it fades the text under it instead of drawing a line.
class _Bar extends StatelessWidget {
  const _Bar({required this.title, this.sub, this.onTitle, required this.actions});
  final String title;
  final String? sub;
  final VoidCallback? onTitle;
  final List<Widget> actions;
  @override
  Widget build(BuildContext context) => ConvoBar(title: title, sub: sub, onTitle: onTitle, actions: actions);
}

class ConvoBar extends StatelessWidget {
  const ConvoBar({super.key, required this.title, this.sub, this.subWidget, this.onTitle, this.actions = const [], this.under});
  final String title;
  final String? sub;
  final Widget? subWidget, under;
  final VoidCallback? onTitle;
  final List<Widget> actions;
  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final top = MediaQuery.paddingOf(context).top;
    return Container(
      padding: EdgeInsets.only(top: top),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [p.bg, p.bg, p.bg.withValues(alpha: 0)],
          stops: const [0, .86, 1],
        ),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          SizedBox(
            height: 56,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8),
              child: Row(
                children: [
                  const BackBtn(),
                  Expanded(
                    child: Press(
                      onTap: onTitle,
                      scale: .98,
                      child: Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 6),
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Swap(
                              align: AlignmentDirectional.centerStart.resolve(Directionality.of(context)),
                              child: Text(
                                title,
                                key: ValueKey(title),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: T.h3.copyWith(color: p.text),
                              ),
                            ),
                            if (subWidget != null) subWidget! else if (sub != null) Text(sub!, maxLines: 1, overflow: TextOverflow.ellipsis, style: T.tiny.copyWith(color: p.text3)),
                          ],
                        ),
                      ),
                    ),
                  ),
                  ...actions,
                ],
              ),
            ),
          ),
          ?under,
          const SizedBox(height: 10),
        ],
      ),
    );
  }
}

class _Hello extends StatelessWidget {
  const _Hello({this.assistant, required this.temporary, required this.onPick, required this.focus});
  final Assistant? assistant;
  final bool temporary;
  final ValueChanged<String> onPick;
  final FocusNode focus;

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    if (MediaQuery.viewInsetsOf(context).bottom > 100) return const SizedBox();
    final ideas = [
      (LucideIcons.globe, t('Find out something'), t('Search the web for ')),
      (LucideIcons.penLine, t('Write with me'), t('Help me write ')),
      (LucideIcons.camera, t('Explain a photo'), t('Explain what is in this photo: ')),
      (LucideIcons.code, t('Solve a bug'), t('Why does this code fail? ')),
    ];
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: gutter + 4),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Rise(
            0,
            child: Text(
              temporary ? t('Nothing here is kept.') : (assistant?.name ?? t('What can I help with?')),
              style: T.display.copyWith(color: p.text),
            ),
          ),
          const SizedBox(height: 8),
          Rise(
            1,
            child: Text(
              temporary ? t('This chat is gone when you leave it. It never touches the phone\'s storage.') : (assistant != null ? assistant!.system : t('Photos, files, voice, the web: it can use them all.')),
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
              style: T.sub.copyWith(color: p.text2),
            ),
          ),
          if (!temporary && assistant == null) ...[
            const SizedBox(height: 26),
            for (final (i, (icon, label, text)) in ideas.indexed)
              Rise(
                i + 2,
                child: Press(
                  onTap: () {
                    onPick(text);
                    focus.requestFocus();
                  },
                  child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: 10),
                    child: Row(
                      children: [
                        Icon(icon, size: 19, color: p.text2),
                        const SizedBox(width: 14),
                        Text(label, style: T.row.copyWith(color: p.text)),
                      ],
                    ),
                  ),
                ),
              ),
          ],
        ],
      ),
    );
  }
}

class _Reply extends StatelessWidget {
  const _Reply(this.m, {super.key, this.run, required this.last, required this.onAgain, required this.onMenu, required this.provider});
  final Msg m;
  final LiveRun? run;
  final bool last;
  final VoidCallback onAgain, onMenu;
  final String provider;

  @override
  Widget build(BuildContext context) => run == null ? _body(context) : ListenableBuilder(listenable: run!, builder: (c, _) => _body(c));

  Widget _body(BuildContext context) {
    final p = context.p;
    final live = m.live;
    final busy = m.steps.where((s) => s.state == 'running').lastOrNull;
    final thinking = live && m.text.isEmpty && m.reasoning.isNotEmpty && busy == null;
    return Padding(
      padding: const EdgeInsets.fromLTRB(gutter, 10, gutter, 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (m.reasoning.isNotEmpty && (!live || m.text.isNotEmpty || busy != null))
            QuietLine((m.thoughtMs ?? 0) < 900 ? t('Thoughts') : t('Thought for {}', took(m.thoughtMs!)), icon: LucideIcons.lightbulb, onTap: () => thoughtSheet(context, m.reasoning)),
          if (m.steps.isNotEmpty)
            QuietLine(
              busy != null ? busy.label : (m.steps.length == 1 ? m.steps.first.label : t('{} steps', m.steps.length)),
              icon: m.steps.any((s) => s.state == 'error') && m.steps.length == 1 ? LucideIcons.circleAlert : LucideIcons.listChecks,
              live: busy != null,
              onTap: () => _steps(context),
            ),
          if (thinking) QuietLine(t('Thinking'), live: true, onTap: () => thoughtSheet(context, m.reasoning)),
          if (live && m.text.isEmpty && m.reasoning.isEmpty && m.steps.isEmpty) QuietLine(t('Thinking'), live: true),
          if (m.text.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: FlowText(m.text, live: live)),
          if (m.error != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Note(m.error!, icon: LucideIcons.circleAlert, color: p.bad, action: last ? t('Try again') : null, onTap: onAgain),
            ),
          if (!live && m.text.isNotEmpty)
            Transform.translate(
              offset: Offset(Directionality.of(context) == TextDirection.rtl ? 9 : -9, 0),
              child: Row(
                children: [
                  ReplyBtn(LucideIcons.copy, () => copyText(context, m.text), tip: t('Copy')),
                  ListenableBuilder(
                    listenable: Voice.i,
                    builder: (c, _) {
                      final on = Voice.i.speaking == '${m.at.millisecondsSinceEpoch}';
                      return ReplyBtn(on ? LucideIcons.square : LucideIcons.volume2, () => on ? Voice.i.hush() : Voice.i.speak('${m.at.millisecondsSinceEpoch}', m.text), tip: t('Read aloud'), on: on);
                    },
                  ),
                  if (last) ReplyBtn(LucideIcons.rotateCw, onAgain, tip: t('Try again')),
                  ReplyBtn(LucideIcons.ellipsis, onMenu, tip: t('More')),
                  const SizedBox(width: 12),
                  if (m.model != null)
                    Expanded(
                      child: Text(
                        textAlign: TextAlign.end,
                        [prettyModel(m.model!), if (m.tookMs != null) took(m.tookMs!)].join(' · '),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: T.tiny.copyWith(color: p.text3),
                      ),
                    ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  Future<void> _steps(BuildContext context) => sheet(
    context,
    title: t('What it did'),
    (c) => ListView(
      shrinkWrap: true,
      padding: EdgeInsets.fromLTRB(gutter, 0, gutter, 20 + MediaQuery.paddingOf(c).bottom),
      children: [
        for (final (i, s) in m.steps.indexed)
          Rise(
            i,
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 9),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Square(phoneStepIcon(s.tool), size: 32, color: s.state == 'error' ? c.p.bad : null),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(s.label, style: T.row.copyWith(color: c.p.text)),
                        if (s.detail.isNotEmpty) Text(s.detail, style: T.small.copyWith(color: c.p.text3)),
                        if (s.output.isNotEmpty) ...[
                          const SizedBox(height: 8),
                          Container(
                            width: double.infinity,
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(color: c.p.code, borderRadius: BorderRadius.circular(14)),
                            child: Text(s.output, maxLines: 12, overflow: TextOverflow.ellipsis, style: T.small.copyWith(color: c.p.text2)),
                          ),
                        ],
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
      ],
    ),
  );
}

IconData phoneStepIcon(String tool) => switch (tool) {
  'web_search' => LucideIcons.search,
  'read_webpage' => LucideIcons.globe,
  'get_weather' => LucideIcons.cloudSun,
  'get_location' || 'open_maps' => LucideIcons.mapPin,
  'get_device_info' => LucideIcons.smartphone,
  'calculate' => LucideIcons.calculator,
  'read_clipboard' || 'copy_to_clipboard' => LucideIcons.clipboard,
  'open_link' => LucideIcons.externalLink,
  'start_call' => LucideIcons.phone,
  'draft_text_message' => LucideIcons.messageSquare,
  'draft_email' => LucideIcons.mail,
  'find_contact' => LucideIcons.contact,
  'set_reminder' => LucideIcons.bell,
  'add_calendar_event' => LucideIcons.calendar,
  'remember' || 'forget' => LucideIcons.brain,
  'list_computers' || 'run_on_computer' || 'read_computer_thread' => LucideIcons.monitor,
  _ => LucideIcons.wrench,
};

Future<void> exportChat(Chat c) async {
  final a = await Media.keepBytes(utf8.encode(c.export()), '${(c.title.isEmpty ? 'chat' : c.title).replaceAll(RegExp(r'[^\w\- ]+'), '').trim()}.md');
  await SharePlus.instance.share(ShareParams(files: [XFile(a.file.path, mimeType: 'text/markdown', name: a.label)], fileNameOverrides: [a.label]));
}
