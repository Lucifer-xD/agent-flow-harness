// Direct chat: the phone talks to the model provider itself with the user's own key or sign-in.
// The provider list is the desktop's (assets/providers.json, written by scripts/app-providers.py);
// four wire formats cover everyone: OpenAI-compatible chat completions, OpenAI Responses (ChatGPT
// sign-in), Anthropic messages and Gemini.
import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

import 'signin.dart';
import 'store.dart';

enum Wire { openai, anthropic, gemini, responses }

/// A field the provider's address is built from, like Azure's resource name.
class Param {
  const Param(this.name, this.label, this.fallback);
  final String name, label, fallback;
}

class Provider {
  Provider({
    required this.id,
    required this.name,
    required this.wire,
    required this.base,
    this.docs = '',
    this.featured = false,
    this.fallback = const [],
    this.login,
    this.loginOnly = false,
    this.noKey = false,
    this.local = false,
    this.noFetch = false,
    this.params = const [],
    this.hint = '',
    this.headers = const {},
    this.authHeader = 'authorization',
    this.authPrefix = 'Bearer ',
  });

  factory Provider.fromJson(Map<String, dynamic> j) => Provider(
    id: j['id'] as String,
    name: j['name'] as String,
    wire: Wire.values.byName(j['wire'] as String),
    base: j['base'] as String? ?? '',
    docs: j['docs'] as String? ?? '',
    featured: j['featured'] == true,
    fallback: List<String>.from(j['models'] as List? ?? const []),
    login: j['login'] as String?,
    loginOnly: j['loginOnly'] == true,
    noKey: j['noKey'] == true,
    local: j['local'] == true,
    noFetch: j['noFetch'] == true,
    params: [for (final p in (j['params'] as List? ?? const [])) Param(p['name'] as String, p['label'] as String, p['default'] as String? ?? '')],
    hint: j['hint'] as String? ?? '',
    headers: Map<String, String>.from(j['headers'] as Map? ?? const {}),
    authHeader: (j['authHeader'] as String? ?? 'authorization').toLowerCase(),
    authPrefix: j['authPrefix'] as String? ?? 'Bearer ',
  );

  final String id;
  final String name;
  final Wire wire;
  final String base;
  final String docs;
  final bool featured;
  final List<String> fallback; // shown before the model list has been fetched
  final String? login; // 'chatgpt' | 'copilot' | 'openrouter': sign in with the browser
  final bool loginOnly; // a subscription pays, there's no key to paste
  final bool noKey; // local servers that take any key, or none
  final bool local; // the default address is the desktop's own machine: the phone needs a LAN address
  final bool noFetch; // no usable /models: the built-in list is the list
  final List<Param> params;
  final String hint;
  final Map<String, String> headers;
  final String authHeader, authPrefix;

  _Look get _look => _looks[id] ?? _Look(_hashColor(id), _defaultBlurb);
  Color get color => _look.color;
  String get blurb => _look.blurb;
  String get keysUrl => _look.keys.isNotEmpty ? _look.keys : docs;
  String get keyHint => _look.keyHint;
  String get _defaultBlurb => switch (wire) {
    Wire.anthropic => 'Anthropic-compatible API',
    Wire.gemini => 'Gemini API',
    _ => local ? 'A server on your own network' : 'OpenAI-compatible API',
  };

  String get initials {
    final letters = name.replaceAll(RegExp(r'[^A-Za-z0-9]'), '');
    return letters.isEmpty ? '?' : letters.substring(0, 1).toUpperCase();
  }

  bool get custom => id == 'custom';
  bool get needsAddress => custom || local;
  bool get signedIn => Settings.i.auth[id] != null;

  /// Something the user set up: a key, a sign-in, or (for local servers) an address.
  bool get ready {
    if (loginOnly) return signedIn;
    if ((Settings.i.keys[id] ?? '').isNotEmpty) return true;
    return needsAddress && (Settings.i.baseUrl(id) ?? '').isNotEmpty;
  }

  /// The address requests go to: the user's own, or the built-in one with its fields filled in.
  String baseUrl() {
    var url = Settings.i.baseUrl(id) ?? (local ? '' : base);
    url = url.replaceAllMapped(RegExp(r'\$\{([A-Z0-9_]+)\}'), (m) {
      final p = params.where((p) => p.name == m[1]).firstOrNull;
      final v = Settings.i.param(id, m[1]!) ?? p?.fallback ?? '';
      return v.isEmpty ? m[0]! : v;
    });
    url = url.replaceAll(RegExp(r'/+$'), '');
    if (url.isEmpty) return url;
    // the desktop keeps the bare host for these two and adds the version per request
    if (wire == Wire.anthropic && !url.endsWith('/v1')) url = '$url/v1';
    if (wire == Wire.gemini && !RegExp(r'/v1(beta)?$').hasMatch(url)) url = '$url/v1beta';
    return url;
  }

