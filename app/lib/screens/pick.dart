// Choosing things: a model (the phone's or a computer's), its effort, a project, how much an agent may do.
import 'package:flutter/material.dart';

import '../core/ai.dart';
import '../core/hub.dart';
import '../core/l10n.dart';
import '../core/relay.dart';
import '../core/store.dart';
import '../ui/badge.dart';
import '../ui/kit.dart';
import '../ui/look.dart';
import '../ui/motion.dart';
import 'providers.dart';

/// A model that can be picked, wherever it runs.
class MRow {
  MRow({required this.pid, required this.pname, required this.id, required this.name, this.sub = '', this.efforts = const [], this.images = true, this.raw});
  final String pid, pname, id, name, sub;
  final List<String> efforts;
  final bool images;
  final J? raw;
  String get key => '$pid/$id';
}

List<MRow> phoneModels() => [
  for (final p in providers.where((p) => p.ready))
    for (final m in p.models) MRow(pid: p.id, pname: p.name, id: m, name: prettyModel(m), sub: m, efforts: effortsFor(p, m)),
];

List<MRow> hubModels(Hub h) => [
  for (final m in h.usable)
    MRow(
      pid: '${m['providerID']}',
      pname: h.providerNames['${m['providerID']}'] ?? '${m['providerID']}',
      id: '${m['id']}',
      name: '${m['name'] ?? m['id']}',
      sub: [if (m['context'] is num) t('{} context', count(m['context'] as num)), if (m['reasoning'] == true) t('thinks')].join(' · '),
      efforts: [for (final v in (m['variants'] as List? ?? const [])) if ('$v' != 'default') '$v'],
      images: (m['input'] as List?)?.contains('image') ?? true,
      raw: m,
    ),
];

String effortName(String? e) => switch (e) {
  null || '' || 'default' => t('Default'),
  'xhigh' => t('Extra high'),
  _ => t(e[0].toUpperCase() + e.substring(1)),
};

class Picked {
  Picked(this.row, this.effort);
  final MRow row;
  final String? effort;
  J get ref => {'providerID': row.pid, 'id': row.id, 'variant': ?effort};
}

Future<Picked?> pickModel(BuildContext context, List<MRow> rows, {String? current, String? effort, bool phone = false, String? title}) =>
    sheet<Picked>(context, full: true, title: title ?? t('Model'), (c) => _Models(rows, current, effort, phone));

class _Models extends StatefulWidget {
  const _Models(this.rows, this.current, this.effort, this.phone);
  final List<MRow> rows;
  final String? current, effort;
  final bool phone;
  @override
  State<_Models> createState() => _ModelsState();
}

class _ModelsState extends State<_Models> {
  final _q = TextEditingController();
  late final MRow? _on = widget.rows.where((r) => r.key == widget.current).firstOrNull;
  late String? _effort = widget.effort;
  String? _only; // one provider's models

  @override
  void dispose() {
    _q.dispose();
    super.dispose();
  }

  List<String> get _favs => Settings.i.strings('favs');

  void _star(MRow r) {
    final f = [..._favs];
    f.contains(r.key) ? f.remove(r.key) : f.add(r.key);
    Settings.i.put('favs', f);
    Tap.light();
    setState(() {});
  }

  void _pick(MRow r) {
    final recent = [r.key, ...Settings.i.strings('recents').where((k) => k != r.key)].take(5).toList();
    Settings.i.put('recents', recent, quiet: true);
    final fits = r.efforts.contains(_effort) ? _effort : null;
    Navigator.pop(context, Picked(r, fits));
  }

