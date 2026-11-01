// Sign in to a provider instead of pasting an API key, the same three ways as the desktop app
// (afh/engine/auth.py):
//
//   openrouter  browser (OAuth PKCE); OpenRouter hands back an ordinary API key
//   chatgpt     browser (OAuth PKCE, the Codex CLI client); a ChatGPT plan pays for the tokens,
//               requests go to the Codex backend's Responses API
//   copilot     GitHub device code; the GitHub token buys short-lived Copilot tokens
//
// The browser ones redirect to http://localhost:<port>/…, so the app listens on the phone's own
// loopback while the sign-in page is open. Tokens live in the keystore (Settings.auth).
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;
import 'package:url_launcher/url_launcher.dart';

import 'ai.dart';
import 'store.dart';

const _chatgptClient = 'app_EMoamEEZ73f0CkXaXp7hrann';
const _chatgptAuth = 'https://auth.openai.com/oauth/authorize';
const _chatgptToken = 'https://auth.openai.com/oauth/token';
const _chatgptPort = 1455; // the redirect URI registered for this client
const chatgptBase = 'https://chatgpt.com/backend-api/codex';

const _copilotClient = 'Iv1.b507a08c87ecfe98';
const copilotBase = 'https://api.githubcopilot.com';
const _copilotHeaders = {
  'editor-version': 'vscode/1.99.0',
  'editor-plugin-version': 'copilot-chat/0.26.0',
  'copilot-integration-id': 'vscode-chat',
  'user-agent': 'GitHubCopilotChat/0.26.0',
};

const _timeout = Duration(minutes: 10);

String _b64url(List<int> raw) => base64Url.encode(raw).replaceAll('=', '');

(String, String) _pkce() {
  final r = Random.secure();
  final verifier = _b64url(List.generate(32, (_) => r.nextInt(256)));
  return (verifier, _b64url(sha256.convert(ascii.encode(verifier)).bytes));
}

Map<String, dynamic> _claims(String token) {
  try {
    final part = token.split('.')[1];
    return jsonDecode(utf8.decode(base64Url.decode(base64Url.normalize(part)))) as Map<String, dynamic>;
  } catch (_) {
    return {};
  }
}

class _Cancelled implements Exception {}

/// One sign-in in progress. [code] is set for GitHub's device flow: the user types it on github.com.
class SignIn {
  SignIn(this.provider);
  final Provider provider;
  final _cancel = Completer<void>();
  String? code;
  String? codeUrl;
  void Function()? onCode;

  bool get cancelled => _cancel.isCompleted;
  void cancel() {
    if (!_cancel.isCompleted) _cancel.complete();
  }

  /// Runs the whole sign-in; returns the account it signed in to, or null when cancelled.
  Future<String?> run() async {
    try {
      return switch (provider.login) {
        'openrouter' => await _openrouter(),
        'chatgpt' => await _chatgpt(),
        'copilot' => await _copilot(),
        _ => throw AiError('${provider.name} has no sign-in.'),
      };
    } on _Cancelled {
      return null;
    } on AiError {
      rethrow;
    } on TimeoutException {
      throw AiError('The sign-in took too long. Try again.');
    } on SocketException {
      throw AiError('Couldn\'t reach ${provider.name}. Check your connection.');
    } on http.ClientException {
      throw AiError('Couldn\'t reach ${provider.name}. Check your connection.');
    }
  }

  Future<T> _wait<T>(Future<T> f) => Future.any([f, _cancel.future.then<T>((_) => throw _Cancelled())]).timeout(_timeout);

  Future<void> _open(Uri url) async {
    // an in-app browser: on iPhone it keeps the app awake to hear the redirect, and Google's sign-in
    // (used by many OpenAI accounts) refuses plain web views
    if (!await launchUrl(url, mode: LaunchMode.inAppBrowserView)) {
      await launchUrl(url, mode: LaunchMode.externalApplication);
    }
  }

