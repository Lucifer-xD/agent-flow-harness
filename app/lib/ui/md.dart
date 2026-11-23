// Replies as text: markdown, code with colours, tables that scroll. While a reply streams, only its last
// block is laid out again; finished blocks keep their widgets.
import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:markdown/markdown.dart' as m;
import 'package:url_launcher/url_launcher.dart';

import '../core/l10n.dart';
import '../core/store.dart';
import 'kit.dart';
import 'look.dart';
import 'motion.dart';

class Md extends StatefulWidget {
  const Md(this.text, {super.key, this.live = false, this.style});
  final String text;
  final bool live;
  final TextStyle? style;
  @override
  State<Md> createState() => _MdState();
}

class _MdState extends State<Md> {
  final Map<String, Widget> _cache = {};
  Pal? _pal;
  double _scale = 1;

  static final _fence = RegExp(r'^\s{0,3}(```|~~~)');
  static final _item = RegExp(r'^(\s{2,}|\s*([-*+]|\d+[.)])\s)');

  List<String> _blocks(String text) {
    final out = <String>[];
    var cur = <String>[];
    var fenced = false;
    for (final line in text.split('\n')) {
      if (_fence.hasMatch(line)) fenced = !fenced;
      if (!fenced && line.trim().isEmpty) {
        if (cur.isNotEmpty) out.add(cur.join('\n'));
        cur = [];
        continue;
      }
      cur.add(line);
    }
    if (cur.isNotEmpty) out.add(cur.join('\n'));
    // a list with gaps between its items is still one list
    final merged = <String>[];
    for (final b in out) {
      if (merged.isNotEmpty && _item.hasMatch(b) && _item.hasMatch(merged.last) && !merged.last.contains('```')) {
        merged.last = '${merged.last}\n\n$b';
      } else {
        merged.add(b);
      }
    }
    return merged;
  }

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final scale = Settings.i.textScale;
    if (_pal != p || _scale != scale) _cache.clear();
    _pal = p;
    _scale = scale;
    final blocks = _blocks(widget.text);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final (i, b) in blocks.indexed)
          Padding(
            key: ValueKey(i),
            padding: EdgeInsets.only(top: i == 0 ? 0 : (b.startsWith('#') ? 20 : 12)),
            child: widget.live && i == blocks.length - 1 ? _Live(child: _block(b, p)) : _cache.putIfAbsent('$i$b', () => _block(b, p)),
          ),
      ],
    );
  }

  Widget _block(String b, Pal p) {
    final rtl = isRtl(b.replaceAll(RegExp(r'^[#>\-*\s\d.]+'), ''));
    final base = (widget.style ?? T.body).copyWith(color: p.text);
    if (_fence.hasMatch(b)) {
      final lines = b.split('\n');
      final lang = lines.first.replaceAll(RegExp(r'[`~\s]'), '');
      final closed = lines.length > 1 && _fence.hasMatch(lines.last);
      return CodeBox(lines.sublist(1, closed ? lines.length - 1 : lines.length).join('\n'), lang: lang);
    }
    final body = MarkdownBody(
      data: b,
      selectable: !widget.live,
      extensionSet: m.ExtensionSet.gitHubFlavored,
      onTapLink: (_, href, _) {
        final u = Uri.tryParse(href ?? '');
        if (u != null && u.hasScheme) launchUrl(u, mode: LaunchMode.externalApplication);
      },
      builders: {'pre': _Pre(), 'code': _Inline(p)},
      imageBuilder: (uri, _, _) => ClipRRect(
        borderRadius: BorderRadius.circular(14),
        child: Image.network('$uri', errorBuilder: (_, _, _) => const SizedBox()),
      ),
      styleSheet: MarkdownStyleSheet(
        p: base,
        pPadding: EdgeInsets.zero,
        blockSpacing: 10,
        strong: const TextStyle(fontWeight: FontWeight.w600),
        em: const TextStyle(fontStyle: FontStyle.italic),
        a: TextStyle(color: p.accent, decoration: TextDecoration.underline, decorationColor: p.accent.withValues(alpha: .35)),
        h1: T.title.copyWith(color: p.text, fontSize: 22),
        h2: T.h1.copyWith(color: p.text, fontSize: 19),
        h3: T.h2.copyWith(color: p.text),
        h4: T.h3.copyWith(color: p.text),
        h5: T.h3.copyWith(color: p.text2),
        h6: T.label.copyWith(color: p.text2),
        listBullet: base.copyWith(color: p.text3),
        listIndent: 22,
        listBulletPadding: rtl ? const EdgeInsets.only(left: 8) : const EdgeInsets.only(right: 8),
        blockquote: base.copyWith(color: p.text2),
        blockquotePadding: rtl ? const EdgeInsets.fromLTRB(0, 2, 14, 2) : const EdgeInsets.fromLTRB(14, 2, 0, 2),
        blockquoteDecoration: BoxDecoration(
          border: BorderDirectional(
            start: BorderSide(color: p.accent.withValues(alpha: .6), width: 2.5),
          ),
        ),
        horizontalRuleDecoration: BoxDecoration(
          border: Border(top: BorderSide(color: p.line)),
        ),
        tableHeadAlign: TextAlign.start,
        tableHead: T.small.copyWith(color: p.text2, fontWeight: FontWeight.w600),
        tableBody: T.sub.copyWith(color: p.text),
        tableBorder: TableBorder(
          horizontalInside: BorderSide(color: p.line),
          top: BorderSide(color: p.line),
          bottom: BorderSide(color: p.line),
        ),
        tableColumnWidth: const IntrinsicColumnWidth(),
        tableCellsPadding: rtl ? const EdgeInsets.fromLTRB(22, 10, 0, 10) : const EdgeInsets.fromLTRB(0, 10, 22, 10),
        checkbox: T.body.copyWith(color: p.accent),
      ),
    );
    return Directionality(
      textDirection: rtl ? TextDirection.rtl : TextDirection.ltr,
      child: Align(alignment: rtl ? Alignment.topRight : Alignment.topLeft, child: body),
    );
  }
}

