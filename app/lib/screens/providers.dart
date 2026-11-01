// Model providers, the same list as the desktop's Settings → Models: sign in (ChatGPT, GitHub
// Copilot, OpenRouter) or paste a key; AFH checks it by fetching the models it can use, and it's kept
// in the phone's keystore. Nothing goes through AFH's servers.
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'package:url_launcher/url_launcher.dart';

import '../ai.dart';
import '../signin.dart';
import '../store.dart';
import '../theme.dart';
import '../widgets/badge.dart';
import '../widgets/common.dart';

class ProvidersScreen extends StatefulWidget {
  const ProvidersScreen({super.key});
  @override
  State<ProvidersScreen> createState() => _ProvidersScreenState();
}

class _ProvidersScreenState extends State<ProvidersScreen> {
  final _search = TextEditingController();
  String _q = '';

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  Widget _group(List<Provider> list) => Group(
    inset: 62,
    children: [
      for (final p in list)
        Tile(
          leading: Hero(tag: 'prov-${p.id}', child: ProviderBadge(p, size: 32)),
          title: p.name,
          subtitle: p.ready ? _connected(p) : p.blurb,
          trailing: p.ready ? Pill('Connected', color: Afh.good) : (p.login != null ? Pill('Sign in', color: Afh.accent) : null),
          chevron: true,
          onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => ProviderPage(provider: p))),
        ),
    ],
  );

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Providers')),
      body: ListenableBuilder(
        listenable: Settings.i,
        builder: (context, _) {
          final q = _q.trim().toLowerCase();
          final found = q.isEmpty ? const <Provider>[] : providers.where((p) => '${p.name} ${p.id}'.toLowerCase().contains(q)).toList();
          final ready = providers.where((p) => p.ready).toList();
          // the sign-ins first: no key to hunt for
          final popular = providers.where((p) => p.featured && !p.ready && p.login != null).toList()
            ..addAll(providers.where((p) => p.featured && !p.ready && p.login == null));
          final more = providers.where((p) => !p.featured && !p.ready).toList();
          return ListView(
            keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
            padding: EdgeInsets.fromLTRB(16, 4, 16, 30 + MediaQuery.paddingOf(context).bottom),
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(4, 0, 4, 14),
                child: Text(
                  'Sign in or paste a key. Keys stay in this phone\'s secure storage, and chats go straight from here to the provider.',
                  style: Afh.small.copyWith(fontSize: 13.5, height: 1.45),
                ),
              ).enter(0),
              TextField(
                controller: _search,
                onChanged: (v) => setState(() => _q = v),
                textInputAction: TextInputAction.search,
                decoration: InputDecoration(
                  hintText: 'Search ${providers.length} providers',
                  prefixIcon: Icon(LucideIcons.search, size: 18, color: Afh.text3),
                  suffixIcon: _q.isEmpty
                      ? null
                      : IconBtn(
                          LucideIcons.x,
                          tooltip: 'Clear',
                          size: 36,
                          iconSize: 17,
                          color: Afh.text3,
                          onTap: () => setState(() {
                            _search.clear();
                            _q = '';
                          }),
                        ),
                ),
              ).enter(1),
              if (q.isNotEmpty) ...[
                SectionLabel(found.isEmpty ? 'No provider matches' : '${found.length} found'),
                if (found.isNotEmpty) _group(found),
                if (found.isEmpty)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(4, 0, 4, 0),
                    child: Text(
                      'Any server that speaks the OpenAI API works as a Custom server.',
                      style: TextStyle(color: Afh.text3, fontSize: 13, height: 1.4),
                    ),
                  ),
              ] else ...[
                if (ready.isNotEmpty) ...[const SectionLabel('Connected'), _group(ready).enter(2)],
                const SectionLabel('Popular'),
                _group(popular).enter(3),
                SectionLabel('More providers · ${more.length}'),
                _group(more),
              ],
            ],
          );
        },
      ),
    );
  }

  static String _connected(Provider p) {
    final account = p.loginOnly ? (Settings.i.auth[p.id]?['account'] as String? ?? '') : '';
    final n = (Settings.i.models[p.id] ?? const []).length;
    final parts = [if (account.isNotEmpty) account, if (n > 0) '$n model${n == 1 ? '' : 's'}'];
    return parts.isEmpty ? 'Connected' : parts.join(' · ');
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
  late final _params = {for (final x in widget.provider.params) x.name: TextEditingController(text: Settings.i.param(widget.provider.id, x.name) ?? x.fallback)};
  bool _hidden = true;
  bool _busy = false;
  bool _allModels = false;
  String? _error;
  int? _count;
  SignIn? _signin;

  Provider get p => widget.provider;

  @override
  void dispose() {
    _signin?.cancel();
    _key.dispose();
    _base.dispose();
    for (final c in _params.values) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _check() async {
    final models = await fetchModels(p);
    await Settings.i.setModels(p.id, models);
    HapticFeedback.mediumImpact();
    if (!mounted) return;
    setState(() => _count = models.length);
    showToast(context, '${p.name} connected · ${models.length} models');
  }

  Future<void> _save({bool force = false}) async {
    FocusScope.of(context).unfocus();
    final key = _key.text.trim();
    final oldBase = Settings.i.baseUrl(p.id);
    if (p.needsAddress) {
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
    for (final e in _params.entries) {
      Settings.i.setParam(p.id, e.key, e.value.text.trim());
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    final old = Settings.i.keys[p.id];
    await Settings.i.setKey(p.id, key);
    try {
      await _check();
    } on AiError catch (e) {
      if (!force) {
        await Settings.i.setKey(p.id, old);
        if (p.needsAddress) Settings.i.setBaseUrl(p.id, oldBase);
      }
      setState(() => _error = e.message);
      HapticFeedback.heavyImpact();
    }
    if (mounted) setState(() => _busy = false);
  }

  Future<void> _signIn() async {
    FocusScope.of(context).unfocus();
    final s = SignIn(p)..onCode = () => mounted ? setState(() {}) : null;
    setState(() {
      _signin = s;
      _error = null;
    });
    try {
      final account = await s.run();
      if (account == null || !mounted) return; // cancelled
      setState(() => _busy = true);
      try {
        await _check();
      } on AiError catch (e) {
        // signed in, but the model list failed: keep the sign-in and say why
        if (mounted) setState(() => _error = e.message);
      }
    } on AiError catch (e) {
      HapticFeedback.heavyImpact();
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) {
        setState(() {
          _signin = null;
          _busy = false;
        });
      }
    }
  }

  Future<void> _remove() async {
    if (p.loginOnly) {
      await Settings.i.setAuth(p.id, null);
    } else {
      await Settings.i.setKey(p.id, null);
      if (p.needsAddress) Settings.i.setBaseUrl(p.id, null);
      _key.clear();
      _base.clear();
    }
    setState(() {
      _count = null;
      _error = null;
    });
    if (mounted) showToast(context, p.loginOnly ? 'Signed out of ${p.name}' : '${p.name} removed');
  }

  String get _signInLabel => switch (p.login) {
    'chatgpt' => 'Sign in with ChatGPT',
    'copilot' => 'Sign in with GitHub',
    _ => 'Sign in with ${p.name}',
  };

  String get _signInText => switch (p.login) {
    'chatgpt' => 'Chat on your ChatGPT Plus, Pro or Team plan. No API key and no extra cost.',
    'copilot' => 'Sign in with the GitHub account that has Copilot, and chat on your Copilot plan.',
    _ => 'Sign in and ${p.name} makes a key for AFH by itself.',
  };

  Widget _field(String label, TextEditingController c, {String hint = '', TextInputType? type}) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      SectionLabel(label),
      TextField(
        controller: c,
        keyboardType: type,
        autocorrect: false,
        enableSuggestions: false,
        style: TextStyle(fontFamily: Afh.mono, fontSize: 14, color: Afh.text),
        decoration: InputDecoration(hintText: hint),
      ),
    ],
  );

  Widget _signInBox() {
    final s = _signin;
    if (s == null) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(4, 18, 4, 12),
            child: Text(_signInText, style: TextStyle(color: Afh.text2, fontSize: 13.5, height: 1.45)),
          ),
          PrimaryButton(label: _signInLabel, icon: LucideIcons.logIn, busy: _busy, onTap: _signIn),
        ],
      );
    }
    final code = s.code;
    return Container(
      margin: const EdgeInsets.only(top: 18),
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
      decoration: BoxDecoration(color: Afh.surface, borderRadius: BorderRadius.circular(Afh.r), border: Border.all(color: Afh.line)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (p.login == 'copilot' && code == null)
            Row(
              children: [
                SizedBox.square(dimension: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Afh.accent)),
                const SizedBox(width: 12),
                Text('Asking GitHub for a code…', style: TextStyle(color: Afh.text2, fontSize: 14)),
              ],
            )
          else if (code != null) ...[
            Text('Enter this code on GitHub', style: TextStyle(color: Afh.text2, fontSize: 13.5)),
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(
                  child: SelectableText(
                    code,
                    style: TextStyle(fontFamily: Afh.mono, fontSize: 26, fontWeight: FontWeight.w600, letterSpacing: 2, color: Afh.text),
                  ),
                ),
                IconBtn(
                  LucideIcons.copy,
                  tooltip: 'Copy',
                  onTap: () {
                    Clipboard.setData(ClipboardData(text: code));
                    showToast(context, 'Code copied');
                  },
                ),
              ],
            ),
            const SizedBox(height: 12),
            PrimaryButton(
              label: 'Copy code and open GitHub',
              icon: LucideIcons.externalLink,
              onTap: () {
                Clipboard.setData(ClipboardData(text: code));
                launchUrl(Uri.parse(s.codeUrl ?? 'https://github.com/login/device'), mode: LaunchMode.externalApplication);
              },
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                SizedBox.square(dimension: 14, child: CircularProgressIndicator(strokeWidth: 2, color: Afh.text3)),
                const SizedBox(width: 10),
                Expanded(child: Text('Waiting for you to approve AFH on GitHub…', style: TextStyle(color: Afh.text3, fontSize: 13))),
              ],
            ),
          ] else
            Row(
              children: [
                SizedBox.square(dimension: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Afh.accent)),
                const SizedBox(width: 12),
                Expanded(
                  child: Text('Finish signing in in the browser, then come back here.', style: TextStyle(color: Afh.text2, fontSize: 14, height: 1.4)),
                ),
              ],
            ),
          Align(
            alignment: Alignment.centerRight,
            child: TextButton(
              onPressed: () {
                s.cancel();
                setState(() => _signin = null);
              },
              style: TextButton.styleFrom(foregroundColor: Afh.text2),
              child: const Text('Cancel', style: TextStyle(fontWeight: FontWeight.w600)),
            ),
          ),
        ],
      ),
    ).animate().fadeIn(duration: Afh.fast);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(p.name)),
      body: ListenableBuilder(
        listenable: Settings.i,
        builder: (context, _) {
          final ready = p.ready;
          final account = Settings.i.auth[p.id];
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
                                child: Text(p.name, maxLines: 2, overflow: TextOverflow.ellipsis, style: Afh.h3()),
                              ),
                              if (ready) ...[
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
              // sign-in
              if (p.login != null)
                if (p.loginOnly && account != null)
                  Container(
                    margin: const EdgeInsets.only(top: 18),
                    padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
                    decoration: BoxDecoration(color: Afh.surface, borderRadius: BorderRadius.circular(Afh.r), border: Border.all(color: Afh.line)),
                    child: Row(
                      children: [
                        Icon(LucideIcons.circleCheck, size: 20, color: Afh.good),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text('Signed in', style: TextStyle(color: Afh.text, fontWeight: FontWeight.w600, fontSize: 14.5)),
                              if ('${account['account'] ?? ''}'.isNotEmpty || '${account['plan'] ?? ''}'.isNotEmpty)
                                Text(
                                  [
                                    if ('${account['account'] ?? ''}'.isNotEmpty) account['account'],
                                    if ('${account['plan'] ?? ''}'.isNotEmpty) '${account['plan']} plan',
                                  ].join(' · '),
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: TextStyle(color: Afh.text3, fontSize: 13),
                                ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ).enter(1)
                else
                  _signInBox(),
              if (!p.loginOnly) ...[
                if (p.login != null) const SectionLabel('Or paste an API key', padding: EdgeInsets.fromLTRB(4, 26, 4, 0)),
                if (p.needsAddress) ...[
                  _field('Server address', _base, hint: p.custom || p.base.isEmpty ? 'http://192.168.1.20:11434/v1' : p.base.replaceFirst(RegExp(r'localhost|127\.0\.0\.1'), '192.168.1.20'), type: TextInputType.url),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(4, 8, 4, 0),
                    child: Text(
                      p.custom
                          ? 'Any server that speaks the OpenAI chat API: Ollama, LM Studio, vLLM, LiteLLM…'
                          : 'Use the address of the computer running it on your network, not localhost: the phone can\'t see the computer\'s localhost.',
                      style: TextStyle(color: Afh.text3, fontSize: 12.5, height: 1.4),
                    ),
                  ),
                ],
                for (final x in p.params) _field(x.label, _params[x.name]!),
                if (p.hint.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(4, 8, 4, 0),
                    child: Text(p.hint, style: TextStyle(color: Afh.text3, fontSize: 12.5, height: 1.4)),
                  ),
                SectionLabel(p.noKey ? 'API key (optional)' : 'API key'),
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
                if (p.keysUrl.isNotEmpty && !p.local)
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
                                p.keysUrl == p.docs ? '${p.name} docs' : 'Get a key from ${p.name}',
                                style: TextStyle(color: Afh.accent, fontWeight: FontWeight.w600, fontSize: 13.5),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
              ],
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
                                  if (!p.loginOnly && (_key.text.trim().isNotEmpty || p.needsAddress))
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
              if (!p.loginOnly) ...[
                const SizedBox(height: 20),
                p.login != null
                    ? SecondaryButton(label: ready ? 'Save and check again' : 'Connect with this key', icon: LucideIcons.zap, expand: true, onTap: _busy ? null : _save)
                    : PrimaryButton(label: ready ? 'Save and check again' : 'Connect', icon: LucideIcons.zap, busy: _busy, onTap: _save),
              ] else if (ready) ...[
                const SizedBox(height: 14),
                SecondaryButton(
                  label: 'Check the models again',
                  icon: LucideIcons.refreshCw,
                  expand: true,
                  onTap: _busy
                      ? null
                      : () async {
                          setState(() {
                            _busy = true;
                            _error = null;
                          });
                          try {
                            await _check();
                          } on AiError catch (e) {
                            if (mounted) setState(() => _error = e.message);
                          }
                          if (mounted) setState(() => _busy = false);
                        },
                ),
              ],
              if (showModels) ...[
                SectionLabel(
                  '${_count ?? models.length} model${(_count ?? models.length) == 1 ? '' : 's'} available',
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
                SecondaryButton(
                  label: p.loginOnly ? 'Sign out' : 'Remove this provider',
                  icon: p.loginOnly ? LucideIcons.logOut : LucideIcons.trash2,
                  danger: true,
                  expand: true,
                  onTap: _remove,
                ),
              ],
            ],
          );
        },
      ),
    );
  }
}
