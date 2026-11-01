import 'package:flutter/material.dart';

import '../ai.dart';
import '../theme.dart';

/// A provider's round badge in its own colour.
class ProviderBadge extends StatelessWidget {
  const ProviderBadge(this.provider, {super.key, this.size = 40});
  final Provider provider;
  final double size;
  @override
  Widget build(BuildContext context) {
    final c = provider.color;
    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [c.withValues(alpha: 0.32), c.withValues(alpha: 0.12)]),
        border: Border.all(color: c.withValues(alpha: 0.55), width: 1.2),
      ),
      child: provider.id == 'custom'
          ? Icon(Icons.dns_rounded, size: size * 0.46, color: c)
          : Text(
              provider.initials,
              style: TextStyle(fontFamily: Afh.display, fontWeight: FontWeight.w700, fontSize: size * 0.44, color: Color.lerp(c, Colors.white, 0.35)),
            ),
    );
  }
}