  Future<String> _openrouter() async {
    final (verifier, challenge) = _pkce();
    final cb = await _Callback.open('/callback');
    final Map<String, String> query;
    try {
      await _open(
        Uri.https('openrouter.ai', '/auth', {
          'callback_url': 'http://localhost:${cb.port}/callback',
          'code_challenge': challenge,
          'code_challenge_method': 'S256',
        }),
      );
      query = await _wait(cb.result);
    } finally {
      await cb.close();
    }
    if (query['code'] == null) throw AiError(query['error_description'] ?? query['error'] ?? 'OpenRouter returned no code.');
    final res = await http
        .post(
          Uri.parse('https://openrouter.ai/api/v1/auth/keys'),
          headers: {'content-type': 'application/json'},
          body: jsonEncode({'code': query['code'], 'code_verifier': verifier, 'code_challenge_method': 'S256'}),
        )
        .timeout(const Duration(seconds: 30));
    if (res.statusCode >= 300) throw AiError('OpenRouter refused the sign-in (${res.statusCode}).');
    final key = (jsonDecode(res.body) as Map)['key'] as String?;
    if (key == null || key.isEmpty) throw AiError('OpenRouter returned no key.');
    await Settings.i.setKey(provider.id, key);
    return 'OpenRouter account';
  }

  Future<String> _chatgpt() async {
    final (verifier, challenge) = _pkce();
    final state = _b64url(List.generate(24, (_) => Random.secure().nextInt(256)));
    const redirect = 'http://localhost:$_chatgptPort/auth/callback';
    final cb = await _Callback.open('/auth/callback', port: _chatgptPort);
    final Map<String, String> query;
    try {
      await _open(
        Uri.parse(_chatgptAuth).replace(
          queryParameters: {
            'response_type': 'code',
            'client_id': _chatgptClient,
            'redirect_uri': redirect,
            'scope': 'openid profile email offline_access',
            'code_challenge': challenge,
            'code_challenge_method': 'S256',
            'id_token_add_organizations': 'true',
            'codex_cli_simplified_flow': 'true',
            'state': state,
            'originator': 'codex_cli_rs',
          },
        ),
      );
      query = await _wait(cb.result);
    } finally {
      await cb.close();
    }
    if (query['state'] != state) throw AiError('The sign-in answer did not match this request. Try again.');
    if (query['code'] == null) throw AiError(query['error_description'] ?? 'OpenAI returned no code.');
    final res = await http
        .post(
          Uri.parse(_chatgptToken),
          body: {
            'grant_type': 'authorization_code',
            'code': query['code']!,
            'redirect_uri': redirect,
            'client_id': _chatgptClient,
            'code_verifier': verifier,
          },
        )
        .timeout(const Duration(seconds: 30));
    if (res.statusCode >= 300) throw AiError('OpenAI refused the sign-in (${res.statusCode}).');
    final auth = _chatgptTokens(jsonDecode(res.body) as Map<String, dynamic>, const {});
    if ((auth['account_id'] as String).isEmpty) throw AiError('This OpenAI account has no ChatGPT plan attached.');
    await Settings.i.setAuth(provider.id, auth);
    return auth['account'] as String;
  }

