// Model providers: paste a key, AFH checks it by fetching the models it can use, and it's kept in the
// phone's keystore. Nothing goes through AFH's servers.
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'package:url_launcher/url_launcher.dart';

import '../ai.dart';
import '../store.dart';
import '../theme.dart';
import '../widgets/badge.dart';
import '../widgets/common.dart';

class ProvidersScreen extends StatelessWidget {
  const ProvidersScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Providers')),
      body: ListenableBuilder(
        listenable: Settings.i,
        builder: (context, _) => ListView(
          padding: EdgeInsets.fromLTRB(16, 4, 16, 30 + MediaQuery.paddingOf(context).bottom),
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(4, 0, 4, 0),
              child: Text(
                'Your keys stay in this phone\'s secure storage, and chats go straight from here to the provider.',
                style: Afh.small.copyWith(fontSize: 13.5, height: 1.45),
              ),
            ).enter(0),
            const SectionLabel('Providers', padding: EdgeInsets.fromLTRB(4, 22, 4, 8)),
            Group(
              inset: 62,
              children: [
                for (final p in providers)
                  Tile(
                    leading: Hero(tag: 'prov-${p.id}', child: ProviderBadge(p, size: 32)),
                    title: p.name,
                    subtitle: p.ready ? _connected(p) : p.blurb,
                    trailing: p.ready ? Pill('Connected', color: Afh.good) : null,
                    chevron: true,
                    onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => ProviderPage(provider: p))),
                  ),
              ],
            ).enter(1),
          ],
        ),
      ),
    );
  }

  static String _connected(Provider p) {
    final n = (Settings.i.models[p.id] ?? const []).length;
    return n == 0 ? 'Connected' : 'Connected · $n model${n == 1 ? '' : 's'}';
  }
}

class ProviderPage extends StatefulWidget {
  const ProviderPage({super.key, required this.provider});
  final Provider provider;
  @override
  State<ProviderPage> createState() => _ProviderPageState();
}

class _ProviderPageState extends State<ProviderPage> {
  late final _key = TextEditingController(text: Settings.i.keys[widget.provider.id] ?? '');
  late final _base = TextEditingController(text: Settings.i.baseUrl(widget.provider.id) ?? '');
  bool _hidden = true;
  bool _busy = false;
  bool _allModels = false;
  String? _error;
  int? _count;

  Provider get p => widget.provider;

  @override
  void dispose() {
    _key.dispose();
    _base.dispose();
    super.dispose();
  }

