// One reply of a thread: words as words, and the steps between them as one quiet line each.
import 'package:flutter/material.dart';
import 'package:share_plus/share_plus.dart';

import '../core/hub.dart';
import '../core/l10n.dart';
import '../core/relay.dart';
import '../core/voice.dart';
import '../ui/badge.dart';
import '../ui/convo.dart';
import '../ui/diff.dart';
import '../ui/kit.dart';
import '../ui/look.dart';
import '../ui/md.dart';
import '../ui/media.dart';
import '../ui/motion.dart';
import 'thread.dart' show openThread;

bool _running(J part) => const {'pending', 'running'}.contains('${asMap(part['state'])['status']}');
bool _failed(J part) => '${asMap(part['state'])['status']}' == 'error';

IconData stepIcon(String tool) => switch (tool) {
  'shell' || 'bash' => LucideIcons.terminal,
  'read' => LucideIcons.fileText,
  'write' => LucideIcons.filePlus,
  'edit' || 'multiedit' || 'patch' => LucideIcons.filePen,
  'glob' || 'grep' => LucideIcons.search,
  'list' || 'ls' => LucideIcons.folder,
  'todo' || 'todowrite' => LucideIcons.listTodo,
  'websearch' || 'web_search' || 'webfetch' || 'web_fetch' || 'fetch' => LucideIcons.globe,
  'subagent' || 'delegate' || 'task' => LucideIcons.users,
  'question' => LucideIcons.messageCircleQuestionMark,
  'design' => LucideIcons.palette,
  'browser' || 'chrome' => LucideIcons.globe,
  'computer' => LucideIcons.mouse,
  'threads' => LucideIcons.messagesSquare,
  'skill' => LucideIcons.sparkles,
  'memory' || 'remember' => LucideIcons.brain,
  'goal' => LucideIcons.target,
  _ => LucideIcons.wrench,
};

/// "Edited 3 files, ran 2 commands": a run of steps in a few words.
String runLabel(List<J> steps) {
  final tools = [for (final s in steps) if (s['type'] == 'tool') s];
  if (tools.isEmpty) {
    final ms = steps.fold<int>(0, (n, s) => n + ((s['took'] as num?)?.toInt() ?? 0));
    return ms > 900 ? t('Thought for {}', took(ms)) : t('Thoughts');
  }
  if (tools.length == 1) {
    final s = tools.first;
    return stepLabel('${s['name']}', asMap(asMap(s['state'])['input']));
  }
  var edited = <String>{}, read = <String>{};
  var ran = 0, searched = 0, web = 0, subs = 0, other = 0;
  for (final s in tools) {
    final input = asMap(asMap(s['state'])['input']);
    final path = '${input['path'] ?? input['file'] ?? input['filePath'] ?? s['id']}';
    switch ('${s['name']}') {
      case 'edit' || 'write' || 'multiedit' || 'patch':
        edited.add(path);
      case 'read':
        read.add(path);
      case 'shell' || 'bash':
        ran++;
      case 'glob' || 'grep' || 'list' || 'ls':
        searched++;
      case 'websearch' || 'web_search' || 'webfetch' || 'web_fetch' || 'fetch' || 'browser' || 'chrome':
        web++;
      case 'subagent' || 'delegate' || 'task':
        subs++;
      case 'todo' || 'todowrite' || 'question' || 'design' || 'goal':
        break;
      default:
        other++;
    }
  }
  String n(int k, String one, String many) => k == 1 ? t(one) : t(many, k);
  final parts = [
    if (edited.isNotEmpty) n(edited.length, 'Edited 1 file', 'Edited {} files'),
    if (ran > 0) n(ran, 'ran 1 command', 'ran {} commands'),
    if (read.isNotEmpty) n(read.length, 'read 1 file', 'read {} files'),
    if (searched > 0) n(searched, 'searched once', 'searched {} times'),
    if (web > 0) n(web, 'opened 1 page', 'opened {} pages'),
    if (subs > 0) n(subs, 'used 1 subagent', 'used {} subagents'),
    if (other > 0) n(other, '1 other step', '{} other steps'),
  ];
  if (parts.isEmpty) return t('Updated the plan');
  final s = parts.take(3).join(arabic ? '، ' : ', ');
  return s[0].toUpperCase() + s.substring(1);
}