  Future<String> _copilot() async {
    final c = http.Client();
    try {
      final res = await c
          .post(
            Uri.parse('https://github.com/login/device/code'),
            headers: {'accept': 'application/json', 'content-type': 'application/json'},
            body: jsonEncode({'client_id': _copilotClient, 'scope': 'read:user'}),
          )
          .timeout(const Duration(seconds: 30));
      if (res.statusCode >= 300) throw AiError('GitHub refused the sign-in (${res.statusCode}).');
      final dev = jsonDecode(res.body) as Map<String, dynamic>;
      code = dev['user_code'] as String? ?? '';
      codeUrl = dev['verification_uri'] as String? ?? 'https://github.com/login/device';
      onCode?.call();
      var interval = (dev['interval'] as num?)?.toInt() ?? 5;
      final deadline = DateTime.now().add(_timeout);
      String gh;
      while (true) {
        await _wait(Future<void>.delayed(Duration(seconds: interval)));
        if (DateTime.now().isAfter(deadline)) throw TimeoutException('device code');
        final r = await c.post(
          Uri.parse('https://github.com/login/oauth/access_token'),
          headers: {'accept': 'application/json', 'content-type': 'application/json'},
          body: jsonEncode({
            'client_id': _copilotClient,
            'device_code': dev['device_code'],
            'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
          }),
        );
        final data = r.body.isEmpty ? <String, dynamic>{} : jsonDecode(r.body) as Map<String, dynamic>;
        if (data['access_token'] != null) {
          gh = data['access_token'] as String;
          break;
        }
        final err = data['error'];
        if (err == 'slow_down') {
          interval += 5;
        } else if (err != 'authorization_pending') {
          throw AiError(data['error_description'] as String? ?? '$err');
        }
      }
      final user = await c.get(Uri.parse('https://api.github.com/user'), headers: {'authorization': 'token $gh'});
      final login = user.statusCode < 300 ? ((jsonDecode(user.body) as Map)['login'] as String? ?? '') : '';
      // fails here, not on the first message, when the account has no Copilot
      final auth = await _copilotToken({'type': 'copilot', 'github': gh, 'account': login});
      await Settings.i.setAuth(provider.id, auth);
      return login;
    } finally {
      c.close();
    }
  }
}

Map<String, dynamic> _chatgptTokens(Map<String, dynamic> tokens, Map<String, dynamic> old) {
  var claims = _claims(tokens['id_token'] as String? ?? '');
  if (claims.isEmpty) claims = _claims(tokens['access_token'] as String? ?? '');
  final info = claims['https://api.openai.com/auth'] as Map? ?? {};
  return {
    'type': 'chatgpt',
    'access': tokens['access_token'] ?? old['access'] ?? '',
    'refresh': tokens['refresh_token'] ?? old['refresh'] ?? '',
    'id_token': tokens['id_token'] ?? old['id_token'] ?? '',
    'expires': DateTime.now().millisecondsSinceEpoch / 1000 + ((tokens['expires_in'] as num?) ?? 3600),
    'account_id': info['chatgpt_account_id'] ?? old['account_id'] ?? '',
    'plan': info['chatgpt_plan_type'] ?? old['plan'] ?? '',
    'account': claims['email'] ?? old['account'] ?? '',
  };
}

Future<Map<String, dynamic>> _copilotToken(Map<String, dynamic> auth) async {
  final res = await http
      .get(
        Uri.parse('https://api.github.com/copilot_internal/v2/token'),
        headers: {'authorization': 'token ${auth['github']}', 'accept': 'application/json', ..._copilotHeaders},
      )
      .timeout(const Duration(seconds: 30));
  if (res.statusCode == 401) throw AiError('GitHub sign-in expired. Sign in to Copilot again in Settings → Providers.');
  if (res.statusCode >= 300) throw AiError('This GitHub account has no Copilot access (${res.statusCode}).');
  final data = jsonDecode(res.body) as Map<String, dynamic>;
  final api = ((data['endpoints'] as Map?)?['api'] as String? ?? copilotBase).replaceAll(RegExp(r'/+$'), '');
  return {
    ...auth,
    'access': data['token'] ?? '',
    'expires': (data['expires_at'] as num?)?.toDouble() ?? DateTime.now().millisecondsSinceEpoch / 1000 + 1500,
    'api': api,
  };
}

final _refreshing = <String, Future<Map<String, dynamic>>>{};

Future<Map<String, dynamic>> _refresh(Provider p, Map<String, dynamic> auth) async {
  if (auth['type'] == 'chatgpt') {
    final res = await http
        .post(
          Uri.parse(_chatgptToken),
          headers: {'content-type': 'application/json'},
          body: jsonEncode({
            'client_id': _chatgptClient,
            'grant_type': 'refresh_token',
            'refresh_token': auth['refresh'] ?? '',
            'scope': 'openid profile email',
          }),
        )
        .timeout(const Duration(seconds: 30));
    if (res.statusCode >= 300) throw AiError('ChatGPT sign-in expired. Sign in again in Settings → Providers.');
    return _chatgptTokens(jsonDecode(res.body) as Map<String, dynamic>, auth);
  }
  return _copilotToken(auth);
}

