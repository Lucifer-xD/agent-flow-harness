// One computer: its projects, what it's doing, its screen, its automations and what it has used.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/hub.dart';
import '../core/l10n.dart';
import '../core/relay.dart';
import '../core/store.dart';
import '../ui/badge.dart';
import '../ui/kit.dart';
import '../ui/look.dart';
import '../ui/media.dart';
import '../ui/motion.dart';
import 'compose.dart';
import 'files.dart';
import 'pick.dart';
import 'rows.dart';
import 'work.dart' show Bar;

class ComputerScreen extends StatelessWidget {
  const ComputerScreen(this.c, {super.key});
  final Computer c;

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: Listenable.merge([Hubs.i, Account.i]),
    builder: (context, _) {
      final p = context.p;
      final h = Hubs.i.of(c.id);
      final live = h != null && h.state != 'offline' && Account.i.computers.any((x) => x.id == c.id && x.online);
      final running = h == null
          ? const <J>[]
          : [
              for (final s in h.sessions)
                if (s['running'] == true) s,
            ];
      final done = h == null
          ? <J>[]
          : [
              for (final s in h.sessions)
                if (s['running'] != true && s['parentID'] == null) s,
            ];
      return AppPage(
        title: c.name,
        sub: live ? t('Online · AFH {}', h.version.isEmpty ? c.version ?? '' : h.version) : (c.lastSeen == null ? t('Offline') : t('Last online {}', ago(c.lastSeen!))),
        onRefresh: () async {
          await Account.i.refresh();
          await h?.load();
        },
        actions: [
          Ic(
            LucideIcons.ellipsis,
            color: p.text2,
            tip: t('More'),
            onTap: () => actions(context, title: c.name, [
              if (live)
                Act(t('Restart AFH there'), LucideIcons.rotateCw, () async {
                  if (!await confirm(context, t('Restart AFH on {}?', c.name), t('Threads that are running stop and can be continued.'), t('Restart'))) return;
                  try {
                    await h.pc.post('/api/restart');
                    if (context.mounted) toast(context, t('Restarting'));
                  } catch (e) {
                    if (context.mounted) toast(context, '$e', bad: true);
                  }
                }),
              Act(t('Remove from my account'), LucideIcons.unlink, () async {
                if (!await confirm(context, t('Remove {}?', c.name), t('You can link it again from AFH on that computer.'), t('Remove'), danger: true)) return;
                try {
                  await Account.i.removeComputer(c.id);
                  if (context.mounted) Navigator.pop(context);
                } catch (e) {
                  if (context.mounted) toast(context, '$e', bad: true);
                }
              }, danger: true),
            ]),
          ),
        ],
        slivers: [
          pad([
            if (!live)
              Note(t('AFH isn\'t running on it, or it has no internet. Open AFH there and it shows up by itself.'), icon: LucideIcons.cloudOff)
            else ...[
              Row(
                children: [
                  for (final (i, (icon, label, page)) in [
                    (LucideIcons.monitorPlay, t('Screen'), ScreenPeek(h)),
                    (LucideIcons.calendarClock, t('Automations'), AutomationsScreen(h)),
                    (LucideIcons.chartColumn, t('Usage'), UsageScreen(h)),
                  ].indexed) ...[
                    if (i > 0) const SizedBox(width: 10),
                    Expanded(
                      child: Panel(
                        onTap: () => go(context, page),
                        pad: const EdgeInsets.fromLTRB(14, 15, 8, 14),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Icon(icon, size: 21, color: p.text),
                            const SizedBox(height: 18),
                            Text(
                              label,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: T.label.copyWith(color: p.text),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ],
              ),
              if (running.isNotEmpty) ...[Head(t('Working now')), for (final s in running) WorkingCard(h, s)],
              Group(
                title: t('Projects'),
                trailing: Press(
                  onTap: () => pickProject(context, h, null),
                  child: Icon(LucideIcons.plus, size: 17, color: p.text2),
                ),
                children: [
                  for (final d in h.projects) Tile(baseName(d), sub: parentOf(d), subMax: 1, lead: const Square(LucideIcons.folder), arrow: true, onTap: () => go(context, ProjectScreen(h, d))),
                  if (h.projects.isEmpty) Tile(t('Add a folder'), icon: LucideIcons.folderPlus, onTap: () => pickProject(context, h, null)),
                ],
              ),
              if (done.isNotEmpty) ...[
                Head(t('Threads')),
                ThreadGroup([for (final s in done.take(12)) (h, s)]),
              ],
            ],
          ]),
        ],
      );
    },
  );
}

class ProjectScreen extends StatefulWidget {
  const ProjectScreen(this.h, this.dir, {super.key});
  final Hub h;
  final String dir;
  @override
  State<ProjectScreen> createState() => _ProjectScreenState();
}

class _ProjectScreenState extends State<ProjectScreen> {
  List<String>? _facts;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final m = asMap(await widget.h.pc.get('/api/projects/memory?directory=${Uri.encodeQueryComponent(widget.dir)}'));
      final f = m['facts'];
      if (mounted) setState(() => _facts = [for (final x in (f is List ? f : const [])) x is Map ? '${x['text'] ?? x['fact'] ?? ''}' : '$x']);
    } catch (_) {}
  }

  Future<void> _save(List<String> facts) async {
    setState(() => _facts = facts);
    try {
      await widget.h.pc.put('/api/projects/memory', {'directory': widget.dir, 'facts': facts});
    } catch (e) {
      if (mounted) toast(context, '$e', bad: true);
    }
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: widget.h,
    builder: (context, _) {
      final p = context.p;
      final list = [
        for (final s in widget.h.sessions)
          if (dirOf(s) == widget.dir && s['parentID'] == null) (widget.h, s),
      ];
      return AppPage(
        title: baseName(widget.dir),
        sub: '${widget.h.computer.name} · ${parentOf(widget.dir)}',
        bottom: 110,
        onRefresh: widget.h.load,
        actions: [
          Ic(
            LucideIcons.ellipsis,
            color: p.text2,
            tip: t('More'),
            onTap: () => actions(context, [
              Act(t('Take it off the list'), LucideIcons.folderMinus, () async {
                try {
                  await widget.h.pc.delete('/api/projects', {'path': widget.dir});
                  await widget.h.reloadSettings();
                  if (context.mounted) Navigator.pop(context);
                } catch (e) {
                  if (context.mounted) toast(context, '$e', bad: true);
                }
              }, sub: t('The folder itself stays where it is')),
            ]),
          ),
        ],
        footer: Padding(
          padding: EdgeInsets.fromLTRB(gutter, 0, gutter, 14 + MediaQuery.paddingOf(context).bottom),
          child: Btn(
            t('New thread here'),
            icon: LucideIcons.plus,
            onTap: () => compose(context, hub: widget.h, dir: widget.dir),
          ),
        ),
        slivers: [
          pad([
            Group(
              children: [Tile(t('Files'), icon: LucideIcons.folderOpen, arrow: true, onTap: () => go(context, FilesScreen(widget.h, widget.dir)))],
            ),
            if (_facts != null)
              Group(
                title: t('What it remembers here'),
                note: t('Every thread in this project reads these.'),
                children: [
                  for (final (i, f) in _facts!.indexed)
                    Tile(
                      f,
                      titleMax: 3,
                      trail: Ic(LucideIcons.x, size: 32, icon_: 15, color: p.text3, tip: t('Forget'), onTap: () => _save([..._facts!]..removeAt(i))),
                      onTap: () async {
                        final n = await askText(context, t('Edit'), value: f, lines: 3);
                        if (n != null && n.isNotEmpty) _save([..._facts!]..[i] = n);
                      },
                    ),
                  Tile(
                    t('Add something to remember'),
                    icon: LucideIcons.plus,
                    onTap: () async {
                      final n = await askText(context, t('Remember'), lines: 3, hint: t('The tests run with npm test -- --ci'));
                      if (n != null && n.isNotEmpty) _save([..._facts!, n]);
                    },
                  ),
                ],
              ),
            if (list.isNotEmpty) ...[Head(t('Threads')), ThreadGroup(list)],
          ]),
        ],
      );
    },
  );
}

// ---- the screen ----

class ScreenPeek extends StatefulWidget {
  const ScreenPeek(this.h, {super.key});
  final Hub h;
  @override
  State<ScreenPeek> createState() => _ScreenPeekState();
}

class _ScreenPeekState extends State<ScreenPeek> {
  Uint8List? _img;
  String? _error;
  bool _live = true, _gone = false, _wide = false;
  int _display = 0;
  DateTime? _at;