class Turn extends StatelessWidget {
  const Turn(this.s, this.msgs, {super.key, required this.last, required this.onFork, required this.onChanges});
  final ThreadStore s;
  final List<TMsg> msgs;
  final bool last;
  final VoidCallback onFork, onChanges;

  String get _text => [
    for (final m in msgs)
      for (final x in m.parts)
        if (x['type'] == 'text') '${x['text']}'.trim(),
  ].where((x) => x.isNotEmpty).join('\n\n');

  @override
  Widget build(BuildContext context) => ListenableBuilder(listenable: Listenable.merge(msgs), builder: (c, _) => _body(c));

  Widget _body(BuildContext context) {
    final p = context.p;
    final live = last && s.running;
    final out = <Widget>[];
    var run = <J>[];
    void flush({bool end = false}) {
      if (run.isEmpty) return;
      final steps = run;
      run = [];
      out.add(_RunLine(s, steps, live: live && end));
    }

    for (final m in msgs) {
      for (final x in m.parts) {
        if (x['type'] == 'text') {
          if ('${x['text']}'.trim().isEmpty) continue;
          flush();
          out.add(
            Padding(
              padding: EdgeInsets.only(top: out.isEmpty ? 2 : 6, bottom: 4),
              child: FlowText('${x['text']}'.trim(), live: live && m.live && x['live'] != false && identical(m, msgs.last)),
            ),
          );
        } else if (x['type'] == 'reasoning') {
          if ('${x['text']}'.trim().isNotEmpty || (live && x['live'] == true)) run.add(x);
        } else if (x['type'] == 'tool') {
          run.add(x);
        }
      }
      if (m.d['error'] != null && '${m.d['error']}'.isNotEmpty) {
        flush();
        final e = m.d['error'];
        out.add(
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Note(e is Map ? '${e['message'] ?? e}' : '$e', icon: LucideIcons.circleAlert, color: p.bad),
          ),
        );
      }
    }
    flush(end: true);
    if (live && out.isEmpty) out.add(QuietLine(t('Thinking'), live: true));
    final done = msgs.last;
    final time = asMap(done.d['time']);
    final first = (asMap(msgs.first.d['time'])['created'] as num?)?.toInt(), end = ((time['completed'] ?? time['created']) as num?)?.toInt();
    final files = live ? const <J>[] : _files();
    return Padding(
      padding: const EdgeInsets.fromLTRB(gutter, 10, gutter, 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ...out,
          if (files.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 10, bottom: 4),
              child: _FilesCard(files, root: s.dir, onTap: onChanges),
            ),
          if (!live && _text.isNotEmpty)
            Transform.translate(
              offset: Offset(Directionality.of(context) == TextDirection.rtl ? 9 : -9, 0),
              child: Row(
                children: [
                  ReplyBtn(LucideIcons.copy, () => copyText(context, _text), tip: t('Copy')),
                  ListenableBuilder(
                    listenable: Voice.i,
                    builder: (c, _) {
                      final on = Voice.i.speaking == done.id;
                      return ReplyBtn(on ? LucideIcons.square : LucideIcons.volume2, () => on ? Voice.i.hush() : Voice.i.speak(done.id, _text), tip: t('Read aloud'), on: on);
                    },
                  ),
                  ReplyBtn(
                    LucideIcons.ellipsis,
                    () => actions(context, [
                      Act(t('Select text'), LucideIcons.textSelect, () => selectSheet(context, _text)),
                      Act(t('Share'), LucideIcons.share2, () => SharePlus.instance.share(ShareParams(text: _text))),
                      Act(t('Fork the thread'), LucideIcons.gitBranch, onFork),
                    ]),
                    tip: t('More'),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      textAlign: TextAlign.end,
                      [s.hub.modelName(done.d['model']), if (first != null && end != null && end > first) took(end - first)].join(' · '),
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

  /// The files this reply changed, with how much.
  List<J> _files() {
    final out = <String, J>{};
    for (final m in msgs) {
      for (final x in m.parts) {
        if (x['type'] != 'tool' || _failed(x)) continue;
        final md = asMap(asMap(x['state'])['metadata']);
        final patch = '${md['diff'] ?? ''}';
        if (patch.isEmpty) continue;
        final path = '${md['path'] ?? md['file']}';
        final f = out.putIfAbsent(path, () => {'file': path, 'additions': 0, 'deletions': 0});
        for (final l in parsePatch(patch)) {
          if (l.kind == '+') f['additions'] = (f['additions'] as int) + 1;
          if (l.kind == '-') f['deletions'] = (f['deletions'] as int) + 1;
        }
      }
    }
    return out.values.toList();
  }
}

class _FilesCard extends StatelessWidget {
  const _FilesCard(this.files, {required this.root, required this.onTap});
  final List<J> files;
  final String root;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final p = context.p;
    return Panel(
      onTap: onTap,
      pad: const EdgeInsets.fromLTRB(14, 6, 14, 6),
      child: Column(
        children: [
          for (final f in files.take(4))
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 7),
              child: Row(
                children: [
                  Icon(fileIcon('${f['file']}'), size: 16, color: fileColor('${f['file']}', p) ?? p.text3),
                  const SizedBox(width: 11),
                  Expanded(
                    child: Text(shortPath('${f['file']}', root), maxLines: 1, overflow: TextOverflow.ellipsis, style: T.sub.copyWith(color: p.text, fontWeight: FontWeight.w500)),
                  ),
                  const SizedBox(width: 10),
                  Plus(f['additions'] as int, f['deletions'] as int),
                ],
              ),
            ),
          if (files.length > 4)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Row(children: [Text(t('and {} more', files.length - 4), style: T.small.copyWith(color: p.text3))]),
            ),
        ],
      ),
    );
  }
}

/// A run of steps between two pieces of text.
class _RunLine extends StatelessWidget {
  const _RunLine(this.s, this.steps, {required this.live});
  final ThreadStore s;
  final List<J> steps;
  final bool live;

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final lastOne = steps.last;
    final busy = live && (lastOne['type'] == 'tool' ? _running(lastOne) : lastOne['live'] == true);
    final label = busy
        ? (lastOne['type'] == 'tool' ? stepLabel('${lastOne['name']}', asMap(asMap(lastOne['state'])['input']), live: true, root: s.dir) : t('Thinking'))
        : (live ? t('Thinking') : runLabel(steps));
    final tools = steps.where((x) => x['type'] == 'tool').toList();
    final out = busy && lastOne['type'] == 'tool' && '${lastOne['name']}' == 'shell' ? _output(lastOne) : '';
    final bad = !live && tools.isNotEmpty && tools.every(_failed);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        QuietLine(
          label,
          icon: tools.isEmpty ? LucideIcons.lightbulb : (tools.length == 1 ? stepIcon('${tools.first['name']}') : LucideIcons.listChecks),
          live: live,
          bad: bad,
          onTap: () => stepsSheet(context, s, steps),
          trail: live && tools.length > 1 ? Text('${tools.length}', style: T.tiny.copyWith(color: p.text3)) : null,
        ),
        Fold(
          open: out.isNotEmpty,
          child: out.isEmpty
              ? const SizedBox()
              : Container(
                  margin: const EdgeInsets.only(top: 4, bottom: 6),
                  width: double.infinity,
                  height: 96,
                  decoration: BoxDecoration(color: p.code, borderRadius: BorderRadius.circular(14), border: Border.all(color: p.line)),
                  child: SingleChildScrollView(
                    reverse: true,
                    padding: const EdgeInsets.all(12),
                    child: SizedBox(
                      width: double.infinity,
                      child: Text(out, textDirection: TextDirection.ltr, style: T.code.copyWith(color: p.text2, fontSize: 11.5)),
                    ),
                  ),
                ),
        ),
      ],
    );
  }
}

