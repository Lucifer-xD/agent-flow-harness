// What changed in a file, line by line.
import 'package:flutter/material.dart';

import '../core/l10n.dart';
import '../core/relay.dart';
import 'kit.dart';
import 'look.dart';
import 'md.dart';
import 'media.dart';
import 'motion.dart';

class DiffLine {
  DiffLine(this.kind, this.text, this.a, this.b);
  final String kind; // ' ', '+', '-', '@'
  final String text;
  final int? a, b;
}

List<DiffLine> parsePatch(String patch) {
  final out = <DiffLine>[];
  var a = 0, b = 0;
  for (final l in patch.split('\n')) {
    final h = RegExp(r'^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)').firstMatch(l);
    if (h != null) {
      a = int.parse(h[1]!);
      b = int.parse(h[2]!);
      out.add(DiffLine('@', h[3]!.trim(), null, null));
      continue;
    }
    if (l.startsWith('---') || l.startsWith('+++') || l.startsWith('diff ') || l.startsWith('index ') || l.startsWith('\\')) continue;
    if (l.startsWith('+')) {
      out.add(DiffLine('+', l.substring(1), null, b++));
    } else if (l.startsWith('-')) {
      out.add(DiffLine('-', l.substring(1), a++, null));
    } else if (l.startsWith(' ')) {
      out.add(DiffLine(' ', l.substring(1), a++, b++));
    }
  }
  return out;
}

class Plus extends StatelessWidget {
  const Plus(this.add, this.del, {super.key, this.size = 12.5});
  final int add, del;
  final double size;
  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final s = T.code.copyWith(fontSize: size, fontWeight: FontWeight.w500, height: 1.2);
    return Text.rich(
      TextSpan(
        children: [
          if (add > 0 || del == 0)
            TextSpan(
              text: '+$add',
              style: s.copyWith(color: p.good),
            ),
          if (add > 0 && del > 0) const TextSpan(text: ' '),
          if (del > 0)
            TextSpan(
              text: '−$del',
              style: s.copyWith(color: p.bad),
            ),
        ],
      ),
      textDirection: TextDirection.ltr,
    );
  }
}

/// The lines, numbered and coloured, scrolling sideways as one.
class DiffView extends StatelessWidget {
  const DiffView(this.patch, {super.key, this.lang = '', this.max = 400});
  final String patch, lang;
  final int max;

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final lines = parsePatch(patch);
    if (lines.isEmpty) {
      return Padding(
        padding: const EdgeInsets.all(16),
        child: Text(t('Nothing to show: an empty or binary file.'), style: T.small.copyWith(color: p.text3)),
      );
    }
    // a lone opening mark says nothing: the file starts here
    if (lines.first.kind == '@' && lines.first.text.isEmpty) lines.removeAt(0);
    final shown = lines.take(max).toList();
    final base = T.code.copyWith(color: p.text, fontSize: 12, height: 1.6);
    Widget row(DiffLine l) {
      if (l.kind == '@') {
        return Container(
          padding: const EdgeInsets.fromLTRB(12, 6, 12, 6),
          color: p.fill.withValues(alpha: .6),
          child: Text(l.text.isEmpty ? '⋯' : l.text, style: base.copyWith(color: p.text3)),
        );
      }
      final c = l.kind == '+' ? p.good : (l.kind == '-' ? p.bad : null);
      return Container(
        color: c?.withValues(alpha: p.dark ? .1 : .08),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(width: 3, height: 19.2, color: c ?? Colors.transparent),
            SizedBox(
              width: 38,
              child: Text(
                '${l.b ?? l.a ?? ''}',
                textAlign: TextAlign.right,
                style: base.copyWith(color: c?.withValues(alpha: .8) ?? p.text3, fontSize: 10.5),
              ),
            ),
            const SizedBox(width: 12),
            Text.rich(TextSpan(children: paint(l.text.replaceAll('\t', '    '), lang, p)), style: base, softWrap: false),
            const SizedBox(width: 16),
          ],
        ),
      );
    }

    return Directionality(
      textDirection: TextDirection.ltr,
      child: LayoutBuilder(
        builder: (c, box) => SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: ConstrainedBox(
            constraints: BoxConstraints(minWidth: box.maxWidth),
            child: IntrinsicWidth(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  for (final l in shown) row(l),
                  if (lines.length > shown.length)
                    Padding(
                      padding: const EdgeInsets.all(12),
                      child: Text(t('{} more lines', lines.length - shown.length), style: T.small.copyWith(color: p.text3)),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// One changed file: its name, how much changed, and the lines when opened.
class DiffFile extends StatefulWidget {
  const DiffFile(this.d, {super.key, this.root, this.open = false, this.onOpen});
  final J d;
  final String? root;
  final bool open;
  final VoidCallback? onOpen;
  @override
  State<DiffFile> createState() => _DiffFileState();
}

class _DiffFileState extends State<DiffFile> {
  late bool _open = widget.open;
  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final path = '${widget.d['file']}';
    final short = shortPath(path, widget.root);
    final status = '${widget.d['status'] ?? ''}';
    final add = (widget.d['additions'] as num?)?.toInt() ?? 0, del = (widget.d['deletions'] as num?)?.toInt() ?? 0;
    return Container(
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: p.surface,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: p.line),
      ),
      child: Column(
        children: [
          Press(
            onTap: () => setState(() => _open = !_open),
            onLong: widget.onOpen,
            scale: .99,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 11, 14, 11),
              child: Row(
                children: [
                  Square(fileIcon(path), color: status == 'deleted' ? p.bad : (status == 'added' ? p.good : fileColor(path, p)), size: 34),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          baseName(path),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: T.row.copyWith(color: p.text),
                        ),
                        Text(
                          short.contains('/')
                              ? short.substring(0, short.lastIndexOf('/'))
                              : (status == 'added' ? t('New file') : (status == 'deleted' ? t('Deleted') : t('Project folder'))),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: T.tiny.copyWith(color: p.text3),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 10),
                  Plus(add, del),
                  const SizedBox(width: 8),
                  AnimatedRotation(
                    turns: _open ? .25 : 0,
                    duration: med,
                    child: Icon(LucideIcons.chevronRight, size: 16, color: p.text3),
                  ),
                ],
              ),
            ),
          ),
          Fold(
            open: _open,
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.only(bottom: 4),
              decoration: BoxDecoration(
                color: p.code,
                border: Border(top: BorderSide(color: p.line)),
              ),
              child: _open ? DiffView('${widget.d['patch'] ?? ''}', lang: langOf(path)) : const SizedBox(),
            ),
          ),
        ],
      ),
    );
  }
}