/// Address and headers for a signed-in provider; refreshes a token that is about to expire.
/// [force] refreshes anyway: the server just said 401 to a token we thought was fine.
Future<(String, Map<String, String>)> signedRequest(Provider p, {bool force = false}) async {
  var auth = Settings.i.auth[p.id];
  if (auth == null) throw AiError('Sign in to ${p.name} first in Settings → Providers.');
  final now = DateTime.now().millisecondsSinceEpoch / 1000;
  if (force || (auth['access'] as String? ?? '').isEmpty || ((auth['expires'] as num?) ?? 0) < now + 120) {
    final pending = _refreshing[p.id] ??= _refresh(p, auth).whenComplete(() => _refreshing.remove(p.id));
    auth = await pending;
    await Settings.i.setAuth(p.id, auth, quiet: true);
  }
  final base = {'content-type': 'application/json', 'authorization': 'Bearer ${auth['access']}'};
  if (auth['type'] == 'chatgpt') {
    return (
      chatgptBase,
      {...base, 'chatgpt-account-id': '${auth['account_id']}', 'openai-beta': 'responses=experimental', 'originator': 'codex_cli_rs'},
    );
  }
  return ((auth['api'] as String?) ?? copilotBase, {...base, 'openai-intent': 'conversation-edits', ..._copilotHeaders});
}

/// The phone's own loopback, waiting for the sign-in page to redirect back with a code.
class _Callback {
  _Callback._(this.path, this.servers);
  final String path;
  final List<HttpServer> servers;
  final _result = Completer<Map<String, String>>();
  Future<Map<String, String>> get result => _result.future;
  int get port => servers.first.port;

  static Future<_Callback> open(String path, {int port = 0}) async {
    final HttpServer v4;
    try {
      v4 = await HttpServer.bind(InternetAddress.loopbackIPv4, port);
    } on SocketException {
      throw AiError('Port $port is busy on this phone. Close other apps signing in and try again.');
    }
    final servers = [v4];
    try {
      servers.add(await HttpServer.bind(InternetAddress.loopbackIPv6, v4.port, v6Only: true)); // "localhost" may be ::1
    } catch (_) {}
    final cb = _Callback._(path, servers);
    for (final s in servers) {
      s.listen(cb._handle, onError: (_) {});
    }
    return cb;
  }

  Future<void> _handle(HttpRequest req) async {
    final res = req.response;
    if (req.uri.path != path) {
      res.statusCode = 404;
      await res.close();
      return;
    }
    final q = req.uri.queryParameters;
    final ok = q['code'] != null;
    final text = ok ? 'You\'re signed in. Go back to AFH.' : (q['error_description'] ?? q['error'] ?? 'No code was returned.');
    final back = Platform.isAndroid ? '<p><a class="b" href="intent:#Intent;action=android.intent.action.MAIN;category=android.intent.category.LAUNCHER;package=com.agentflowharness.app;end">Back to AFH</a></p>' : '';
    res.headers.contentType = ContentType.html;
    res.write(
      '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AFH</title>'
      '<style>body{font:17px/1.5 system-ui,sans-serif;background:#0e0d0d;color:#eee;display:grid;place-items:center;min-height:90vh;margin:0;text-align:center;padding:24px}'
      'h1{font-size:22px;margin:0 0 8px}.b{display:inline-block;margin-top:14px;padding:12px 22px;border-radius:999px;background:#f2a65a;color:#111;text-decoration:none;font-weight:600}</style>'
      '<div><h1>${ok ? 'Signed in' : 'Sign-in failed'}</h1><p>${const HtmlEscape().convert(text)}</p>$back</div>',
    );
    await res.close();
    if (!_result.isCompleted) _result.complete(Map.of(q));
    unawaited(closeInAppWebView().catchError((_) {})); // iPhone: closes the sign-in sheet
  }

  Future<void> close() async {
    for (final s in servers) {
      await s.close(force: true);
    }
  }
}