String _output(J part) {
  final st = asMap(part['state']);
  final text = [for (final c in asList(st['content'])) if (c['type'] == 'text') '${c['text']}'].join('\n').trim();
  final err = asMap(st['error'])['message'] ?? (st['error'] is String ? st['error'] : null);
  return [if (err != null) '$err', if (text.isNotEmpty) text].join('\n');
}

/// Every step of a run, each opening to what it did.
Future<void> stepsSheet(BuildContext context, ThreadStore s, List<J> steps) => sheet(
  context,
  full: steps.length > 14,
  title: steps.length == 1 && steps.first['type'] == 'reasoning' ? t('Thinking') : t('What it did'),
  (c) => ListenableBuilder(
    listenable: Listenable.merge([s, ...s.msgs.where((m) => m.live)]),
    builder: (c, _) => ListView.builder(
      shrinkWrap: steps.length <= 14,
      padding: EdgeInsets.fromLTRB(gutter, 0, gutter, 20 + MediaQuery.paddingOf(c).bottom),
      itemCount: steps.length,
      itemBuilder: (c, i) => _Step(s, steps[i], first: i == 0, last: i == steps.length - 1, open: steps.length == 1),
    ),
  ),
);

class _Step extends StatefulWidget {
  const _Step(this.s, this.x, {required this.first, required this.last, required this.open});
  final ThreadStore s;
  final J x;
  final bool first, last, open;
  @override
  State<_Step> createState() => _StepState();
}