  /// Fields still showing ${VAR}: the user hasn't filled them in.
  bool get missingParams => RegExp(r'\$\{').hasMatch(baseUrl());

  List<String> get models {
    final got = Settings.i.models[id];
    return got != null && got.isNotEmpty ? got : fallback;
  }
}

class _Look {
  const _Look(this.color, this.blurb, {this.keys = '', this.keyHint = ''});
  final Color color;
  final String blurb, keys, keyHint;
}

// Brand colours, blurbs and key pages for the providers people pick most.
const _looks = <String, _Look>{
  'openai': _Look(Color(0xFF10A37F), 'GPT models', keys: 'https://platform.openai.com/api-keys', keyHint: 'sk-…'),
  'anthropic': _Look(Color(0xFFD97757), 'Claude Opus, Sonnet and Haiku', keys: 'https://console.anthropic.com/settings/keys', keyHint: 'sk-ant-…'),
  'gemini': _Look(Color(0xFF4F8DF7), 'Gemini Pro and Flash', keys: 'https://aistudio.google.com/apikey', keyHint: 'AIza…'),
  'chatgpt': _Look(Color(0xFF10A37F), 'Use your ChatGPT Plus, Pro or Team plan'),
  'github-copilot': _Look(Color(0xFF8B949E), 'Use your GitHub Copilot plan'),
  'openrouter': _Look(Color(0xFF8B7CF6), 'Hundreds of models with one account', keys: 'https://openrouter.ai/keys', keyHint: 'sk-or-…'),
  'kimi': _Look(Color(0xFF3B82F6), 'Kimi coding plan', keys: 'https://platform.kimi.ai'),
  'moonshot': _Look(Color(0xFF6366F1), 'Kimi models', keys: 'https://platform.moonshot.ai/console/api-keys', keyHint: 'sk-…'),
  'zai': _Look(Color(0xFF2563EB), 'GLM models', keys: 'https://z.ai/manage-apikey/apikey-list'),
  'zai-coding': _Look(Color(0xFF1D4ED8), 'GLM coding plan', keys: 'https://z.ai/manage-apikey/apikey-list'),
  'deepseek': _Look(Color(0xFF4D6BFE), 'DeepSeek chat and reasoner', keys: 'https://platform.deepseek.com/api_keys', keyHint: 'sk-…'),
  'groq': _Look(Color(0xFFF55036), 'Very fast open models', keys: 'https://console.groq.com/keys', keyHint: 'gsk_…'),
  'mistral': _Look(Color(0xFFFF7000), 'Mistral Large, Medium and Codestral', keys: 'https://console.mistral.ai/api-keys'),
  'xai': _Look(Color(0xFFA3A3A3), 'Grok models', keys: 'https://console.x.ai', keyHint: 'xai-…'),
  'together': _Look(Color(0xFF0F6FFF), 'Open models in the cloud', keys: 'https://api.together.ai/settings/api-keys'),
  'fireworks': _Look(Color(0xFF7C3AED), 'Fast open models', keys: 'https://fireworks.ai/account/api-keys', keyHint: 'fw_…'),
  'cerebras': _Look(Color(0xFFF97316), 'The fastest open models', keys: 'https://cloud.cerebras.ai', keyHint: 'csk-…'),
  'perplexity': _Look(Color(0xFF20B8CD), 'Sonar models that search the web', keys: 'https://www.perplexity.ai/settings/api', keyHint: 'pplx-…'),
  'ollama': _Look(Color(0xFF9CA3AF), 'Ollama on a computer on your network'),
  'lmstudio': _Look(Color(0xFF6D28D9), 'LM Studio on a computer on your network'),
  'vllm': _Look(Color(0xFF0EA5E9), 'vLLM on a server you run'),
  'custom': _Look(Color(0xFFBDB0A5), 'Any other OpenAI-compatible server'),
};

Color _hashColor(String id) {
  var h = 0;
  for (final c in id.codeUnits) {
    h = (h * 31 + c) & 0x7fffffff;
  }
  return HSLColor.fromAHSL(1, (h % 360).toDouble(), 0.55, 0.55).toColor();
}

/// Every provider, in the desktop's order; filled by [loadProviders] before the app starts.
List<Provider> providers = [];