/// The block being written fades in as it arrives.
class _Live extends StatefulWidget {
  const _Live({required this.child});
  final Widget child;
  @override
  State<_Live> createState() => _LiveState();
}

class _LiveState extends State<_Live> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 260))..forward();
  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => FadeTransition(opacity: _c, child: widget.child);
}

class _Pre extends MarkdownElementBuilder {
  @override
  bool isBlockElement() => true;
  @override
  Widget? visitElementAfterWithContext(BuildContext context, m.Element e, TextStyle? a, TextStyle? b) {
    final code = e.children?.whereType<m.Element>().firstOrNull;
    final lang = (code?.attributes['class'] ?? '').replaceFirst('language-', '');
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: CodeBox(e.textContent.trimRight(), lang: lang),
    );
  }
}

class _Inline extends MarkdownElementBuilder {
  _Inline(this.p);
  final Pal p;
  @override
  Widget? visitElementAfterWithContext(BuildContext context, m.Element e, TextStyle? a, TextStyle? b) {
    if (e.attributes['class']?.startsWith('language-') == true || e.textContent.contains('\n')) return null;
    return Text.rich(
      WidgetSpan(
        alignment: PlaceholderAlignment.middle,
        child: Container(
          margin: const EdgeInsets.symmetric(horizontal: 1),
          padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1.5),
          decoration: BoxDecoration(color: p.fill, borderRadius: BorderRadius.circular(6)),
          child: Text(e.textContent, style: T.code.copyWith(color: p.text, fontSize: 13, height: 1.35)),
        ),
      ),
    );
  }
}

/// Code in a box: language, copy, and colours.
class CodeBox extends StatelessWidget {
  const CodeBox(this.code, {super.key, this.lang = '', this.max, this.head = true});
  final String code, lang;
  final double? max;
  final bool head;

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    Widget body = SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: EdgeInsets.fromLTRB(15, head ? 4 : 13, 15, 14),
      child: SelectableText.rich(TextSpan(children: paint(code, lang, p)), style: T.code.copyWith(color: p.text)),
    );
    if (max != null) body = ConstrainedBox(constraints: BoxConstraints(maxHeight: max!), child: SingleChildScrollView(child: body));
    return Directionality(
      textDirection: TextDirection.ltr,
      child: Container(
        width: double.infinity,
        clipBehavior: Clip.antiAlias,
        decoration: BoxDecoration(color: p.code, borderRadius: BorderRadius.circular(16), border: Border.all(color: p.line)),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (head)
              Padding(
                padding: const EdgeInsets.fromLTRB(15, 4, 4, 0),
                child: Row(
                  children: [
                    Expanded(child: Text(lang.isEmpty ? 'text' : lang, style: T.tiny.copyWith(color: p.text3, fontFamily: mono))),
                    Press(
                      onTap: () => copyText(context, code, t('Code copied')),
                      child: Padding(
                        padding: const EdgeInsets.all(10),
                        child: Icon(LucideIcons.copy, size: 14, color: p.text3),
                      ),
                    ),
                  ],
                ),
              ),
            body,
          ],
        ),
      ),
    );
  }
}