  Widget _row(MRow r, {bool showProvider = false}) {
    final p = context.p;
    final on = r.key == _on?.key;
    return Press(
      onTap: () => _pick(r),
      onLong: () => _star(r),
      scale: .985,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: gutter, vertical: 9),
        child: Row(
          children: [
            LogoBox(r.pid, name: r.pname, model: r.id, size: 36),
            const SizedBox(width: 13),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    r.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: T.row.copyWith(color: on ? p.accent : p.text),
                  ),
                  if (showProvider || r.sub.isNotEmpty)
                    Text(
                      showProvider ? r.pname : r.sub,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: T.small.copyWith(color: p.text3),
                    ),
                ],
              ),
            ),
            if (r.efforts.isNotEmpty) Padding(padding: const EdgeInsetsDirectional.only(start: 8), child: Icon(LucideIcons.gauge, size: 15, color: p.text3)),
            Ic(_favs.contains(r.key) ? LucideIcons.bookmarkCheck : LucideIcons.bookmark, size: 36, icon_: 16, color: _favs.contains(r.key) ? p.accent : p.text3, onTap: () => _star(r), tip: t('Favorite')),
            SizedBox(width: 18, child: on ? Icon(LucideIcons.check, size: 18, color: p.accent) : null),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final q = _q.text.trim().toLowerCase();
    var rows = widget.rows;
    if (q.isNotEmpty) rows = [for (final r in rows) if (q.split(' ').every((w) => '${r.name} ${r.id} ${r.pname}'.toLowerCase().contains(w))) r];
    if (_only != null) rows = [for (final r in rows) if (r.pid == _only) r];
    final pids = <String, String>{for (final r in widget.rows) r.pid: r.pname};
    final favs = [for (final k in _favs) ...widget.rows.where((r) => r.key == k)];
    final recents = [for (final k in Settings.i.strings('recents')) ...widget.rows.where((r) => r.key == k && !_favs.contains(k))].take(3).toList();
    final plain = q.isEmpty && _only == null;
    final items = <Widget>[
      if (plain && favs.isNotEmpty) ...[_h(t('Favorites')), for (final r in favs) _row(r, showProvider: true)],
      if (plain && recents.isNotEmpty) ...[_h(t('Recent')), for (final r in recents) _row(r, showProvider: true)],
    ];
    for (final e in pids.entries) {
      final mine = [for (final r in rows) if (r.pid == e.key) r];
      if (mine.isEmpty) continue;
      items.add(_h(e.value, logo: e.key));
      for (final r in mine) {
        items.add(_row(r));
      }
    }
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(gutter, 0, gutter, 10),
          child: Field(_q, hint: t('Search models'), icon: LucideIcons.search, onChanged: (_) => setState(() {})),
        ),
        if (pids.length > 1)
          SizedBox(
            height: 36,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: gutter),
              children: [
                Pill(t('All'), on: _only == null, onTap: () => setState(() => _only = null)),
                for (final e in pids.entries) ...[
                  const SizedBox(width: 7),
                  Pill(
                    e.value,
                    lead: Logo(e.key, name: e.value, size: 15, color: _only == e.key ? p.onInv : null),
                    on: _only == e.key,
                    onTap: () => setState(() => _only = _only == e.key ? null : e.key),
                  ),
                ],
              ],
            ),
          ),
        Fold(
          open: _on != null && _on.efforts.isNotEmpty && q.isEmpty,
          child: _on == null || _on.efforts.isEmpty
              ? const SizedBox()
              : Padding(
                  padding: const EdgeInsets.fromLTRB(gutter, 12, gutter, 2),
                  child: Panel(
                    color: p.fill,
                    border: Colors.transparent,
                    pad: const EdgeInsets.fromLTRB(14, 11, 14, 13),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(t('Effort for {}', _on.name), style: T.label.copyWith(color: p.text2)),
                        const SizedBox(height: 9),
                        Wrap(
                          spacing: 6,
                          runSpacing: 6,
                          children: [
                            for (final e in [null, ..._on.efforts])
                              Pill(
                                effortName(e),
                                on: _effort == e,
                                dense: false,
                                onTap: () {
                                  setState(() => _effort = e);
                                  Navigator.pop(context, Picked(_on, e));
                                },
                              ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
        ),
        Expanded(
          child: items.isEmpty
              ? SingleChildScrollView(
                  child: widget.rows.isEmpty
                      ? Empty(
                          LucideIcons.keyRound,
                          t('No models yet'),
                          widget.phone ? t('Sign in to a provider or paste its key, and its models show up here.') : t('Add a provider in AFH on that computer.'),
                          action: widget.phone ? t('Add a provider') : null,
                          onTap: () => go(context, const ProvidersScreen()).then((_) => context.mounted ? Navigator.pop(context) : null),
                        )
                      : Empty(LucideIcons.searchX, t('Nothing found'), t('No model matches "{}".', _q.text.trim())),
                )
              : ListView.builder(
                  padding: EdgeInsets.only(top: 4, bottom: 20 + MediaQuery.paddingOf(context).bottom),
                  itemCount: items.length + (widget.phone ? 1 : 0),
                  itemBuilder: (c, i) => i < items.length
                      ? items[i]
                      : Padding(
                          padding: const EdgeInsets.fromLTRB(gutter, 16, gutter, 0),
                          child: Btn(t('Add a provider'), icon: LucideIcons.plus, kind: Kind.soft, onTap: () => go(context, const ProvidersScreen())),
                        ),
                ),
        ),
      ],
    );
  }

  Widget _h(String s, {String? logo}) => Padding(
    padding: const EdgeInsets.fromLTRB(gutter, 18, gutter, 5),
    child: Text(s, style: T.label.copyWith(color: context.p.text3)),
  );
}

// ---- how much the agent may do ----

const modes = <String, (IconData, String, String)>{
  'ask': (LucideIcons.shield, 'Ask first', 'You approve file edits and commands'),
  'full': (LucideIcons.zap, 'Full access', 'Edits files and runs commands freely'),
  'readonly': (LucideIcons.eye, 'Read only', 'Reads and searches, never edits or runs'),
};

(IconData, String, String) modeOf_(String m) => modes[m] ?? modes['ask']!;

Future<String?> pickMode(BuildContext context, String current) async {
  String? got;
  await actions(context, title: t('What it may do'), [
    for (final e in modes.entries) Act(t(e.value.$2), e.value.$1, () => got = e.key, sub: t(e.value.$3), on: e.key == current),
  ]);
  return got;
}

Future<String?> pickAgent(BuildContext context, Hub h, String? current) async {
  String? got;
  await actions(context, title: t('Agent'), [
    for (final a in h.agents)
      if (a['hidden'] != true && a['mode'] != 'subagent')
        Act(
          '${a['name'] ?? a['id']}'.replaceFirstMapped(RegExp('^.'), (m) => m[0]!.toUpperCase()),
          switch ('${a['id']}') { 'plan' => LucideIcons.map, 'delegate' => LucideIcons.network, 'redteam' => LucideIcons.shieldAlert, 'ask' => LucideIcons.messageCircleQuestionMark, _ => LucideIcons.hammer },
          () => got = '${a['id']}',
          sub: '${a['description'] ?? ''}',
          on: a['id'] == current,
        ),
  ]);
  return got;
}

/// A project on a computer. Null: nothing picked.
Future<String?> pickProject(BuildContext context, Hub h, String? current) => sheet<String>(
  context,
  title: t('Project on {}', h.computer.name),
  (c) => ListenableBuilder(
    listenable: h,
    builder: (c, _) => ListView(
      shrinkWrap: true,
      padding: EdgeInsets.only(bottom: 14 + MediaQuery.paddingOf(c).bottom),
      children: [
        for (final d in h.projects)
          Tile(
            baseName(d),
            sub: parentOf(d),
            subMax: 1,
            lead: Square(LucideIcons.folder, color: d == current ? c.p.accent : null),
            trail: d == current ? Icon(LucideIcons.check, size: 18, color: c.p.accent) : null,
            onTap: () => Navigator.pop(c, d),
          ),
        if (h.projects.isEmpty) Empty(LucideIcons.folder, t('No projects yet'), t('Open a folder in AFH on {}, or add one by its path.', h.computer.name)),
        Tile(
          t('Add a folder by its path'),
          lead: const Square(LucideIcons.folderPlus),
          onTap: () async {
            final path = await askText(c, t('Folder on {}', h.computer.name), hint: r'C:\Projects\shop', action: t('Add'));
            if (path == null || path.isEmpty) return;
            try {
              await h.pc.post('/api/projects', {'path': path});
              await h.reloadSettings();
              if (c.mounted && h.projects.isNotEmpty) Navigator.pop(c, h.projects.first);
            } catch (e) {
              if (c.mounted) toast(c, '$e', bad: true);
            }
          },
        ),
      ],
    ),
  ),
);

/// The folder a project is in, without giving the whole path away.
String parentOf(String d) {
  final parts = d.split(RegExp(r'[\\/]')).where((s) => s.isNotEmpty).toList();
  if (parts.length < 2) return d;
  final up = parts.sublist(0, parts.length - 1);
  return up.length > 2 ? '…/${up.sublist(up.length - 2).join('/')}' : up.join('/');
}

/// A computer that's online. Skips the question when there's only one.
Future<Hub?> pickComputer(BuildContext context, {String? current}) async {
  final list = Hubs.i.online.toList();
  if (list.length == 1) return list.first;
  Hub? got;
  await actions(context, title: t('Computer'), [
    for (final h in list) Act(h.computer.name, LucideIcons.monitor, () => got = h, sub: t('{} projects', h.projects.length), on: h.computer.id == current),
  ]);
  return got;
}
