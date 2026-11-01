import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../ai.dart';
import '../theme.dart';

/// A provider's round badge: its initial on a wash of its own colour.
class ProviderBadge extends StatelessWidget {
  const ProviderBadge(this.provider, {super.key, this.size = 40});
  final Provider provider;
  final double size;
  @override
  Widget build(BuildContext context) {
    final c = provider.color;
    final fg = Afh.p.dark ? Color.lerp(c, Colors.white, 0.3)! : Color.lerp(c, Colors.black, 0.15)!;
    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(shape: BoxShape.circle, color: c.withValues(alpha: Afh.p.dark ? 0.2 : 0.14)),
      child: provider.id == 'custom'
          ? Icon(LucideIcons.server, size: size * 0.46, color: fg)
          : Text(
              provider.initials,
              style: TextStyle(fontFamily: Afh.display, fontWeight: FontWeight.w600, fontSize: size * 0.44, color: fg, height: 1),
            ),
    );
  }
}
