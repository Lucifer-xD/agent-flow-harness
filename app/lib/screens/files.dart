// A project's files on a computer: look through them, read them, share them.
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:share_plus/share_plus.dart';

import '../core/hub.dart';
import '../core/l10n.dart';
import '../core/relay.dart';
import '../core/store.dart';
import '../ui/kit.dart';
import '../ui/look.dart';
import '../ui/md.dart';
import '../ui/media.dart';
import '../ui/motion.dart';

class FilesScreen extends StatefulWidget {
  const FilesScreen(this.hub, this.root, {super.key, this.path});
  final Hub hub;
  final String root;
  final String? path;
  @override
  State<FilesScreen> createState() => _FilesScreenState();
}

class _FilesScreenState extends State<FilesScreen> {
  List<J>? _entries;
  List<String> _found = const [];
  String? _error;
  final _q = TextEditingController();
  int _n = 0;

  String get _path => widget.path ?? widget.root;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _q.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    if (!widget.hub.computer.atLeast(1, 36)) {
      return setState(() => _error = t('Update AFH on {} to 1.36 to look through its files.', widget.hub.computer.name));
    }
    try {
      final got = asMap(await widget.hub.pc.get('/api/files/list?path=${Uri.encodeQueryComponent(_path)}'));
      if (mounted) {
        setState(() {
          _entries = asList(got['entries']);
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  Future<void> _search(String q) async {
    final n = ++_n;
    if (q.trim().isEmpty) return setState(() => _found = const []);
    await Future<void>.delayed(const Duration(milliseconds: 220));
    if (n != _n) return;
    try {
      final got = asMap(await widget.hub.pc.get('/api/files/search?directory=${Uri.encodeQueryComponent(_path)}&q=${Uri.encodeQueryComponent(q.trim())}'));
      if (n == _n && mounted) setState(() => _found = [for (final f in (got['files'] as List? ?? const [])) '$f']);
    } catch (_) {}
  }

  static const _noise = {'.git', 'node_modules', '__pycache__', '.venv', '.afh', '.DS_Store'};

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final searching = _q.text.trim().isNotEmpty;
    final list = [for (final e in _entries ?? const <J>[]) if (!_noise.contains(e['name'])) e];
    return AppPage(
      title: baseName(_path),
      sub: widget.path == null ? widget.hub.computer.name : shortPath(_path, widget.root),
      onRefresh: _load,
      slivers: [
        pad(rise: false, [
          if (_error == null) ...[Field(_q, hint: t('Find a file'), icon: LucideIcons.search, onChanged: _search), const SizedBox(height: 14)],
          if (_error != null)
            Empty(LucideIcons.folderX, t('Couldn\'t open it'), _error!, action: t('Try again'), onTap: _load)
          else if (searching)
            Group(
              children: [
                if (_found.isEmpty) Tile(t('Nothing found'), icon: LucideIcons.searchX),
                for (final f in _found)
                  Tile(
                    baseName(f),
                    sub: f,
                    subMax: 1,
                    lead: Square(fileIcon(f), color: fileColor(f, p), size: 34),
                    onTap: () => go(context, FileScreen(widget.hub, '$_path/$f', root: widget.root)),
                  ),
              ],
            )
          else if (_entries == null)
            for (var i = 0; i < 6; i++) const Padding(padding: EdgeInsets.only(bottom: 10), child: Bone(h: 52, r: 16))
          else if (list.isEmpty)
            Empty(LucideIcons.folderOpen, t('An empty folder'), t('Nothing is in here yet.'))
          else
            Group(
              children: [
                for (final e in list)
                  Tile(
                    '${e['name']}',
                    sub: e['dir'] == true ? null : '${bytesText((e['size'] as num?)?.toInt() ?? 0)} · ${ago(DateTime.fromMillisecondsSinceEpoch((e['modified'] as num?)?.toInt() ?? 0))}',
                    lead: Square(e['dir'] == true ? LucideIcons.folder : fileIcon('${e['name']}'), color: e['dir'] == true ? p.accent : fileColor('${e['name']}', p), size: 34),
                    arrow: e['dir'] == true,
                    onTap: () => go(context, e['dir'] == true ? FilesScreen(widget.hub, widget.root, path: '${e['path']}') : FileScreen(widget.hub, '${e['path']}', root: widget.root)),
                  ),
              ],
            ),
        ]),
      ],
    );
  }
}

class FileScreen extends StatefulWidget {
  const FileScreen(this.hub, this.path, {super.key, this.root});
  final Hub hub;
  final String path;
  final String? root;
  @override
  State<FileScreen> createState() => _FileScreenState();
}

class _FileScreenState extends State<FileScreen> {
  String? _text, _error;
  bool _binary = false, _plain = false;
  int _size = 0;

  bool get _image => const {'png', 'jpg', 'jpeg', 'gif', 'webp'}.contains(Media.ext(widget.path));
  bool get _md => const {'md', 'markdown'}.contains(Media.ext(widget.path));

  @override
  void initState() {
    super.initState();
    if (!_image) _load();
  }

  Future<void> _load() async {
    try {
      final got = asMap(await widget.hub.pc.get('/api/files/read?path=${Uri.encodeQueryComponent(widget.path)}'));
      if (!mounted) return;
      setState(() {
        if (got['exists'] == false) _error = t('That file isn\'t there any more.');
        _binary = got['binary'] == true;
        _text = '${got['content'] ?? ''}';
        _size = (got['size'] as num?)?.toInt() ?? 0;
      });
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  Future<void> _share() async {
    try {
      final f = File('${Directory.systemTemp.path}/${baseName(widget.path)}');
      await f.writeAsBytes(_image ? await widget.hub.pc.bytes('/api/image?path=${Uri.encodeQueryComponent(widget.path)}') : (_text ?? '').codeUnits.every((c) => c < 128) ? (_text ?? '').codeUnits : await _utf8());
      await SharePlus.instance.share(ShareParams(files: [XFile(f.path)]));
    } catch (e) {
      if (mounted) toast(context, '$e', bad: true);
    }
  }

  Future<List<int>> _utf8() async {
    final f = File('${Directory.systemTemp.path}/share-${newId()}');
    await f.writeAsString(_text ?? '');
    return f.readAsBytes();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final lang = langOf(widget.path);
    final lines = (_text ?? '').trimRight().split('\n');
    return AppPage(
      title: baseName(widget.path),
      sub: [shortPath(widget.path, widget.root), if (_size > 0) bytesText(_size)].join(' · '),
      actions: [
        if (_md && _text != null) Ic(_plain ? LucideIcons.bookOpen : LucideIcons.code, color: p.text2, tip: t('Show as text'), onTap: () => setState(() => _plain = !_plain)),
        if (_text != null && !_binary) Ic(LucideIcons.copy, color: p.text2, tip: t('Copy'), onTap: () => copyText(context, _text!)),
        if ((_text != null && !_binary) || _image) Ic(LucideIcons.share2, color: p.text2, tip: t('Share'), onTap: _share),
      ],
      slivers: [
        if (_image)
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: gutter),
              child: Press(
                onTap: () => viewImages(context, [NetworkImage(widget.hub.pc.imageUrl(widget.path), headers: widget.hub.pc.headers)], 0),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(20),
                  child: Image.network(
                    widget.hub.pc.imageUrl(widget.path),
                    headers: widget.hub.pc.headers,
                    errorBuilder: (_, _, _) => Empty(LucideIcons.imageOff, t('Couldn\'t open it'), ''),
                    loadingBuilder: (_, c, l) => l == null ? c : const Bone(h: 240, r: 20),
                  ),
                ),
              ),
            ),
          )
        else if (_error != null)
          SliverToBoxAdapter(child: Empty(LucideIcons.fileX, t('Couldn\'t open it'), _error!, action: t('Try again'), onTap: _load))
        else if (_text == null)
          pad([for (var i = 0; i < 10; i++) Padding(padding: const EdgeInsets.only(bottom: 10), child: Bone(w: 120 + 37.0 * (i % 5)))])
        else if (_binary)
          SliverToBoxAdapter(child: Empty(LucideIcons.binary, t('Not a text file'), t('It can\'t be shown here.')))
        else if (_md && !_plain)
          pad([Md(_text!)])
        else
          SliverToBoxAdapter(
            child: Directionality(
              textDirection: TextDirection.ltr,
              child: Container(
                decoration: BoxDecoration(
                  color: p.code,
                  border: Border.symmetric(horizontal: BorderSide(color: p.line)),
                ),
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  padding: const EdgeInsets.symmetric(vertical: 14),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 14),
                        child: Text(
                          [for (var i = 1; i <= lines.length && i <= 4000; i++) '$i'].join('\n'),
                          textAlign: TextAlign.right,
                          style: T.code.copyWith(color: p.text3, fontSize: 12),
                        ),
                      ),
                      Padding(
                        padding: const EdgeInsets.only(right: 20),
                        child: SelectableText.rich(
                          TextSpan(children: paint(lines.take(4000).join('\n'), lang, p)),
                          style: T.code.copyWith(color: p.text, fontSize: 12),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
      ],
    );
  }
}