final _tok = RegExp(
  r'''("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`)''' // strings
  r'|(//[^\n]*|/\*[\s\S]*?\*/|#[^\n{]*|<!--[\s\S]*?-->|--\s[^\n]*)' // comments
  r'|(\b\d[\d_.]*(?:px|em|rem|%|s|ms)?\b|#[0-9a-fA-F]{3,8}\b)' // numbers
  r'|([A-Za-z_$][\w$]*)(?=(\s*\()?)', // words (and whether they are called)
);
const _kw =
    ' abstract and as assert async await bool break case catch char class const continue def default del do double dyn elif else end enum except export extends extern false False final finally float fn for foreach from func function get global go goto if impl implements import in int interface is lambda let local loop match mod module mut namespace new nil None nonlocal not null of or override package pass print private protected pub public raise readonly record ref required return select self set sizeof static str string struct super switch then this throw throws trait true True try type typedef typeof union unsafe use using val var virtual void when where while with yield echo fi esac done select insert update delete create table join on group by order limit ';

/// Colours for code: strings, comments, numbers, keywords, calls and types.
List<TextSpan> paint(String code, String lang, Pal p) {
  if (const {'', 'text', 'txt', 'output', 'md', 'markdown'}.contains(lang.toLowerCase()) || code.length > 30000) return [TextSpan(text: code)];
  final hash = const {'py', 'python', 'sh', 'bash', 'zsh', 'yaml', 'yml', 'rb', 'ruby', 'toml', 'powershell', 'ps1', 'r', 'dockerfile', 'makefile'}.contains(lang.toLowerCase());
  final dash = const {'sql', 'lua', 'haskell'}.contains(lang.toLowerCase());
  final str = p.dark ? const Color(0xFF9BD6A3) : const Color(0xFF1D7A46);
  final com = p.text3;
  final number = p.dark ? const Color(0xFFF2B57B) : const Color(0xFFA85A00);
  final key = p.dark ? const Color(0xFFFF8FA3) : const Color(0xFFC2255C);
  final call = p.dark ? const Color(0xFF8DB9FF) : const Color(0xFF2457C5);
  final type = p.dark ? const Color(0xFFC9A7FF) : const Color(0xFF6B3FC9);
  final out = <TextSpan>[];
  var at = 0;
  for (final x in _tok.allMatches(code)) {
    Color? c;
    if (x[1] != null) {
      c = str;
    } else if (x[2] != null) {
      final s = x[2]!;
      if (s.startsWith('#') && !hash || s.startsWith('--') && !dash || s.startsWith('//') && hash) continue;
      c = com;
    } else if (x[3] != null) {
      c = number;
    } else {
      final w = x[4]!;
      c = _kw.contains(' $w ')
          ? key
          : x[5] != null
          ? call
          : RegExp(r'^[A-Z][a-z]').hasMatch(w)
          ? type
          : null;
      if (c == null) continue;
    }
    if (x.start > at) out.add(TextSpan(text: code.substring(at, x.start)));
    out.add(TextSpan(text: code.substring(x.start, x.end), style: TextStyle(color: c)));
    at = x.end;
  }
  if (at < code.length) out.add(TextSpan(text: code.substring(at)));
  return out;
}

String langOf(String path) => switch (Media.ext(path)) {
  'py' => 'python',
  'js' || 'mjs' || 'jsx' => 'javascript',
  'ts' || 'tsx' => 'typescript',
  'yml' => 'yaml',
  'md' => 'markdown',
  final e => e,
};