class _StepState extends State<_Step> {
  late bool _open = widget.open;
  J get x => widget.x;

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final tool = x['type'] == 'tool';
    final st = asMap(x['state']);
    final md = asMap(st['metadata']);
    final ms = (md['duration_ms'] as num?)?.toInt() ?? (x['took'] as num?)?.toInt();
    final label = tool ? stepLabel('${x['name']}', asMap(st['input']), live: _running(x), root: widget.s.dir) : t('Thought');
    return Stack(
      children: [
        if (!widget.last)
          PositionedDirectional(
            start: 16,
            top: 42,
            bottom: 0,
            child: Container(width: 1.5, color: p.line),
          ),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Square(tool ? stepIcon('${x['name']}') : LucideIcons.lightbulb, size: 34, color: _failed(x) ? p.bad : null, child: tool && _running(x) ? const Pulse(size: 14) : null),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Press(
                    onTap: () => setState(() => _open = !_open),
                    scale: .985,
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 15),
                      child: Row(
                        children: [
                          Expanded(
                            child: Text(label, maxLines: _open ? 4 : 2, overflow: TextOverflow.ellipsis, style: T.row.copyWith(color: _failed(x) ? p.bad : p.text)),
                          ),
                          if (ms != null && ms > 900) ...[const SizedBox(width: 10), Text(took(ms), style: T.tiny.copyWith(color: p.text3))],
                          const SizedBox(width: 6),
                          AnimatedRotation(turns: _open ? .5 : 0, duration: med, child: Icon(LucideIcons.chevronDown, size: 15, color: p.text3)),
                        ],
                      ),
                    ),
                  ),
                  Fold(
                    open: _open,
                    child: Padding(
                      padding: const EdgeInsets.only(bottom: 14),
                      child: _open ? _detail(p, tool, st, md) : const SizedBox(),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _detail(Pal p, bool tool, J st, J md) {
    if (!tool) return Md('${x['text']}', style: T.sub.copyWith(color: p.text2, height: 1.55));
    final input = asMap(st['input']);
    final name = '${x['name']}';
    final patch = '${md['diff'] ?? ''}';
    final out = _output(x);
    final images = [for (final c in asList(st['content'])) if (c['type'] == 'image' && '${c['data'] ?? c['uri'] ?? ''}'.isNotEmpty) c];
    Widget box(Widget child) => Container(
      width: double.infinity,
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(color: p.code, borderRadius: BorderRadius.circular(15), border: Border.all(color: p.line)),
      child: child,
    );
    final child = asList(widget.s.children).where((c) => '${c['id']}' == '${md['sessionID'] ?? md['child'] ?? md['sessionId']}').firstOrNull;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (name == 'shell' && '${input['command'] ?? ''}'.isNotEmpty) ...[CodeBox('${input['command']}', lang: 'bash', head: false), const SizedBox(height: 8)],
        if (patch.isNotEmpty) box(DiffView(patch, lang: langOf('${md['file'] ?? md['path'] ?? ''}'))),
        for (final img in images) ...[_img(img), const SizedBox(height: 8)],
        if (patch.isEmpty && out.isNotEmpty)
          box(
            ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 320),
              child: SingleChildScrollView(
                reverse: _running(x),
                padding: const EdgeInsets.all(12),
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: SelectableText(
                    out.length > 12000 ? '…${out.substring(out.length - 12000)}' : out,
                    textDirection: TextDirection.ltr,
                    style: T.code.copyWith(color: p.text2, fontSize: 12),
                  ),
                ),
              ),
            ),
          ),
        if (patch.isEmpty && out.isEmpty && images.isEmpty && name != 'shell') Text(_running(x) ? t('Still running…') : t('Nothing came back.'), style: T.small.copyWith(color: p.text3)),
        if (child != null) ...[
          const SizedBox(height: 8),
          Btn(
            t('Open its thread'),
            small: true,
            kind: Kind.soft,
            icon: LucideIcons.arrowUpRight,
            onTap: () {
              Navigator.pop(context);
              openThread(context, widget.s.hub, '${child['id']}');
            },
          ),
        ],
      ],
    );
  }

  Widget _img(J c) {
    final uri = '${c['uri'] ?? c['data']}';
    final shot = Shot.remote({'uri': uri.startsWith('data:') || uri.startsWith('file:') ? uri : 'data:${c['mime'] ?? 'image/png'};base64,$uri', 'name': 'picture.png'}, widget.s.pc);
    if (shot.image == null) return const SizedBox();
    return Press(
      onTap: () => viewImages(context, [shot.image!], 0),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(15),
        child: Image(image: shot.image!, errorBuilder: (_, _, _) => const SizedBox()),
      ),
    );
  }
}

