// Model providers for chats on the phone: sign in or paste a key; the models it can use are fetched at
// once. Keys stay in the phone's secure storage and chats go straight to the provider.
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/ai.dart';
import '../core/l10n.dart';
import '../core/signin.dart';
import '../core/store.dart';
import '../ui/badge.dart';
import '../ui/kit.dart';
import '../ui/look.dart';
import '../ui/motion.dart';

class ProvidersScreen extends StatefulWidget {
  const ProvidersScreen({super.key});
  @override
  State<ProvidersScreen> createState() => _ProvidersScreenState();
}

class _ProvidersScreenState extends State<ProvidersScreen> {
  final _q = TextEditingController();
  bool _all = false;

  @override
  void dispose() {
    _q.dispose();
    super.dispose();
  }

  Widget _tile(Provider p) => Tile(
    p.name.startsWith('ChatGPT (') ? 'ChatGPT' : p.name,
    sub: p.ready ? connectedText(p) : p.blurb,
    subMax: 2,
    titleMax: 2,
    lead: LogoBox(p.id, name: p.name),
    trail: p.ready ? Dot(context.p.good) : (p.login != null ? Pill(t('Sign in'), dense: true) : null),
    arrow: true,
    onTap: () => go(context, ProviderScreen(p)),
  );

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: Settings.i,
    builder: (context, _) {
      final q = _q.text.trim().toLowerCase();
      final found = [for (final p in providers) if ('${p.name} ${p.id}'.toLowerCase().contains(q)) p];
      final ready = [for (final p in providers) if (p.ready) p];
      int rank(Provider p) => p.id == 'chatgpt' ? 3 : (p.id == 'openrouter' ? 2 : (p.login != null ? 1 : 0));
      final popular = [for (final p in providers) if (p.featured && !p.ready) p]..sort((a, b) => rank(b) - rank(a));
      final more = [for (final p in providers) if (!p.featured && !p.ready) p];
      return AppPage(
        title: t('Models'),
        sub: t('Sign in or paste a key. Keys stay on this phone and chats go straight to the provider.'),
        slivers: [
          pad([
            Field(_q, hint: t('Search providers'), icon: LucideIcons.search, onChanged: (_) => setState(() {})),
            if (q.isNotEmpty) ...[
              if (found.isEmpty)
                Empty(LucideIcons.searchX, t('Nothing found'), t('Any server that speaks the OpenAI API works as a Custom server.'))
              else ...[
                const SizedBox(height: 16),
                Group(children: [for (final p in found.take(40)) _tile(p)]),
              ],
            ] else ...[
              if (ready.isNotEmpty) Group(title: t('Connected'), children: [for (final p in ready) _tile(p)]),
              Group(title: t('Popular'), children: [for (final p in popular) _tile(p)]),
              if (_all)
                Group(title: t('More'), children: [for (final p in more) _tile(p)])
              else ...[
                const SizedBox(height: 16),
                Btn(t('Show every provider'), kind: Kind.soft, onTap: () => setState(() => _all = true)),
              ],
            ],
          ]),
        ],
      );
    },
  );
}

String connectedText(Provider p) {
  final account = p.loginOnly ? '${Settings.i.auth[p.id]?['account'] ?? ''}' : '';
  final n = (Settings.i.models[p.id] ?? const []).length;
  final parts = [if (account.isNotEmpty) account, if (n > 0) n == 1 ? t('1 model') : t('{} models', n)];
  return parts.isEmpty ? t('Connected') : parts.join(' · ');
}

class ProviderScreen extends StatefulWidget {
  const ProviderScreen(this.p, {super.key});
  final Provider p;
  @override
  State<ProviderScreen> createState() => _ProviderScreenState();
}