  @override
  void initState() {
    super.initState();
    _loop();
  }

  Future<void> _loop() async {
    while (!_gone) {
      if (_live || _img == null) await _shot();
      if (_error != null && _img == null) return;
      await Future<void>.delayed(const Duration(milliseconds: 1600));
    }
  }

  Future<void> _shot() async {
    if (!widget.h.computer.atLeast(1, 36)) {
      return setState(() => _error = t('Update AFH on {} to 1.36 to see its screen.', widget.h.computer.name));
    }
    try {
      final b = await widget.h.pc.bytes('/api/screen?display=$_display&edge=1600');
      if (!mounted) return;
      await precacheImage(MemoryImage(b), context);
      if (!mounted) return;
      setState(() {
        _img = b;
        _error = null;
        _at = DateTime.now();
      });
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  @override
  void dispose() {
    _gone = true;
    SystemChrome.setPreferredOrientations(const []);
    super.dispose();
  }

  void _turn() {
    _wide = !_wide;
    SystemChrome.setPreferredOrientations(_wide ? const [DeviceOrientation.landscapeLeft, DeviceOrientation.landscapeRight] : const [DeviceOrientation.portraitUp]);
    setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    const white = Colors.white;
    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: SystemUiOverlayStyle.light,
      child: Scaffold(
        backgroundColor: Colors.black,
        body: Stack(
          fit: StackFit.expand,
          children: [
            Positioned.fill(
              child: _img == null
                  ? Center(
                      child: _error == null
                          ? const Pulse(size: 28)
                          : Padding(
                              padding: const EdgeInsets.all(40),
                              child: Column(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  const Icon(LucideIcons.monitorX, color: Colors.white54, size: 34),
                                  const SizedBox(height: 16),
                                  Text(
                                    _error!,
                                    textAlign: TextAlign.center,
                                    style: T.sub.copyWith(color: Colors.white70),
                                  ),
                                ],
                              ),
                            ),
                    )
                  : ZoomBox(
                      child: Center(child: Image.memory(_img!, gaplessPlayback: true, fit: BoxFit.contain)),
                    ),
            ),
            PositionedDirectional(
              start: 0,
              end: 0,
              top: 0,
              child: SafeArea(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  child: Row(
                    children: [
                      Ic(LucideIcons.x, color: white, fill: Colors.white12, onTap: () => Navigator.pop(context)),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(widget.h.computer.name, style: T.h3.copyWith(color: white)),
                            if (_at != null) Text(_live ? t('Live, a picture every second or two') : t('Paused'), style: T.tiny.copyWith(color: Colors.white60)),
                          ],
                        ),
                      ),
                      Ic(
                        LucideIcons.monitor,
                        color: white,
                        fill: Colors.white12,
                        tip: t('Next display'),
                        onTap: () {
                          setState(() {
                            _display = (_display + 1) % 4;
                            _img = null;
                          });
                          _shot();
                        },
                      ),
                      const SizedBox(width: 8),
                      Ic(LucideIcons.rotateCwSquare, color: white, fill: Colors.white12, tip: t('Turn'), onTap: _turn),
                      const SizedBox(width: 8),
                      Ic(_live ? LucideIcons.pause : LucideIcons.play, color: white, fill: Colors.white12, tip: t('Pause'), onTap: () => setState(() => _live = !_live)),
                    ],
                  ),
                ),
              ),
            ),
            if (!_wide)
              Positioned(
                left: 24,
                right: 24,
                bottom: 20 + MediaQuery.paddingOf(context).bottom,
                child: Text(
                  t('Pinch to zoom. AFH on that computer shows that its screen is being viewed.'),
                  textAlign: TextAlign.center,
                  style: T.small.copyWith(color: Colors.white54),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

// ---- automations ----

String whenText(J j) {
  final at = '${j['time'] ?? '09:00'}';
  const days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  return switch ('${j['every']}') {
    'interval' => t('Every {} minutes', '${j['minutes'] ?? 30}'),
    'hourly' => t('Every hour'),
    'daily' => t('Every day at {}', at),
    'weekdays' => t('Weekdays at {}', at),
    'weekly' => t('{} at {}', t(days[((j['weekday'] as num?) ?? 0).toInt().clamp(0, 6)]), at),
    final e => e,
  };
}

class AutomationsScreen extends StatefulWidget {
  const AutomationsScreen(this.h, {super.key});
  final Hub h;
  @override
  State<AutomationsScreen> createState() => _AutomationsScreenState();
}

class _AutomationsScreenState extends State<AutomationsScreen> {
  List<J>? _jobs;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final got = await widget.h.pc.get('/api/schedules');
      if (mounted) setState(() => _jobs = asList(got is Map ? got['jobs'] : got));
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  Future<void> _edit([J? j]) async {
    final ok = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => AutomationScreen(widget.h, j), fullscreenDialog: true));
    if (ok == true) _load();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final jobs = _jobs;
    return AppPage(
      title: t('Automations'),
      sub: t('Threads {} starts by itself.', widget.h.computer.name),
      onRefresh: _load,
      actions: [Ic(LucideIcons.plus, tip: t('New automation'), onTap: _edit)],
      slivers: [
        pad([
          if (_error != null)
            Empty(LucideIcons.cloudOff, t('Couldn\'t open it'), _error!, action: t('Try again'), onTap: _load)
          else if (jobs == null)
            for (var i = 0; i < 3; i++) const Padding(padding: EdgeInsets.only(bottom: 12), child: Bone(h: 92, r: 20))
          else if (jobs.isEmpty)
            Empty(LucideIcons.calendarClock, t('Nothing runs by itself yet'), t('Have the tests run every morning, or the inbox sorted every hour.'), action: t('New automation'), onTap: _edit)
          else
            for (final j in jobs)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Panel(
                  onTap: () => _edit(j),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              '${j['name']}',
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: T.h3.copyWith(color: p.text),
                            ),
                          ),
                          Toggle(
                            j['enabled'] != false,
                            onChanged: (v) async {
                              setState(() => j['enabled'] = v);
                              try {
                                await widget.h.pc.put('/api/schedules/${j['id']}', j);
                              } catch (e) {
                                if (context.mounted) toast(context, '$e', bad: true);
                              }
                            },
                          ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Text(
                        '${j['prompt']}',
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: T.sub.copyWith(color: p.text2),
                      ),
                      const SizedBox(height: 13),
                      Row(
                        children: [
                          Expanded(
                            child: Wrap(
                              spacing: 6,
                              runSpacing: 6,
                              children: [
                                Pill(whenText(j), icon: LucideIcons.clock, dense: true),
                                Pill(baseName('${j['directory']}'), icon: LucideIcons.folder, dense: true),
                                if ('${j['lastStatus'] ?? ''}'.isNotEmpty)
                                  Pill(t('${j['lastStatus']}'[0].toUpperCase() + '${j['lastStatus']}'.substring(1)), dense: true, color: '${j['lastStatus']}' == 'failed' ? p.bad : p.good),
                              ],
                            ),
                          ),
                          Ic(
                            LucideIcons.play,
                            size: 34,
                            icon_: 15,
                            fill: p.fill,
                            tip: t('Run it now'),
                            onTap: () async {
                              try {
                                await widget.h.pc.post('/api/schedules/${j['id']}/run');
                                if (context.mounted) toast(context, t('Started'));
                              } catch (e) {
                                if (context.mounted) toast(context, '$e', bad: true);
                              }
                            },
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
        ]),
      ],
    );
  }
}

class AutomationScreen extends StatefulWidget {
  const AutomationScreen(this.h, this.job, {super.key});
  final Hub h;
  final J? job;
  @override
  State<AutomationScreen> createState() => _AutomationScreenState();
}

class _AutomationScreenState extends State<AutomationScreen> {
  late final J j = {
    'name': '',
    'prompt': '',
    'directory': widget.h.projects.firstOrNull ?? '',
    'every': 'daily',
    'minutes': 30,
    'time': '09:00',
    'weekday': 0,
    'mode': 'full',
    'model': null,
    'enabled': true,
    ...?widget.job,
  };
  late final _name = TextEditingController(text: '${j['name']}');
  late final _prompt = TextEditingController(text: '${j['prompt']}');
  bool _busy = false;
  static const _every = ['interval', 'hourly', 'daily', 'weekdays', 'weekly'];

  @override
  void dispose() {
    _name.dispose();
    _prompt.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (_prompt.text.trim().isEmpty) return toast(context, t('Say what it should do.'), bad: true);
    j['prompt'] = _prompt.text.trim();
    j['name'] = _name.text.trim().isEmpty ? _prompt.text.trim().split('\n').first : _name.text.trim();
    setState(() => _busy = true);
    try {
      widget.job == null ? await widget.h.pc.post('/api/schedules', j) : await widget.h.pc.put('/api/schedules/${j['id']}', j);
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        setState(() => _busy = false);
        toast(context, '$e', bad: true);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final every = '${j['every']}';
    final parts = '${j['time'] ?? '09:00'}'.split(':');
    return AppPage(
      title: widget.job == null ? t('New automation') : t('Automation'),
      lead: const BackBtn(icon: LucideIcons.x),
      actions: [
        Btn(t('Save'), small: true, wide: false, busy: _busy, onTap: _save),
        const SizedBox(width: 6),
      ],
      slivers: [
        pad([
          Field(_prompt, label: t('What it should do'), hint: t('Run the tests and fix what fails.'), lines: 3, maxLines: 8),
          const SizedBox(height: 16),
          Field(_name, label: t('Name'), hint: t('Morning tests')),
          Head(t('When')),
          Wrap(
            spacing: 7,
            runSpacing: 7,
            children: [
              for (final (i, l) in [t('Minutes'), t('Hourly'), t('Daily'), t('Weekdays'), t('Weekly')].indexed) Pill(l, on: every == _every[i], onTap: () => setState(() => j['every'] = _every[i])),
            ],
          ),
          const SizedBox(height: 12),
          Group(
            children: [
              if (every == 'interval')
                Tile(
                  t('Every {} minutes', '${j['minutes'] ?? 30}'),
                  icon: LucideIcons.timer,
                  trail: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Ic(LucideIcons.minus, size: 34, fill: p.fill, icon_: 16, onTap: () => setState(() => j['minutes'] = ((j['minutes'] as num? ?? 30) - 5).clamp(5, 1440))),
                      const SizedBox(width: 8),
                      Ic(LucideIcons.plus, size: 34, fill: p.fill, icon_: 16, onTap: () => setState(() => j['minutes'] = ((j['minutes'] as num? ?? 30) + 5).clamp(5, 1440))),
                    ],
                  ),
                ),
              if (every == 'weekly')
                Tile(
                  t(const ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][((j['weekday'] as num?) ?? 0).toInt()]),
                  icon: LucideIcons.calendar,
                  arrow: true,
                  onTap: () => actions(context, [
                    for (final (i, d) in const ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'].indexed)
                      Act(t(d), LucideIcons.calendar, () => setState(() => j['weekday'] = i), on: j['weekday'] == i),
                  ]),
                ),
              if (const {'daily', 'weekdays', 'weekly'}.contains(every))
                Tile(
                  t('At {}', '${j['time'] ?? '09:00'}'),
                  icon: LucideIcons.clock,
                  arrow: true,
                  onTap: () async {
                    final got = await showTimePicker(
                      context: context,
                      initialTime: TimeOfDay(hour: int.tryParse(parts.first) ?? 9, minute: int.tryParse(parts.last) ?? 0),
                    );
                    if (got != null) setState(() => j['time'] = '${'${got.hour}'.padLeft(2, '0')}:${'${got.minute}'.padLeft(2, '0')}');
                  },
                ),
              if (every == 'hourly') Tile(t('Every hour'), icon: LucideIcons.clock),
            ],
          ),
          Group(
            title: t('How'),
            children: [
              Tile(
                t('Project'),
                icon: LucideIcons.folder,
                value: '${j['directory']}'.isEmpty ? t('Choose') : baseName('${j['directory']}'),
                arrow: true,
                onTap: () async {
                  final d = await pickProject(context, widget.h, '${j['directory']}');
                  if (d != null) setState(() => j['directory'] = d);
                },
              ),
              Tile(
                t('Model'),
                icon: LucideIcons.cpu,
                value: j['model'] == null ? t('Default') : widget.h.modelName(j['model']),
                arrow: true,
                onTap: () async {
                  final got = await pickModel(context, hubModels(widget.h), current: j['model'] == null ? null : '${asMap(j['model'])['providerID']}/${asMap(j['model'])['id']}');
                  if (got != null) setState(() => j['model'] = got.ref);
                },
              ),
              Tile(
                t('What it may do'),
                icon: LucideIcons.shield,
                value: t(modeOf_('${j['mode']}').$2),
                arrow: true,
                onTap: () async {
                  final m = await pickMode(context, '${j['mode']}');
                  if (m != null) setState(() => j['mode'] = m);
                },
              ),
            ],
          ),
          if (widget.job != null) ...[
            const SizedBox(height: 24),
            Btn(
              t('Delete'),
              kind: Kind.danger,
              onTap: () async {
                if (!await confirm(context, t('Delete this automation?'), t('Threads it already started stay.'), t('Delete'), danger: true)) return;
                try {
                  await widget.h.pc.delete('/api/schedules/${j['id']}');
                  if (context.mounted) Navigator.pop(context, true);
                } catch (e) {
                  if (context.mounted) toast(context, '$e', bad: true);
                }
              },
            ),
          ],
        ]),
      ],
    );
  }
}

// ---- usage ----

class UsageScreen extends StatefulWidget {
  const UsageScreen(this.h, {super.key});
  final Hub h;
  @override
  State<UsageScreen> createState() => _UsageScreenState();
}

class _UsageScreenState extends State<UsageScreen> {
  J? _d;
  List<J>? _limits;
  String? _error;
  int _days = 30, _pick = -1;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final d = asMap(await widget.h.pc.get('/api/usage/summary?days=$_days'));
      if (mounted) setState(() => _d = d);
      final l = asMap(await widget.h.pc.get('/api/usage/limits'));
      if (mounted) setState(() => _limits = asList(l['providers']));
    } catch (e) {
      if (mounted && _d == null) setState(() => _error = '$e');
    }
  }

  num _tok(J x) => ((x['input'] as num?) ?? 0) + ((x['output'] as num?) ?? 0);

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final d = _d;
    final byDay = {for (final x in asList(d?['days'])) '${x['day']}': x};
    final now = DateTime.now();
    final days = [
      for (var i = _days - 1; i >= 0; i--)
        () {
          final at = DateTime(now.year, now.month, now.day - i);
          final k = '${at.year}-${'${at.month}'.padLeft(2, '0')}-${'${at.day}'.padLeft(2, '0')}';
          return (at, byDay[k] ?? const <String, dynamic>{});
        }(),
    ];
    final tokens = days.fold<num>(0, (n, x) => n + _tok(x.$2));
    final max = days.fold<num>(1, (n, x) => _tok(x.$2) > n ? _tok(x.$2) : n);
    final models = asList(d?['models'])..sort((a, b) => _tok(b).compareTo(_tok(a)));
    final picked = _pick >= 0 && _pick < days.length ? days[_pick] : null;
    return AppPage(
      title: t('Usage'),
      sub: widget.h.computer.name,
      onRefresh: _load,
      slivers: [
        pad([
          if (_error != null)
            Empty(LucideIcons.cloudOff, t('Couldn\'t open it'), _error!, action: t('Try again'), onTap: _load)
          else if (d == null) ...[
            const Bone(h: 220, r: 20),
            const SizedBox(height: 14),
            const Bone(h: 160, r: 20),
          ] else ...[
            Seg([t('7 days'), t('30 days'), t('90 days')], const [7, 30, 90].indexOf(_days), (i) {
              setState(() {
                _days = const [7, 30, 90][i];
                _pick = -1;
              });
              _load();
            }),
            const SizedBox(height: 14),
            Panel(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(picked == null ? t('Tokens') : '${picked.$1.day}/${picked.$1.month}', style: T.label.copyWith(color: p.text2)),
                  const SizedBox(height: 4),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      Text(count(picked == null ? tokens : _tok(picked.$2)), style: T.display.copyWith(color: p.text)),
                      const Spacer(),
                      if (((picked == null ? d['total'] : picked.$2['cost']) as num? ?? 0) > 0)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 5),
                          child: Text(money((picked == null ? d['total'] : picked.$2['cost']) as num), style: T.h2.copyWith(color: p.text2)),
                        ),
                    ],
                  ),
                  const SizedBox(height: 20),
                  SizedBox(
                    height: 120,
                    child: LayoutBuilder(
                      builder: (c, box) => GestureDetector(
                        behavior: HitTestBehavior.opaque,
                        onTapDown: (e) => setState(() => _pick = (e.localPosition.dx / box.maxWidth * days.length).floor().clamp(0, days.length - 1)),
                        onHorizontalDragUpdate: (e) {
                          final n = (e.localPosition.dx / box.maxWidth * days.length).floor().clamp(0, days.length - 1);
                          if (n != _pick) {
                            Tap.tick();
                            setState(() => _pick = n);
                          }
                        },
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.end,
                          children: [
                            for (final (i, x) in days.indexed)
                              Expanded(
                                child: Padding(
                                  padding: EdgeInsets.symmetric(horizontal: _days > 40 ? .5 : 1.5),
                                  child: TweenAnimationBuilder<double>(
                                    tween: Tween(begin: 0, end: _tok(x.$2) / max),
                                    duration: Duration(milliseconds: 500 + i * 8),
                                    curve: Curves.easeOutQuint,
                                    builder: (_, v, _) => Container(
                                      height: 3 + 117 * v,
                                      decoration: BoxDecoration(
                                        color: _tok(x.$2) == 0 ? p.fill : (_pick == i || _pick < 0 ? p.accent : p.accent.withValues(alpha: .35)),
                                        borderRadius: BorderRadius.circular(3),
                                      ),
                                    ),
                                  ),
                                ),
                              ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
            if (models.isNotEmpty) ...[
              Head(t('By model')),
              Panel(
                pad: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                child: Column(
                  children: [
                    for (final m in models.take(8))
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 9),
                        child: Column(
                          children: [
                            Row(
                              children: [
                                Logo('${m['providerID']}', model: '${m['id']}', size: 17, family: true),
                                const SizedBox(width: 11),
                                Expanded(
                                  child: Text(
                                    '${m['name']}',
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: T.sub.copyWith(color: p.text, fontWeight: FontWeight.w500),
                                  ),
                                ),
                                Text(count(_tok(m)), style: T.label.copyWith(color: p.text2)),
                                if (((m['cost'] as num?) ?? 0) > 0) ...[const SizedBox(width: 10), Text(money(m['cost'] as num), style: T.label.copyWith(color: p.text3))],
                              ],
                            ),
                            const SizedBox(height: 8),
                            Bar(_tok(m) / (_tok(models.first) == 0 ? 1 : _tok(models.first)), h: 4, color: p.accent.withValues(alpha: .8)),
                          ],
                        ),
                      ),
                  ],
                ),
              ),
            ],
            if (_limits != null) ..._limitCards(p),
          ],
        ]),
      ],
    );
  }

  List<Widget> _limitCards(Pal p) {
    final out = <Widget>[];
    for (final l in _limits!) {
      final windows = asList(l['windows']);
      if (windows.isEmpty) continue;
      out.add(
        Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: Panel(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Logo('${l['id'] ?? l['provider'] ?? ''}', name: '${l['name'] ?? ''}', size: 18),
                    const SizedBox(width: 11),
                    Expanded(
                      child: Text('${l['name'] ?? l['id']}', style: T.row.copyWith(color: p.text)),
                    ),
                  ],
                ),
                for (final w in windows) ...[
                  const SizedBox(height: 14),
                  Row(
                    children: [
                      Expanded(
                        child: Text('${w['label'] ?? w['name'] ?? ''}', style: T.small.copyWith(color: p.text2)),
                      ),
                      Text('${((w['percent'] ?? w['used'] ?? 0) as num).round()}%', style: T.label.copyWith(color: p.text)),
                    ],
                  ),
                  const SizedBox(height: 7),
                  Bar(((w['percent'] ?? w['used'] ?? 0) as num) / 100, h: 5, color: ((w['percent'] ?? w['used'] ?? 0) as num) > 85 ? p.warn : p.accent),
                ],
              ],
            ),
          ),
        ),
      );
    }
    return out.isEmpty ? const [] : [Head(t('Plan limits')), ...out];
  }
}

/// Kept on the phone: which computer and project were used last.
void rememberPlace(Hub h, String dir) {
  Settings.i.put('last.computer', h.computer.id, quiet: true);
  Settings.i.put('last.dir.${h.computer.id}', dir, quiet: true);
}
