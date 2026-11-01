// Model providers: paste a key, AFH checks it by fetching the models it can use, and it's kept in the
// phone's keystore. Nothing goes through AFH's servers.
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_animate/flutter_animate.dart';
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
            const Padding(
              padding: EdgeInsets.fromLTRB(8, 0, 8, 16),
              child: Text(
                'Your keys stay in this phone\'s secure storage, and chats go straight from here to the provider.',
                style: TextStyle(color: Afh.text2, height: 1.45),
              ),
            ),
            for (final (i, p) in providers.indexed)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: Pressable(
                  onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => ProviderPage(provider: p))),
                  child: Container(
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: Afh.surface,
                      borderRadius: BorderRadius.circular(22),
                      border: Border.all(color: p.ready ? p.color.withValues(alpha: 0.35) : Afh.line),
                    ),
                    child: Row(
                      children: [
                        Hero(tag: 'prov-${p.id}', child: ProviderBadge(p, size: 46)),
                        const SizedBox(width: 14),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(p.name, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
                              const SizedBox(height: 3),
                              Text(
                                p.blurb,
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(color: Afh.text2, fontSize: 13),
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(width: 8),
                        p.ready
                            ? Container(
                                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                                decoration: BoxDecoration(color: Afh.good.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(999)),
                                child: const Row(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    Icon(Icons.check_rounded, size: 14, color: Afh.good),
                                    SizedBox(width: 4),
                                    Text(
                                      'On',
                                      style: TextStyle(color: Afh.good, fontWeight: FontWeight.w700, fontSize: 12),
                                    ),
                                  ],
                                ),
                              )
                            : const Icon(Icons.add_circle_outline_rounded, color: Afh.text3),
                      ],
                    ),
                  ),
                ),
              ).animate().fadeIn(delay: (i * 45).ms).moveX(begin: 18, end: 0, delay: (i * 45).ms, curve: Afh.ease, duration: 450.ms),
          ],
        ),
      ),
    );
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
      appBar: AppBar(),
      body: ListenableBuilder(
        listenable: Settings.i,
        builder: (context, _) => ListView(
          padding: EdgeInsets.fromLTRB(22, 0, 22, 40 + MediaQuery.paddingOf(context).bottom),
          children: [
            Center(
              child: Stack(
                clipBehavior: Clip.none,
                children: [
                  Hero(tag: 'prov-${p.id}', child: ProviderBadge(p, size: 88)),
                  if (p.ready)
                    Positioned(
                      right: -4,
                      bottom: -4,
                      child: Container(
                        padding: const EdgeInsets.all(5),
                        decoration: BoxDecoration(
                          color: Afh.good,
                          shape: BoxShape.circle,
                          border: Border.all(color: Afh.bg, width: 3),
                        ),
                        child: const Icon(Icons.check_rounded, size: 16, color: Afh.bg),
                      ).animate().scale(curve: Afh.spring, duration: 500.ms),
                    ),
                ],
              ),
            ),
            const SizedBox(height: 18),
            Text(p.name, textAlign: TextAlign.center, style: Afh.h2()),
            const SizedBox(height: 6),
            Text(
              p.blurb,
              textAlign: TextAlign.center,
              style: const TextStyle(color: Afh.text2),
            ),
            const SizedBox(height: 28),
            if (p.id == 'custom') ...[
              const Text('SERVER ADDRESS', style: Afh.label),
              const SizedBox(height: 8),
              TextField(
                controller: _base,
                keyboardType: TextInputType.url,
                autocorrect: false,
                decoration: const InputDecoration(hintText: 'http://192.168.1.20:11434/v1'),
              ),
              const SizedBox(height: 6),
              const Text('Any server that speaks the OpenAI chat API: Ollama, LM Studio, vLLM, LiteLLM…', style: TextStyle(color: Afh.text3, fontSize: 12.5)),
              const SizedBox(height: 20),
            ],
            Text(p.id == 'custom' ? 'API KEY (OPTIONAL)' : 'API KEY', style: Afh.label),
            const SizedBox(height: 8),
            TextField(
              controller: _key,
              obscureText: _hidden,
              autocorrect: false,
              enableSuggestions: false,
              style: const TextStyle(fontFamily: Afh.mono, fontSize: 14.5),
              decoration: InputDecoration(
                hintText: p.keyHint,
                suffixIcon: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    IconButton(
                      tooltip: 'Paste',
                      icon: const Icon(Icons.content_paste_rounded, size: 20, color: Afh.text2),
                      onPressed: () async {
                        final d = await Clipboard.getData(Clipboard.kTextPlain);
                        if (d?.text != null) setState(() => _key.text = d!.text!.trim());
                      },
                    ),
                    IconButton(
                      tooltip: _hidden ? 'Show' : 'Hide',
                      icon: Icon(_hidden ? Icons.visibility_rounded : Icons.visibility_off_rounded, size: 20, color: Afh.text2),
                      onPressed: () => setState(() => _hidden = !_hidden),
                    ),
                  ],
                ),
              ),
            ),
            if (p.keysUrl.isNotEmpty)
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  onPressed: () => launchUrl(Uri.parse(p.keysUrl), mode: LaunchMode.externalApplication),
                  icon: const Icon(Icons.open_in_new_rounded, size: 16),
                  label: Text('Get a key from ${p.name}'),
                  style: TextButton.styleFrom(padding: EdgeInsets.zero, foregroundColor: Afh.orange),
                ),
              ),
            AnimatedSize(
              duration: const Duration(milliseconds: 300),
              curve: Afh.ease,
              child: _error == null
                  ? const SizedBox(width: double.infinity)
                  : Container(
                      width: double.infinity,
                      margin: const EdgeInsets.only(top: 10),
                      padding: const EdgeInsets.all(14),
                      decoration: BoxDecoration(
                        color: Afh.bad.withValues(alpha: 0.1),
                        borderRadius: BorderRadius.circular(16),
                        border: Border.all(color: Afh.bad.withValues(alpha: 0.35)),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(_error!, style: const TextStyle(color: Color(0xFFFFC2CD), height: 1.4)),
                          if (_key.text.trim().isNotEmpty || p.id == 'custom')
                            TextButton(
                              onPressed: _busy ? null : () => _save(force: true),
                              style: TextButton.styleFrom(padding: EdgeInsets.zero, foregroundColor: Afh.text2),
                              child: const Text('Save it anyway'),
                            ),
                        ],
                      ),
                    ).animate().shakeX(hz: 4, amount: 3, duration: 400.ms),
            ),
            const SizedBox(height: 22),
            GradButton(label: ready ? 'Save and check again' : 'Connect', icon: Icons.bolt_rounded, busy: _busy, onTap: _save),
            if (_count != null || (ready && (Settings.i.models[p.id] ?? []).isNotEmpty)) ...[
              const SizedBox(height: 14),
              Center(
                child: Text(
                  '${_count ?? Settings.i.models[p.id]!.length} models available',
                  style: const TextStyle(color: Afh.good, fontWeight: FontWeight.w600),
                ),
              ).animate().fadeIn(),
            ],
            if (ready) ...[
              const SizedBox(height: 14),
              Center(
                child: TextButton(
                  onPressed: _remove,
                  child: const Text('Remove this provider', style: TextStyle(color: Afh.bad)),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