Future<void> loadProviders() async {
  final j = jsonDecode(await rootBundle.loadString('assets/providers.json')) as Map<String, dynamic>;
  final list = [for (final p in (j['providers'] as List)) Provider.fromJson(p as Map<String, dynamic>)];
  final cut = list.lastIndexWhere((p) => p.featured) + 1;
  list.insert(cut, Provider(id: 'custom', name: 'Custom server', wire: Wire.openai, base: '', featured: true, noKey: true));
  providers = list;
}

Provider providerById(String id) => providers.firstWhere((p) => p.id == id, orElse: () => providers.first);

class AiError implements Exception {
  AiError(this.message);
  final String message;
  @override
  String toString() => message;
}

/// One piece of a streamed reply.
class Delta {
  const Delta({this.text = '', this.reasoning = ''});
  final String text;
  final String reasoning;
}

/// Address and headers for one request; signed-in providers refresh their token first.
Future<(String, Map<String, String>)> _prepare(Provider p, {bool force = false}) async {
  if (p.loginOnly) return signedRequest(p, force: force);
  final key = Settings.i.keys[p.id] ?? '';
  final h = <String, String>{'content-type': 'application/json', ...p.headers};
  switch (p.wire) {
    case Wire.anthropic:
      h.addAll({'x-api-key': key, 'anthropic-version': '2023-06-01'});
    case Wire.gemini:
      h['x-goog-api-key'] = key;
    case Wire.openai || Wire.responses:
      if (key.isNotEmpty) h[p.authHeader] = '${p.authPrefix}$key';
      if (p.id == 'openrouter') h['HTTP-Referer'] = 'https://agentflowharness.com';
  }
  return (p.baseUrl(), h);
}

String _errorText(int status, String body) {
  try {
    final j = jsonDecode(body);
    final e = j is List ? j.first['error'] : (j['error'] ?? (j['response'] is Map ? j['response']['error'] : null));
    final m = e is Map ? (e['message'] ?? e['type']) : (e ?? j['message'] ?? j['detail']);
    if (m != null && '$m'.trim().isNotEmpty) return '$m';
  } catch (_) {}
  return switch (status) {
    401 || 403 => 'The provider refused the key. Check it in Settings → Providers.',
    404 => 'That model isn\'t available with this key.',
    429 => 'Rate limited or out of credit. Try again in a moment.',
    _ => 'The provider answered $status.',
  };
}

/// Fetches the models this key or sign-in can use.
Future<List<String>> fetchModels(Provider p) async {
  var (base, headers) = await _prepare(p);
  if (base.isEmpty) throw AiError('Enter the server address first.');
  if (p.missingParams) throw AiError('Fill in every field above first.');
  final Uri url = switch (p.wire) {
    Wire.gemini => Uri.parse('$base/models?pageSize=200'),
    Wire.anthropic => Uri.parse('$base/models?limit=100'),
    _ when p.id == 'chatgpt' => Uri.parse('$base/models?client_version=99.0.0'),
    _ => Uri.parse('$base/models'),
  };
  http.Response res;
  try {
    res = await http.get(url, headers: {...headers, 'accept': 'application/json'}).timeout(const Duration(seconds: 20));
    if (res.statusCode == 401 && p.signedIn) {
      (base, headers) = await _prepare(p, force: true);
      res = await http.get(url, headers: {...headers, 'accept': 'application/json'}).timeout(const Duration(seconds: 20));
    }
  } on AiError {
    rethrow;
  } on TimeoutException {
    throw AiError('The provider didn\'t answer in time.');
  } catch (_) {
    throw AiError('Couldn\'t reach ${p.name}. Check your connection.');
  }
  // no model list at this address (coding plans, some gateways): the key worked, use the built-in list
  if ((res.statusCode == 404 || res.statusCode == 405 || p.noFetch) && res.statusCode != 401 && res.statusCode != 403 && p.fallback.isNotEmpty) {
    return p.fallback;
  }
  if (res.statusCode != 200) throw AiError(_errorText(res.statusCode, res.body));
  final j = jsonDecode(utf8.decode(res.bodyBytes));
  List<String> ids;
  if (p.wire == Wire.gemini) {
    ids = [
      for (final m in (j['models'] as List? ?? []))
        if ((m['supportedGenerationMethods'] as List? ?? []).contains('generateContent')) (m['name'] as String).replaceFirst('models/', ''),
    ];
    ids.removeWhere((id) => RegExp(r'embedding|aqa|imagen|tts|image-generation|learnlm').hasMatch(id));
  } else if (p.id == 'chatgpt') {
    ids = [
      for (final m in (j['models'] as List? ?? []))
        if (m is Map && m['slug'] != null && m['visibility'] != 'hide' && m['supported_in_api'] != false) m['slug'] as String,
    ];
    if (ids.isEmpty) throw AiError('ChatGPT listed no models for this plan.');
    return ids; // already in ChatGPT's own order
  } else {
    final items = j is List ? j : (j['data'] as List? ?? []);
    ids = [];
    for (final m in items) {
      if (m is String) {
        ids.add(m);
        continue;
      }
      if (m is! Map || m['id'] == null) continue;
      final caps = m['capabilities'];
      if (caps is Map) {
        // GitHub Copilot: only the chat models this account may pick
        if ((caps['type'] ?? 'chat') != 'chat' || m['model_picker_enabled'] == false || (m['policy'] is Map && m['policy']['state'] == 'disabled')) continue;
      }
      ids.add(m['id'] as String);
    }
    if (p.id == 'openai') {
      ids.removeWhere(
        (id) =>
            !RegExp(r'^(gpt|o\d|chatgpt)').hasMatch(id) ||
            RegExp(r'audio|realtime|tts|transcribe|image|search|instruct|embedding|moderation|codex').hasMatch(id) ||
            RegExp(r'-\d{4}-\d{2}-\d{2}$').hasMatch(id),
      );
    }
    ids.removeWhere((id) => RegExp(r'embed|whisper|tts|moderation|guard|dall-e|rerank').hasMatch(id));
    ids = ids.toSet().toList();
  }
  if (ids.isEmpty && p.fallback.isNotEmpty) return p.fallback;
  if (p.id != 'openrouter' && p.id != 'github-copilot' && p.wire != Wire.anthropic) ids.sort((a, b) => b.compareTo(a));
  return ids;
}

