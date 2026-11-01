// The bottom sheet for picking a model across every provider that has a key.
import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';

import '../ai.dart';
import '../store.dart';
import '../theme.dart';
import '../widgets/badge.dart';
import '../widgets/common.dart';
import 'providers.dart';

Future<(String, String)?> pickModel(BuildContext context, {String? provider, String? model}) {
  return showModalBottomSheet<(String, String)>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    builder: (_) => DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.72,
      minChildSize: 0.4,
      maxChildSize: 0.95,
      builder: (ctx, scroll) => _Picker(scroll: scroll, provider: provider, model: model),
    ),
  );
}

class _Picker extends StatefulWidget {
  const _Picker({required this.scroll, this.provider, this.model});
  final ScrollController scroll;
  final String? provider, model;
  @override
  State<_Picker> createState() => _PickerState();
}

class _PickerState extends State<_Picker> {
  String _q = '';
  final Set<String> _loading = {};

  @override
  void initState() {
    super.initState();
    // fetch the real model list once for providers that only have the built-in suggestions
    for (final p in providers.where((p) => p.ready && (Settings.i.models[p.id] ?? []).isEmpty)) {
      _refresh(p, quiet: true);
    }
  }

  Future<void> _refresh(Provider p, {bool quiet = false}) async {
    setState(() => _loading.add(p.id));
    try {
      await Settings.i.setModels(p.id, await fetchModels(p));
    } on AiError catch (e) {
      if (!quiet && mounted) showToast(context, e.message, error: true);
    }
    if (mounted) setState(() => _loading.remove(p.id));
  }

  @override
  Widget build(BuildContext context) {
    final ready = providers.where((p) => p.ready).toList();
    final q = _q.toLowerCase();
    return ListenableBuilder(
      listenable: Settings.i,
      builder: (context, _) => CustomScrollView(
        controller: widget.scroll,
        slivers: [
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(22, 0, 22, 12),
              child: Row(
                children: [
                  Expanded(child: Text('Choose a model', style: Afh.h2())),
                  TextButton.icon(
                    onPressed: () {
                      Navigator.pop(context);
                      Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ProvidersScreen()));
                    },
                    icon: const Icon(Icons.key_rounded, size: 18),
                    label: const Text('Providers'),
                  ),
                ],
              ),
            ),
          ),
          if (ready.isNotEmpty)
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(18, 0, 18, 6),
                child: TextField(
                  onChanged: (v) => setState(() => _q = v),
                  decoration: const InputDecoration(
                    hintText: 'Search models',
                    prefixIcon: Icon(Icons.search_rounded, color: Afh.text3),
                    contentPadding: EdgeInsets.symmetric(vertical: 12),
                  ),
                ),
              ),
            ),
          if (ready.isEmpty)
            SliverToBoxAdapter(
              child: EmptyState(
                icon: Icons.key_rounded,
                title: 'No providers yet',
                text: 'Add an API key and its models show up here.',
                action: GradButton(
                  label: 'Add a provider',
                  icon: Icons.add_rounded,
                  onTap: () {
                    Navigator.pop(context);
                    Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ProvidersScreen()));
                  },
                ),
              ),
            ),
          for (final (pi, p) in ready.indexed) ...[
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(22, 18, 10, 6),
                child: Row(
                  children: [
                    ProviderBadge(p, size: 26),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(p.name, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
                    ),
                    _loading.contains(p.id)
                        ? const Padding(
                            padding: EdgeInsets.all(12),
                            child: SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)),
                          )
                        : IconButton(
                            tooltip: 'Refresh models',
                            onPressed: () => _refresh(p),
                            icon: const Icon(Icons.refresh_rounded, size: 20, color: Afh.text3),
                          ),
                  ],
                ),
              ).animate().fadeIn(delay: (pi * 60).ms),
            ),
            SliverList.builder(
              itemCount: p.models.where((m) => q.isEmpty || m.toLowerCase().contains(q)).length,
              itemBuilder: (_, i) {
                final m = p.models.where((m) => q.isEmpty || m.toLowerCase().contains(q)).elementAt(i);
                final on = widget.provider == p.id && widget.model == m;
                return Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 2),
                  child: Pressable(
                    onTap: () {
                      Settings.i.lastModel = '${p.id}/$m';
                      Navigator.pop(context, (p.id, m));
                    },
                    child: AnimatedContainer(
                      duration: const Duration(milliseconds: 250),
                      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
                      decoration: BoxDecoration(
                        color: on ? null : Colors.transparent,
                        gradient: on ? const LinearGradient(colors: [Color(0x30FFB11F), Color(0x30FF3D8A)]) : null,
                        borderRadius: BorderRadius.circular(16),
                        border: Border.all(color: on ? Afh.orange.withValues(alpha: 0.4) : Colors.transparent),
                      ),
                      child: Row(
                        children: [
                          Expanded(
                            child: Text(
                              m,
                              style: TextStyle(
                                fontFamily: Afh.mono,
                                fontSize: 14,
                                color: on ? Afh.text : Afh.text2,
                                fontWeight: on ? FontWeight.w500 : FontWeight.w400,
                              ),
                            ),
                          ),
                          if (on) const Icon(Icons.check_circle_rounded, color: Afh.orange, size: 20),
                        ],
                      ),
                    ),
                  ),
                );
              },
            ),
          ],
          const SliverToBoxAdapter(child: SizedBox(height: 30)),
        ],
      ),
    );
  }
}

/// The model to start a new chat with: the last one picked, else the first provider with a key.
(String, String)? defaultModel() {
  final last = Settings.i.lastModel;
  if (last != null && last.contains('/')) {
    final cut = last.indexOf('/');
    final p = providerById(last.substring(0, cut));
    if (p.id == last.substring(0, cut) && p.ready) return (p.id, last.substring(cut + 1));
  }
  for (final p in providers) {
    if (p.ready && p.models.isNotEmpty) return (p.id, p.models.first);
  }
  return null;
}