  Future<void> _save({bool force = false}) async {
    FocusScope.of(context).unfocus();
    final key = _key.text.trim();
    final oldBase = Settings.i.baseUrl(p.id);
    if (p.id == 'custom') {
      final url = _base.text.trim();
      if (!RegExp(r'^https?://').hasMatch(url)) {
        setState(() => _error = 'Enter the server address, starting with http:// or https://');
        return;
      }
      Settings.i.setBaseUrl(p.id, url);
    } else if (key.isEmpty) {
      setState(() => _error = 'Paste your API key first.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    final old = Settings.i.keys[p.id];
    await Settings.i.setKey(p.id, key);
    try {
      final models = await fetchModels(p);
      await Settings.i.setModels(p.id, models);
      HapticFeedback.mediumImpact();
      setState(() => _count = models.length);
      if (!mounted) return;
      showToast(context, '${p.name} connected · ${models.length} models');
    } on AiError catch (e) {
      if (!force) {
        await Settings.i.setKey(p.id, old);
        if (p.id == 'custom') Settings.i.setBaseUrl(p.id, oldBase);
      }
      setState(() => _error = e.message);
      HapticFeedback.heavyImpact();
    }
    if (mounted) setState(() => _busy = false);
  }

  Future<void> _remove() async {
    await Settings.i.setKey(p.id, null);
    if (p.id == 'custom') Settings.i.setBaseUrl(p.id, null);
    _key.clear();
    _base.clear();
    setState(() {
      _count = null;
      _error = null;
    });
    if (mounted) showToast(context, '${p.name} removed');
  }

  @override
  Widget build(BuildContext context) {
    final ready = p.ready;
    return Scaffold(
      appBar: AppBar(title: Text(p.name)),
      body: ListenableBuilder(
        listenable: Settings.i,
        builder: (context, _) {
          final models = Settings.i.models[p.id] ?? const <String>[];
          final showModels = _count != null || (ready && models.isNotEmpty);
          final shownModels = _allModels ? models : models.take(8).toList();
          return ListView(
            keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
            padding: EdgeInsets.fromLTRB(16, 8, 16, 40 + MediaQuery.paddingOf(context).bottom),
            children: [
              // header: badge, name, blurb
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(color: Afh.surface, borderRadius: BorderRadius.circular(16), border: Border.all(color: Afh.line)),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Hero(tag: 'prov-${p.id}', child: ProviderBadge(p, size: 48)),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Flexible(
                                child: Text(p.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: Afh.h3()),
                              ),
                              if (p.ready) ...[
                                const SizedBox(width: 8),
                                Pill('Connected', color: Afh.good, icon: LucideIcons.check),
                              ],
                            ],
                          ),
                          const SizedBox(height: 4),
                          Text(p.blurb, style: Afh.small.copyWith(fontSize: 13.5)),
                        ],
                      ),
                    ),
                  ],
                ),
              ).enter(0),
              if (p.id == 'custom') ...[
                const SectionLabel('Server address'),
                TextField(
                  controller: _base,
                  keyboardType: TextInputType.url,
                  autocorrect: false,
                  style: TextStyle(fontFamily: Afh.mono, fontSize: 14, color: Afh.text),
                  decoration: const InputDecoration(hintText: 'http://192.168.1.20:11434/v1'),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(4, 8, 4, 0),
                  child: Text(
                    'Any server that speaks the OpenAI chat API: Ollama, LM Studio, vLLM, LiteLLM…',
                    style: TextStyle(color: Afh.text3, fontSize: 12.5, height: 1.4),
                  ),
                ),
              ],
              SectionLabel(p.id == 'custom' ? 'API key (optional)' : 'API key'),
              TextField(
                controller: _key,
                obscureText: _hidden,
                autocorrect: false,
                enableSuggestions: false,
                style: TextStyle(fontFamily: Afh.mono, fontSize: 14, color: Afh.text),
                decoration: InputDecoration(
                  hintText: p.keyHint,
                  suffixIcon: Padding(
                    padding: const EdgeInsets.only(right: 4),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        IconBtn(
                          LucideIcons.clipboardPaste,
                          tooltip: 'Paste',
                          size: 36,
                          iconSize: 17,
                          color: Afh.text3,
                          onTap: () async {
                            final d = await Clipboard.getData(Clipboard.kTextPlain);
                            if (d?.text != null) setState(() => _key.text = d!.text!.trim());
                          },
                        ),
                        IconBtn(
                          _hidden ? LucideIcons.eye : LucideIcons.eyeOff,
                          tooltip: _hidden ? 'Show' : 'Hide',
                          size: 36,
                          iconSize: 17,
                          color: Afh.text3,
                          onTap: () => setState(() => _hidden = !_hidden),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
              if (p.keysUrl.isNotEmpty)
                Align(
                  alignment: Alignment.centerLeft,
                  child: Pressable(
                    onTap: () => launchUrl(Uri.parse(p.keysUrl), mode: LaunchMode.externalApplication),
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(4, 12, 4, 4),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(LucideIcons.externalLink, size: 15, color: Afh.accent),
                          const SizedBox(width: 6),
                          Flexible(
                            child: Text(
                              'Get a key from ${p.name}',
                              style: TextStyle(color: Afh.accent, fontWeight: FontWeight.w600, fontSize: 13.5),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              AnimatedSize(
                duration: Afh.med,
                curve: Afh.ease,
                child: _error == null
                    ? const SizedBox(width: double.infinity)
                    : Container(
                        width: double.infinity,
                        margin: const EdgeInsets.only(top: 12),
                        padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
                        decoration: BoxDecoration(
                          color: Afh.bad.withValues(alpha: Afh.p.dark ? 0.1 : 0.07),
                          borderRadius: BorderRadius.circular(Afh.r),
                          border: Border.all(color: Afh.bad.withValues(alpha: 0.3)),
                        ),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Padding(
                              padding: const EdgeInsets.only(top: 1),
                              child: Icon(LucideIcons.circleAlert, size: 16, color: Afh.bad),
                            ),
                            const SizedBox(width: 10),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(_error!, style: TextStyle(color: Afh.text, fontSize: 13.5, height: 1.4)),
                                  if (_key.text.trim().isNotEmpty || p.id == 'custom')
                                    TextButton(
                                      onPressed: _busy ? null : () => _save(force: true),
                                      style: TextButton.styleFrom(
                                        padding: EdgeInsets.zero,
                                        minimumSize: const Size(0, 36),
                                        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                                        foregroundColor: Afh.text2,
                                      ),
                                      child: const Text('Save it anyway', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13.5)),
                                    ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ).animate().shakeX(hz: 4, amount: 2, duration: 350.ms),
              ),
              const SizedBox(height: 20),
              PrimaryButton(label: ready ? 'Save and check again' : 'Connect', icon: LucideIcons.zap, busy: _busy, onTap: _save),
              if (showModels) ...[
                SectionLabel(
                  '${_count ?? models.length} models available',
                  trailing: models.length > 8
                      ? Pressable(
                          onTap: () => setState(() => _allModels = !_allModels),
                          child: Text(
                            _allModels ? 'Show less' : 'Show all',
                            style: TextStyle(color: Afh.accent, fontWeight: FontWeight.w600, fontSize: 12.5),
                          ),
                        )
                      : null,
                ),
                if (shownModels.isNotEmpty)
                  Group(
                    inset: 16,
                    children: [
                      for (final m in shownModels)
                        Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                          child: Text(
                            m,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(fontFamily: Afh.mono, fontSize: 13.5, color: Afh.text2),
                          ),
                        ),
                    ],
                  ).enter(0),
              ],
              if (ready) ...[
                const SizedBox(height: 24),
                SecondaryButton(label: 'Remove this provider', icon: LucideIcons.trash2, danger: true, expand: true, onTap: _remove),
              ],
            ],
          );
        },
      ),
    );
  }
}