/// A reply being streamed. Call [cancel] to stop it.
class Run {
  Run(this.provider, this.model, this.history, {this.system = ''});
  final Provider provider;
  final String model;
  final List<Msg> history; // already ends with the user's message
  final String system;
  final _client = http.Client();
  bool _cancelled = false;
  bool get cancelled => _cancelled;

  void cancel() {
    _cancelled = true;
    _client.close();
  }

  http.Request _request(String base, Map<String, String> headers, List<Msg> msgs) {
    final http.Request req;
    switch (provider.wire) {
      case Wire.openai:
        req = http.Request('POST', Uri.parse('$base/chat/completions'))
          ..body = jsonEncode({
            'model': model,
            'stream': true,
            'messages': [
              if (system.isNotEmpty) {'role': 'system', 'content': system},
              for (final m in msgs) {'role': m.role, 'content': m.text},
            ],
          });
      case Wire.responses:
        req = http.Request('POST', Uri.parse('$base/responses'))
          ..body = jsonEncode({
            'model': model,
            'instructions': system.isNotEmpty ? system : 'You are a helpful assistant.',
            'input': [
              for (final m in msgs)
                m.role == 'user'
                    ? {
                        'role': 'user',
                        'content': [
                          {'type': 'input_text', 'text': m.text},
                        ],
                      }
                    : {
                        'type': 'message',
                        'role': 'assistant',
                        'content': [
                          {'type': 'output_text', 'text': m.text},
                        ],
                      },
            ],
            'stream': true,
            'store': false,
          });
      case Wire.anthropic:
        req = http.Request('POST', Uri.parse('$base/messages'))
          ..body = jsonEncode({
            'model': model,
            'stream': true,
            'max_tokens': 8192,
            if (system.isNotEmpty) 'system': system,
            'messages': [
              for (final m in msgs) {'role': m.role, 'content': m.text},
            ],
          });
      case Wire.gemini:
        req = http.Request('POST', Uri.parse('$base/models/$model:streamGenerateContent?alt=sse'))
          ..body = jsonEncode({
            if (system.isNotEmpty)
              'systemInstruction': {
                'parts': [
                  {'text': system},
                ],
              },
            'contents': [
              for (final m in msgs)
                {
                  'role': m.role == 'assistant' ? 'model' : 'user',
                  'parts': [
                    {'text': m.text},
                  ],
                },
            ],
          });
    }
    req.headers.addAll(headers);
    req.headers['accept'] = 'text/event-stream';
    if (provider.id == 'github-copilot') req.headers['x-initiator'] = 'user';
    return req;
  }

