// Markdown for replies, styled for the dark AFH look: code blocks get a header with the language
// and a copy button, links open in the browser.
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:markdown/markdown.dart' as md;
import 'package:url_launcher/url_launcher.dart';

import '../theme.dart';
import 'common.dart';

class Md extends StatelessWidget {
  const Md(this.text, {super.key, this.size = 15.5});
  final String text;
  final double size;

  @override
  Widget build(BuildContext context) {
    final base = TextStyle(fontSize: size, height: 1.55, color: Afh.text);
    return MarkdownBody(
      data: text,
      selectable: false,
      softLineBreak: true,
      extensionSet: md.ExtensionSet.gitHubWeb,
      onTapLink: (_, href, _) {
        final uri = href == null ? null : Uri.tryParse(href);
        if (uri != null && (uri.scheme == 'http' || uri.scheme == 'https')) launchUrl(uri, mode: LaunchMode.externalApplication);
      },
      builders: {'pre': _CodeBuilder()},
      styleSheet: MarkdownStyleSheet(
        p: base,
        a: base.copyWith(color: const Color(0xFFFF9A6A), decoration: TextDecoration.underline, decorationColor: const Color(0x66FF9A6A)),
        strong: const TextStyle(fontWeight: FontWeight.w700, color: Colors.white),
        em: const TextStyle(fontStyle: FontStyle.italic),
        h1: Afh.h2().copyWith(fontSize: 23),
        h2: Afh.h3().copyWith(fontSize: 20),
        h3: Afh.h3().copyWith(fontSize: 17.5),
        h4: base.copyWith(fontWeight: FontWeight.w700),
        h1Padding: const EdgeInsets.only(top: 8, bottom: 2),
        h2Padding: const EdgeInsets.only(top: 8, bottom: 2),
        h3Padding: const EdgeInsets.only(top: 6),
        blockSpacing: 11,
        listIndent: 22,
        listBullet: base.copyWith(color: Afh.orange, fontWeight: FontWeight.w700),
        code: TextStyle(fontFamily: Afh.mono, fontSize: size * 0.86, color: const Color(0xFFFFC59E), backgroundColor: Colors.white.withValues(alpha: 0.07)),
        codeblockPadding: EdgeInsets.zero,
        codeblockDecoration: const BoxDecoration(),
        blockquote: base.copyWith(color: Afh.text2),
        blockquoteDecoration: const BoxDecoration(
          border: Border(left: BorderSide(color: Afh.orange, width: 3)),
        ),
        blockquotePadding: const EdgeInsets.only(left: 14, top: 2, bottom: 2),
        horizontalRuleDecoration: const BoxDecoration(
          border: Border(top: BorderSide(color: Afh.line2)),
        ),
        tableHead: base.copyWith(fontWeight: FontWeight.w700),
        tableBody: base.copyWith(fontSize: size - 1),
        tableBorder: TableBorder.all(color: Afh.line2, width: 1),
        tableCellsPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
        tableColumnWidth: const IntrinsicColumnWidth(),
      ),
    );
  }
}

class _CodeBuilder extends MarkdownElementBuilder {
  @override
  bool isBlockElement() => true;

  @override
  Widget? visitElementAfterWithContext(BuildContext context, md.Element element, TextStyle? preferredStyle, TextStyle? parentStyle) {
    var lang = '';
    final code = element.children?.whereType<md.Element>().firstOrNull;
    final cls = code?.attributes['class'] ?? '';
    if (cls.startsWith('language-')) lang = cls.substring(9);
    final text = element.textContent.replaceFirst(RegExp(r'\n$'), '');
    return CodeBlock(text: text, lang: lang);
  }
}

class CodeBlock extends StatelessWidget {
  const CodeBlock({super.key, required this.text, this.lang = ''});
  final String text;
  final String lang;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.symmetric(vertical: 2),
      decoration: BoxDecoration(
        color: const Color(0xFF0F0C0A),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: Afh.line2),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.fromLTRB(14, 6, 4, 6),
            decoration: const BoxDecoration(
              border: Border(bottom: BorderSide(color: Afh.line)),
            ),
            child: Row(
              children: [
                Text(
                  lang.isEmpty ? 'code' : lang,
                  style: const TextStyle(fontFamily: Afh.mono, fontSize: 12, color: Afh.text3),
                ),
                const Spacer(),
                _CopyButton(text: text),
              ],
            ),
          ),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.fromLTRB(14, 12, 14, 14),
            child: Text(
              text,
              style: const TextStyle(fontFamily: Afh.mono, fontSize: 13, height: 1.5, color: Color(0xFFF1E4D8)),
            ),
          ),
        ],
      ),
    );
  }
}

class _CopyButton extends StatefulWidget {
  const _CopyButton({required this.text});
  final String text;
  @override
  State<_CopyButton> createState() => _CopyButtonState();
}

class _CopyButtonState extends State<_CopyButton> {
  bool _done = false;
  @override
  Widget build(BuildContext context) {
    return Pressable(
      onTap: () async {
        await Clipboard.setData(ClipboardData(text: widget.text));
        setState(() => _done = true);
        await Future.delayed(const Duration(milliseconds: 1600));
        if (mounted) setState(() => _done = false);
      },
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        child: AnimatedSwitcher(
          duration: const Duration(milliseconds: 200),
          transitionBuilder: (c, a) => ScaleTransition(
            scale: a,
            child: FadeTransition(opacity: a, child: c),
          ),
          child: Row(
            key: ValueKey(_done),
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(_done ? Icons.check_rounded : Icons.copy_rounded, size: 15, color: _done ? Afh.good : Afh.text2),
              const SizedBox(width: 5),
              Text(
                _done ? 'Copied' : 'Copy',
                style: TextStyle(fontSize: 12.5, color: _done ? Afh.good : Afh.text2, fontWeight: FontWeight.w600),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
