// The app's frame: three tabs under a floating glass bar whose highlight slides to the tab you pick.
import 'dart:ui';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../theme.dart';
import 'chats.dart';
import 'computers.dart';
import 'settings.dart';

class Shell extends StatefulWidget {
  const Shell({super.key});
  static final tab = ValueNotifier<int>(0);
  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  static const _tabs = [
    (Icons.chat_bubble_outline_rounded, Icons.chat_bubble_rounded, 'Chats'),
    (Icons.computer_outlined, Icons.computer_rounded, 'Computers'),
    (Icons.tune_outlined, Icons.tune_rounded, 'Settings'),
  ];
  final _seen = <int>{0};

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<int>(
      valueListenable: Shell.tab,
      builder: (context, index, _) {
        _seen.add(index);
        return PopScope(
          canPop: index == 0,
          onPopInvokedWithResult: (didPop, _) {
            if (!didPop) Shell.tab.value = 0;
          },
          child: Scaffold(
            extendBody: true,
            body: Stack(
              children: [
                for (var i = 0; i < 3; i++)
                  if (_seen.contains(i))
                    Positioned.fill(
                      child: IgnorePointer(
                        ignoring: i != index,
                        child: AnimatedOpacity(
                          opacity: i == index ? 1 : 0,
                          duration: const Duration(milliseconds: 260),
                          curve: Curves.easeOut,
                          child: AnimatedSlide(
                            offset: i == index ? Offset.zero : Offset(0, 0.015 * (i < index ? -1 : 1)),
                            duration: const Duration(milliseconds: 380),
                            curve: Afh.ease,
                            child: TickerMode(enabled: i == index, child: [const ChatsScreen(), const ComputersScreen(), const SettingsScreen()][i]),
                          ),
                        ),
                      ),
                    ),
              ],
            ),
            bottomNavigationBar: _NavBar(
              index: index,
              tabs: _tabs,
              onTap: (i) {
                if (i != index) HapticFeedback.selectionClick();
                Shell.tab.value = i;
              },
            ),
          ),
        );
      },
    );
  }
}

class _NavBar extends StatelessWidget {
  const _NavBar({required this.index, required this.tabs, required this.onTap});
  final int index;
  final List<(IconData, IconData, String)> tabs;
  final ValueChanged<int> onTap;

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.paddingOf(context).bottom;
    return Padding(
      padding: EdgeInsets.fromLTRB(22, 0, 22, bottom > 0 ? bottom : 14),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(30),
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 24, sigmaY: 24),
          child: Container(
            height: 64,
            decoration: BoxDecoration(
              color: const Color(0xCC1A1411),
              borderRadius: BorderRadius.circular(30),
              border: Border.all(color: Afh.line2),
              boxShadow: const [BoxShadow(color: Color(0x66000000), blurRadius: 30, offset: Offset(0, 10))],
            ),
            padding: const EdgeInsets.all(6),
            child: LayoutBuilder(
              builder: (context, c) {
                final w = c.maxWidth / tabs.length;
                return Stack(
                  children: [
                    AnimatedPositioned(
                      duration: const Duration(milliseconds: 520),
                      curve: Afh.spring,
                      left: w * index,
                      top: 0,
                      bottom: 0,
                      width: w,
                      child: Container(
                        decoration: BoxDecoration(
                          gradient: const LinearGradient(colors: [Color(0x40FFB11F), Color(0x40FF3D8A)]),
                          borderRadius: BorderRadius.circular(24),
                          border: Border.all(color: Afh.orange.withValues(alpha: 0.35)),
                        ),
                      ),
                    ),
                    Row(
                      children: [
                        for (var i = 0; i < tabs.length; i++)
                          Expanded(
                            child: GestureDetector(
                              behavior: HitTestBehavior.opaque,
                              onTap: () => onTap(i),
                              child: Semantics(
                                button: true,
                                selected: i == index,
                                label: tabs[i].$3,
                                child: _NavItem(icon: tabs[i].$1, active: tabs[i].$2, label: tabs[i].$3, on: i == index),
                              ),
                            ),
                          ),
                      ],
                    ),
                  ],
                );
              },
            ),
          ),
        ),
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({required this.icon, required this.active, required this.label, required this.on});
  final IconData icon, active;
  final String label;
  final bool on;
  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        AnimatedScale(
          scale: on ? 1.08 : 1,
          duration: const Duration(milliseconds: 400),
          curve: Afh.spring,
          child: on
              ? ShaderMask(shaderCallback: (r) => Afh.grad.createShader(r), blendMode: BlendMode.srcIn, child: Icon(active, size: 23))
              : Icon(icon, size: 23, color: Afh.text3),
        ),
        AnimatedSize(
          duration: const Duration(milliseconds: 380),
          curve: Afh.ease,
          child: on
              ? Padding(
                  padding: const EdgeInsets.only(left: 7),
                  child: Text(
                    label,
                    maxLines: 1,
                    style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13.5, color: Afh.text),
                  ),
                )
              : const SizedBox.shrink(),
        ),
      ],
    );
  }
}
