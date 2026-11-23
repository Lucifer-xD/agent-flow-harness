// Who a model comes from: the provider's own logo, or its initial.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../core/ai.dart';
import 'kit.dart';
import 'look.dart';

Map<String, String> _svg = {}, _exact = {};
List<(String, String)> _words = [], _families = [];

Future<void> loadLogos() async {
  final j = jsonDecode(await rootBundle.loadString('assets/logos.json')) as Map<String, dynamic>;
  _svg = Map<String, String>.from(j['svg'] as Map);
  _exact = Map<String, String>.from(j['exact'] as Map);
  _words = [for (final w in j['words'] as List) ('${w[0]}', '${w[1]}')];
  _families = [for (final w in j['families'] as List) ('${w[0]}', '${w[1]}')];
}

String _logoFor(String id, String name, String model) {
  final pid = id.toLowerCase();
  if (_exact[pid] case final String n) return n;
  final base = pid.replaceFirst(RegExp(r'(-\d+|-(cn|eu|us|intl|global|coding-plan|token-plan))+$'), '');
  if (_exact[base] case final String n) return n;
  final hay = '$pid ${name.toLowerCase()}';
  for (final (w, n) in _words) {
    if (hay.contains(w)) return n;
  }
  final m = model.toLowerCase();
  if (m.isNotEmpty) {
    for (final (w, n) in _families) {
      if (m.contains(w)) return n;
    }
  }
  return '';
}

/// A model family's logo first ("openrouter" showing Claude's for Claude), else the provider's.
class Logo extends StatelessWidget {
  const Logo(this.id, {super.key, this.name = '', this.model = '', this.size = 18, this.color, this.family = false});
  final String id, name, model;
  final double size;
  final Color? color;
  final bool family;

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    var key = '';
    if (family && model.isNotEmpty) {
      final m = model.toLowerCase();
      key = _families.where((f) => m.contains(f.$1)).firstOrNull?.$2 ?? '';
    }
    if (key.isEmpty) key = _logoFor(id, name, model);
    final svg = _svg[key];
    if (svg == null) {
      if (id == 'custom') return Icon(LucideIcons.server, size: size, color: color ?? p.text2);
      final c = providers.where((x) => x.id == id).firstOrNull?.color ?? p.text2;
      final letters = (name.isEmpty ? id : name).replaceAll(RegExp(r'[^A-Za-z0-9]'), '');
      return Container(
        width: size,
        height: size,
        alignment: Alignment.center,
        decoration: BoxDecoration(color: p.tint(c), borderRadius: BorderRadius.circular(size * .3)),
        child: Text(letters.isEmpty ? '?' : letters[0].toUpperCase(), style: TextStyle(fontFamily: 'Geist', fontSize: size * .58, height: 1, fontWeight: FontWeight.w600, color: c)),
      );
    }
    return SvgPicture.string(svg, width: size, height: size, theme: SvgTheme(currentColor: color ?? p.text));
  }
}

/// The logo in a soft square, for lists.
class LogoBox extends StatelessWidget {
  const LogoBox(this.id, {super.key, this.name = '', this.model = '', this.size = 38});
  final String id, name, model;
  final double size;
  @override
  Widget build(BuildContext context) => Square(null, size: size, child: Logo(id, name: name, model: model, size: size * .53));
}