/// Messages that aren't a reply: yours, a command you ran, a summary.
class OtherMsg extends StatelessWidget {
  const OtherMsg(this.s, this.m, {super.key, required this.onLong});
  final ThreadStore s;
  final TMsg m;
  final VoidCallback onLong;

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    switch (m.type) {
      case 'user':
        final waiting = m.d['waiting'] == true && s.running;
        return Mine(
          '${m.d['text'] ?? ''}',
          shots: [for (final f in asList(m.d['files'])) Shot.remote(f, s.pc)],
          onLong: onLong,
          note: waiting ? t('It reads this at its next step') : null,
        );
      case 'shell':
        final code = m.d['exitCode'];
        return Padding(
          padding: const EdgeInsets.fromLTRB(gutter, 16, gutter, 4),
          child: CodeBox('\$ ${m.d['command']}\n${'${m.d['output'] ?? ''}'.trimRight()}${code == 0 || code == null ? '' : '\n[exit $code]'}', max: 320, lang: 'output'),
        );
      case 'compaction':
        return Padding(
          padding: const EdgeInsets.fromLTRB(gutter, 18, gutter, 6),
          child: QuietLine(t('Earlier messages were summed up'), icon: LucideIcons.foldVertical, onTap: () => thoughtSheet(context, '${m.d['text']}', title: t('Summary'))),
        );
    }
    final text = '${m.d['text'] ?? ''}'.trim();
    final meta = asMap(m.d['metadata']);
    final (icon, head) = switch ('${meta['notice'] ?? (text.startsWith('[Goal autopilot') ? 'goal' : '')}') {
      'goal' => (LucideIcons.target, t('Kept going toward the goal')),
      'todo' => (LucideIcons.listChecks, t('Checked what is left on its list')),
      'hook' => (LucideIcons.webhook, t('A check failed, so it went on')),
      _ => (LucideIcons.info, '${meta['label'] ?? text.split('\n').first}'),
    };
    return text.isEmpty
        ? const SizedBox()
        : Padding(
            padding: const EdgeInsets.fromLTRB(gutter, 12, gutter, 4),
            child: text.length < 140 && !text.contains('\n')
                ? Text(text, style: T.small.copyWith(color: p.text3))
                : QuietLine(
                    head,
                    icon: icon,
                    onTap: () => thoughtSheet(context, text, title: t('Note')),
                  ),
          );
  }
}

/// Kept so a list can show a thread's question without importing the whole screen.
Widget modelLogo(Hub h, J s, {double size = 16}) {
  final m = asMap(s['model']);
  return Logo('${m['providerID'] ?? ''}', name: h.providerNames['${m['providerID']}'] ?? '', model: '${m['id'] ?? ''}', size: size, family: true);
}
