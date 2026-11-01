// The bottom sheet for picking a model across every provider that has a key.
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

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

  void _providers() {
    Navigator.pop(context);
    Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ProvidersScreen()));
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
              padding: const EdgeInsets.fromLTRB(20, 0, 8, 10),
              child: Row(
                children: [
                  Expanded(child: Text('Choose a model', style: Afh.h2())),
                  TextButton.icon(
                    onPressed: _providers,
                    icon: Icon(LucideIcons.keyRound, size: 16, color: Afh.accent),
                    label: Text('Providers', style: TextStyle(color: Afh.accent, fontWeight: FontWeight.w600)),
                  ),
                ],
              ),
            ),
          ),
          if (ready.isNotEmpty)
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
                child: TextField(
                  onChanged: (v) => setState(() => _q = v),
                  decoration: InputDecoration(
                    hintText: 'Search models',
                    isDense: true,
                    fillColor: Afh.surface2,
                    prefixIcon: Icon(LucideIcons.search, size: 17, color: Afh.text3),
                    contentPadding: const EdgeInsets.symmetric(vertical: 12),
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
                    enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
                    focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: Afh.line2)),
                  ),
                ),
              ),
            ),
          if (ready.isEmpty)
            SliverToBoxAdapter(
              child: EmptyState(
                icon: LucideIcons.keyRound,
                title: 'No providers yet',
                text: 'Add an API key and its models show up here.',
                action: PrimaryButton(label: 'Add a provider', icon: LucideIcons.plus, expand: false, onTap: _providers),
              ),
            ),
          for (final (pi, p) in ready.indexed) ...[
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(20, 14, 8, 4),
                child: Row(
                  children: [
                    ProviderBadge(p, size: 24),
                    const SizedBox(width: 10),
                    Expanded(child: Text(p.name, style: TextStyle(fontWeight: FontWeight.w600, fontSize: 14.5, color: Afh.text))),
                    _loading.contains(p.id)
                        ? const Padding(padding: EdgeInsets.all(11), child: SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)))
                        : IconBtn(LucideIcons.refreshCw, tooltip: 'Refresh models', iconSize: 16, color: Afh.text3, onTap: () => _refresh(p)),
                  ],
                ),
              ).enter(pi),
            ),
            SliverList.builder(
              itemCount: p.models.where((m) => q.isEmpty || m.toLowerCase().contains(q)).length,
              itemBuilder: (_, i) {
                final m = p.models.where((m) => q.isEmpty || m.toLowerCase().contains(q)).elementAt(i);
                final on = widget.provider == p.id && widget.model == m;
                return Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 1),
                  child: Material(
                    color: on ? Afh.tint : Colors.transparent,
                    borderRadius: BorderRadius.circular(12),
                    child: InkWell(
                      borderRadius: BorderRadius.circular(12),
                      onTap: () {
                        HapticFeedback.selectionClick();
                        Settings.i.lastModel = '${p.id}/$m';
                        Navigator.pop(context, (p.id, m));
                      },
                      child: Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                        child: Row(
                          children: [
                            Expanded(
                              child: Text(
                                m,
                                style: TextStyle(fontFamily: Afh.mono, fontSize: 13.5, color: on ? Afh.text : Afh.text2, fontWeight: on ? FontWeight.w500 : FontWeight.w400),
                              ),
                            ),
                            if (on) Icon(LucideIcons.check, color: Afh.accent, size: 18),
                          ],
                        ),
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