  Stream<Delta> start() async* {
    final p = provider;
    final msgs = history.where((m) => m.text.trim().isNotEmpty && m.error == null).toList();
    http.StreamedResponse? res;
    for (var attempt = 0; attempt < 2; attempt++) {
      final String base;
      final Map<String, String> headers;
      try {
        (base, headers) = await _prepare(p, force: attempt > 0);
      } on AiError {
        rethrow;
      } catch (_) {
        throw AiError('Couldn\'t reach ${p.name}. Check your connection.');
      }
      if (base.isEmpty) throw AiError('Set up ${p.name} first in Settings → Providers.');
      try {
        res = await _client.send(_request(base, headers, msgs)).timeout(const Duration(seconds: 60));
      } catch (e) {
        if (_cancelled) return;
        throw AiError(e is TimeoutException ? '${p.name} didn\'t answer in time.' : 'Couldn\'t reach ${p.name}. Check your connection.');
      }
      if (res.statusCode == 401 && p.signedIn && attempt == 0) {
        await res.stream.drain<void>(); // a revoked token: refresh once and try again
        continue;
      }
      break;
    }
    if (res!.statusCode != 200) {
      final body = await res.stream.bytesToString();
      throw AiError(_errorText(res.statusCode, body));
    }
    try {
      var parts = 0;
      await for (final line in res.stream.transform(utf8.decoder).transform(const LineSplitter())) {
        if (!line.startsWith('data:')) continue;
        final data = line.substring(5).trim();
        if (data.isEmpty || data == '[DONE]') continue;
        Map<String, dynamic> j;
        try {
          j = jsonDecode(data) as Map<String, dynamic>;
        } catch (_) {
          continue;
        }
        if (p.wire == Wire.responses && j['type'] == 'response.reasoning_summary_part.added' && ++parts > 1) {
          yield const Delta(reasoning: '\n\n');
          continue;
        }
        final d = _parse(p.wire, j);
        if (d != null) yield d;
      }
    } catch (e) {
      if (_cancelled) return;
      if (e is AiError) rethrow;
      throw AiError('The connection to ${p.name} dropped.');
    } finally {
      _client.close();
    }
  }

  Delta? _parse(Wire wire, Map<String, dynamic> j) {
    switch (wire) {
      case Wire.openai:
        if (j['error'] != null) throw AiError('${(j['error'] as Map)['message'] ?? j['error']}');
        final choices = j['choices'] as List?;
        if (choices == null || choices.isEmpty) return null;
        final d = (choices.first as Map)['delta'] as Map? ?? {};
        final text = d['content'] as String? ?? '';
        final reasoning = (d['reasoning_content'] ?? d['reasoning']) as String? ?? '';
        if (text.isEmpty && reasoning.isEmpty) return null;
        return Delta(text: text, reasoning: reasoning);
      case Wire.responses:
        switch (j['type']) {
          case 'response.output_text.delta':
            return Delta(text: j['delta'] as String? ?? '');
          case 'response.reasoning_summary_text.delta' || 'response.reasoning_text.delta':
            return Delta(reasoning: j['delta'] as String? ?? '');
          case 'response.failed':
            final e = (j['response'] as Map?)?['error'];
            throw AiError('${e is Map ? e['message'] : e ?? 'The provider reported an error.'}');
          case 'error':
            throw AiError('${j['message'] ?? (j['error'] is Map ? j['error']['message'] : null) ?? 'The provider reported an error.'}');
          default:
            return null;
        }
      case Wire.anthropic:
        switch (j['type']) {
          case 'content_block_delta':
            final d = j['delta'] as Map;
            if (d['type'] == 'text_delta') return Delta(text: d['text'] as String? ?? '');
            if (d['type'] == 'thinking_delta') return Delta(reasoning: d['thinking'] as String? ?? '');
            return null;
          case 'error':
            throw AiError('${(j['error'] as Map?)?['message'] ?? 'The provider reported an error.'}');
          default:
            return null;
        }
      case Wire.gemini:
        final cands = j['candidates'] as List?;
        if (cands == null || cands.isEmpty) return null;
        final parts = ((cands.first as Map)['content'] as Map?)?['parts'] as List? ?? [];
        var text = '', reasoning = '';
        for (final part in parts) {
          final t = (part as Map)['text'] as String? ?? '';
          if (part['thought'] == true) {
            reasoning += t;
          } else {
            text += t;
          }
        }
        if (text.isEmpty && reasoning.isEmpty) return null;
        return Delta(text: text, reasoning: reasoning);
    }
  }
}

/// A short title from the first message, so the list reads well without an extra request.
String titleFrom(String text) {
  var t = text.trim().replaceAll(RegExp(r'\s+'), ' ');
  t = t.replaceAll(RegExp(r'^(hey|hi|hello|please|can you|could you)[,!\s]+', caseSensitive: false), '');
  if (t.isEmpty) return 'New chat';
  t = t[0].toUpperCase() + t.substring(1);
  return t.length > 48 ? '${t.substring(0, 46).trimRight()}…' : t;
}