class _ProviderScreenState extends State<ProviderScreen> {
  Provider get p => widget.p;
  late final _key = TextEditingController(text: Settings.i.keys[p.id] ?? '');
  late final _base = TextEditingController(text: Settings.i.baseUrl(p.id) ?? '');
  late final _params = {for (final x in p.params) x.name: TextEditingController(text: Settings.i.param(p.id, x.name) ?? x.fallback)};
  bool _hide = true, _busy = false, _every = false;
  String? _error;
  SignIn? _signin;

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
    Settings.i.lastModel ??= models.isEmpty ? null : '${p.id}/${models.first}';
    Tap.mid();
    if (mounted) toast(context, t('{} is connected', p.name));
  }

  Future<void> _save({bool force = false}) async {
    FocusScope.of(context).unfocus();
    final key = _key.text.trim();
    final oldBase = Settings.i.baseUrl(p.id), old = Settings.i.keys[p.id];
    if (p.needsAddress) {
      final url = _base.text.trim();
      if (!RegExp(r'^https?://').hasMatch(url)) return setState(() => _error = t('Enter the server address, starting with http:// or https://'));
      Settings.i.setBaseUrl(p.id, url);
    } else if (key.isEmpty) {
      return setState(() => _error = t('Paste your API key first.'));
    }
    for (final e in _params.entries) {
      Settings.i.setParam(p.id, e.key, e.value.text.trim());
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    await Settings.i.setKey(p.id, key);
    try {
      await _check();
    } on AiError catch (e) {
      if (!force) {
        await Settings.i.setKey(p.id, old);
        if (p.needsAddress) Settings.i.setBaseUrl(p.id, oldBase);
      }
      Tap.heavy();
      if (mounted) setState(() => _error = e.message);
    }
    if (mounted) setState(() => _busy = false);
  }

  Future<void> _refresh() async {
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
      if (account == null || !mounted) return;
      setState(() => _busy = true);
      await _check();
    } on AiError catch (e) {
      Tap.heavy();
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
    if (!await confirm(context, t('Disconnect {}?', p.name), t('Its key is removed from this phone. Your chats stay.'), t('Disconnect'), danger: true)) return;
    if (p.login != null) await Settings.i.setAuth(p.id, null);
    await Settings.i.setKey(p.id, null);
    if (p.needsAddress) Settings.i.setBaseUrl(p.id, null);
    _key.clear();
    _base.clear();
    if (mounted) setState(() => _error = null);
  }

  Widget _signing() {
    final s = _signin!;
    final pal = context.p;
    return Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (s.code != null) ...[
            Text(t('Enter this code on GitHub'), style: T.sub.copyWith(color: pal.text2)),
            const SizedBox(height: 10),
            Press(
              onTap: () => copyText(context, s.code!, t('Code copied')),
              child: Text(
                s.code!,
                textAlign: TextAlign.center,
                style: T.display.copyWith(fontFamily: mono, color: pal.text, letterSpacing: 3),
              ),
            ),
            const SizedBox(height: 16),
            Btn(
              t('Copy code and open GitHub'),
              icon: LucideIcons.externalLink,
              onTap: () {
                Clipboard.setData(ClipboardData(text: s.code!));
                launchUrl(Uri.parse(s.codeUrl ?? 'https://github.com/login/device'), mode: LaunchMode.externalApplication);
              },
            ),
            const SizedBox(height: 14),
          ],
          Row(
            children: [
              const Pulse(),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  s.code != null ? t('Waiting for you to approve AFH on GitHub…') : (p.login == 'copilot' ? t('Asking GitHub for a code…') : t('Finish signing in in the browser, then come back here.')),
                  style: T.sub.copyWith(color: pal.text2),
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          Btn(
            t('Cancel'),
            kind: Kind.soft,
            onTap: () {
              s.cancel();
              setState(() => _signin = null);
            },
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: Settings.i,
    builder: (context, _) {
      final pal = context.p;
      final account = Settings.i.auth[p.id];
      final models = Settings.i.models[p.id] ?? const <String>[];
      return AppPage(
        title: p.name,
        sub: p.ready ? connectedText(p) : p.blurb,
        actions: [Logo(p.id, name: p.name, size: 22), const SizedBox(width: 10)],
        slivers: [
          pad([
            if (p.login != null && _signin != null)
              _signing()
            else if (p.login != null && !(p.loginOnly && account != null)) ...[
              Text(
                switch (p.login) {
                  'chatgpt' => t('Chat on your ChatGPT plan. No API key and no extra cost.'),
                  'copilot' => t('Sign in with the GitHub account that has Copilot, and chat on that plan.'),
                  _ => t('Sign in and {} makes a key for AFH by itself.', p.name),
                },
                style: T.sub.copyWith(color: pal.text2),
              ),
              const SizedBox(height: 14),
              Btn(
                switch (p.login) {
                  'chatgpt' => t('Sign in with ChatGPT'),
                  'copilot' => t('Sign in with GitHub'),
                  _ => t('Sign in with {}', p.name),
                },
                icon: LucideIcons.logIn,
                busy: _busy,
                onTap: _signIn,
              ),
            ] else if (p.loginOnly && account != null)
              Group(
                children: [
                  Tile(
                    t('Signed in'),
                    sub: [if ('${account['account'] ?? ''}'.isNotEmpty) account['account'], if ('${account['plan'] ?? ''}'.isNotEmpty) '${account['plan']}'].join(' · '),
                    icon: LucideIcons.circleCheck,
                    color: pal.good,
                  ),
                ],
              ),
            if (!p.loginOnly && _signin == null) ...[
              if (p.login != null) Head(t('Or paste an API key')),
              if (p.needsAddress) ...[
                Field(
                  _base,
                  label: t('Server address'),
                  code: true,
                  type: TextInputType.url,
                  hint: p.custom || p.base.isEmpty ? 'http://192.168.1.20:11434/v1' : p.base.replaceFirst(RegExp(r'localhost|127\.0\.0\.1'), '192.168.1.20'),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(4, 8, 4, 16),
                  child: Text(
                    p.custom
                        ? t('Any server that speaks the OpenAI chat API: Ollama, LM Studio, vLLM, LiteLLM…')
                        : t('Use the address of the computer running it on your network, not localhost.'),
                    style: T.small.copyWith(color: pal.text3),
                  ),
                ),
              ],
              for (final x in p.params) ...[Field(_params[x.name]!, label: x.label, code: true), const SizedBox(height: 14)],
              if (p.hint.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.fromLTRB(4, 0, 4, 14),
                  child: Text(p.hint, style: T.small.copyWith(color: pal.text3)),
                ),
              Field(
                _key,
                label: p.noKey ? t('API key (optional)') : t('API key'),
                hint: p.keyHint,
                secret: _hide,
                code: true,
                trail: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Ic(
                      LucideIcons.clipboardPaste,
                      icon_: 17,
                      color: pal.text2,
                      tip: t('Paste'),
                      onTap: () async {
                        final d = await Clipboard.getData(Clipboard.kTextPlain);
                        if (d?.text != null) setState(() => _key.text = d!.text!.trim());
                      },
                    ),
                    Ic(_hide ? LucideIcons.eye : LucideIcons.eyeOff, icon_: 17, color: pal.text2, tip: t('Show'), onTap: () => setState(() => _hide = !_hide)),
                  ],
                ),
              ),
              if (p.keysUrl.isNotEmpty && !p.local)
                Press(
                  onTap: () => launchUrl(Uri.parse(p.keysUrl), mode: LaunchMode.externalApplication),
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(4, 12, 4, 4),
                    child: Row(
                      children: [
                        Icon(LucideIcons.externalLink, size: 15, color: pal.accent),
                        const SizedBox(width: 7),
                        Flexible(
                          child: Text(
                            p.keysUrl == p.docs ? t('{} docs', p.name) : t('Get a key from {}', p.name),
                            style: T.label.copyWith(color: pal.accent),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
            ],
            Fold(
              open: _error != null,
              child: Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Note(
                  _error ?? '',
                  icon: LucideIcons.circleAlert,
                  color: pal.bad,
                  action: !p.loginOnly && (_key.text.trim().isNotEmpty || p.needsAddress) ? t('Save anyway') : null,
                  onTap: () => _save(force: true),
                ),
              ),
            ),
            if (!p.loginOnly && _signin == null) ...[
              const SizedBox(height: 18),
              Btn(p.ready ? t('Save and check again') : t('Connect'), kind: p.login != null ? Kind.soft : Kind.main, busy: _busy, onTap: _save),
            ] else if (p.ready && _signin == null) ...[
              const SizedBox(height: 14),
              Btn(t('Check the models again'), kind: Kind.soft, busy: _busy, onTap: _refresh),
            ],
            if (p.ready && models.isNotEmpty) ...[
              Group(
                title: t('What you can use'),
                trailing: models.length > 6
                    ? Press(
                        onTap: () => setState(() => _every = !_every),
                        child: Text(_every ? t('Less') : t('All {}', models.length), style: T.label.copyWith(color: pal.accent)),
                      )
                    : null,
                children: [
                  for (final m in _every ? models : models.take(6)) Tile(prettyModel(m), sub: m, subMax: 1, lead: LogoBox(p.id, name: p.name, model: m, size: 32)),
                ],
              ),
            ],
            if (p.ready) ...[
              const SizedBox(height: 22),
              Btn(p.loginOnly ? t('Sign out') : t('Disconnect'), kind: Kind.danger, onTap: _remove),
            ],
          ]),
        ],
      );
    },
  );
}
