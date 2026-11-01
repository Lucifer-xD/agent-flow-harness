// Direct chat: the phone talks to the model provider itself with the user's own key or sign-in.
// The provider list is the desktop's (assets/providers.json, written by scripts/app-providers.py);
// four wire formats cover everyone: OpenAI-compatible chat completions, OpenAI Responses (ChatGPT
// sign-in), Anthropic messages and Gemini.
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

import 'remote.dart' show ApiError;
import 'signin.dart';
import 'store.dart';
import 'tools.dart';

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
  const Delta({this.text = '', this.reasoning = '', this.step});
  final String text;
  final String reasoning;
  final ToolStep? step; // a tool started or finished
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
///
/// With tools on, it loops: the model answers or asks for tools, the phone runs them (each shows as a
/// ToolStep) and sends the results back, until the model answers in plain text.
class Run {
  Run(this.provider, this.model, this.history, {this.system = '', this.env});
  final Provider provider;
  final String model;
  final List<Msg> history; // already ends with the user's message
  final String system;
  final ToolEnv? env; // null: no tools
  final _client = http.Client();
  bool _cancelled = false;
  bool get cancelled => _cancelled;
  static const _maxRounds = 12;

  void cancel() {
    _cancelled = true;
    _client.close();
  }

  List<Tool> _tools = const [];
  final List<Map<String, dynamic>> _items = []; // the conversation in this wire's own shape

  String get _system => [system.trim(), if (env != null) toolContext()].where((s) => s.isNotEmpty).join('\n\n');

  // ---- the conversation ----

  Future<void> _build(List<Msg> msgs) async {
    // photos: only the last few go along, base64 is heavy
    final withImages = <Msg>{};
    var budget = 4;
    for (final m in msgs.reversed) {
      if (m.images.isNotEmpty && budget > 0) {
        withImages.add(m);
        budget -= m.images.length;
      }
    }
    if (provider.wire == Wire.openai && _system.isNotEmpty) _items.add({'role': 'system', 'content': _system});
    for (final m in msgs) {
      final imgs = withImages.contains(m) ? await _images(m) : const <(String, String)>[];
      final text = m.text.isEmpty && imgs.isNotEmpty ? 'What do you see?' : m.text;
      switch (provider.wire) {
        case Wire.openai:
          _items.add({
            'role': m.role,
            'content': imgs.isEmpty
                ? text
                : [
                    {'type': 'text', 'text': text},
                    for (final (mime, b64) in imgs)
                      {
                        'type': 'image_url',
                        'image_url': {'url': 'data:$mime;base64,$b64'},
                      },
                  ],
          });
        case Wire.responses:
          _items.add(
            m.role == 'user'
                ? {
                    'role': 'user',
                    'content': [
                      {'type': 'input_text', 'text': text},
                      for (final (mime, b64) in imgs) {'type': 'input_image', 'image_url': 'data:$mime;base64,$b64'},
                    ],
                  }
                : {
                    'type': 'message',
                    'role': 'assistant',
                    'content': [
                      {'type': 'output_text', 'text': text},
                    ],
                  },
          );
        case Wire.anthropic:
          _items.add({
            'role': m.role,
            'content': [
              for (final (mime, b64) in imgs)
                {
                  'type': 'image',
                  'source': {'type': 'base64', 'media_type': mime, 'data': b64},
                },
              {'type': 'text', 'text': text},
            ],
          });
        case Wire.gemini:
          _items.add({
            'role': m.role == 'assistant' ? 'model' : 'user',
            'parts': [
              for (final (mime, b64) in imgs)
                {
                  'inline_data': {'mime_type': mime, 'data': b64},
                },
              {'text': text},
            ],
          });
      }
    }
  }

  Future<List<(String, String)>> _images(Msg m) async {
    final out = <(String, String)>[];
    for (final path in m.images) {
      try {
        final bytes = await File(path).readAsBytes();
        final mime = switch (path.split('.').last.toLowerCase()) {
          'png' => 'image/png',
          'webp' => 'image/webp',
          'gif' => 'image/gif',
          _ => 'image/jpeg',
        };
        out.add((mime, base64Encode(bytes)));
      } catch (_) {}
    }
    return out;
  }

  List<dynamic> _toolSpecs() => switch (provider.wire) {
    Wire.openai => [
      for (final t in _tools)
        {
          'type': 'function',
          'function': {'name': t.name, 'description': t.description, 'parameters': t.schema},
        },
    ],
    Wire.responses => [
      for (final t in _tools) {'type': 'function', 'name': t.name, 'description': t.description, 'parameters': t.schema, 'strict': false},
    ],
    Wire.anthropic => [
      for (final t in _tools) {'name': t.name, 'description': t.description, 'input_schema': t.schema},
    ],
    Wire.gemini => [
      {
        'functionDeclarations': [
          for (final t in _tools) {'name': t.name, 'description': t.description, if (t.properties.isNotEmpty) 'parameters': t.schema},
        ],
      },
    ],
  };

  http.Request _request(String base, Map<String, String> headers, int round) {
    final tools = _tools.isEmpty ? null : _toolSpecs();
    final http.Request req;
    switch (provider.wire) {
      case Wire.openai:
        req = http.Request('POST', Uri.parse('$base/chat/completions'))..body = jsonEncode({'model': model, 'stream': true, 'messages': _items, 'tools': ?tools});
      case Wire.responses:
        req = http.Request('POST', Uri.parse('$base/responses'))
          ..body = jsonEncode({
            'model': model,
            'instructions': _system.isNotEmpty ? _system : 'You are a helpful assistant.',
            'input': _items,
            'tools': ?tools,
            'stream': true,
            'store': false,
          });
      case Wire.anthropic:
        req = http.Request('POST', Uri.parse('$base/messages'))
          ..body = jsonEncode({
            'model': model,
            'stream': true,
            'max_tokens': 8192,
            if (_system.isNotEmpty) 'system': _system,
            'messages': _items,
            'tools': ?tools,
          });
      case Wire.gemini:
        req = http.Request('POST', Uri.parse('$base/models/$model:streamGenerateContent?alt=sse'))
          ..body = jsonEncode({
            if (_system.isNotEmpty)
              'systemInstruction': {
                'parts': [
                  {'text': _system},
                ],
              },
            'contents': _items,
            'tools': ?tools,
          });
    }
    req.headers.addAll(headers);
    req.headers['accept'] = 'text/event-stream';
    // Copilot: only the user's own turn counts as a premium request
    if (provider.id == 'github-copilot') req.headers['x-initiator'] = round == 0 ? 'user' : 'agent';
    return req;
  }

  // ---- the loop ----

  Stream<Delta> start() async* {
    final p = provider;
    final msgs = history.where((m) => (m.text.trim().isNotEmpty || m.images.isNotEmpty) && m.error == null).toList();
    _tools = env != null && Settings.i.tools ? phoneTools() : const [];
    await _build(msgs);
    var wroteText = false;
    try {
      for (var round = 0; round < _maxRounds; round++) {
        final res = await _send(round);
        if (res == null) return; // cancelled
        final turn = _Turn();
        var gap = wroteText; // a new round's text starts a new paragraph
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
          final d = _parse(j, turn);
          if (d == null) continue;
          if (d.text.isNotEmpty) {
            turn.text.write(d.text);
            if (gap) {
              gap = false;
              yield const Delta(text: '\n\n');
            }
            wroteText = true;
          }
          yield d;
        }
        if (turn.calls.isEmpty || _cancelled) return;
        // run the tools the model asked for, then hand it the results
        final results = <String>[];
        for (final c in turn.calls) {
          final tool = _tools.where((t) => t.name == c.name).firstOrNull;
          Map<String, dynamic> args;
          try {
            args = c.args ?? (c.raw.trim().isEmpty ? <String, dynamic>{} : Map<String, dynamic>.from(jsonDecode(c.raw) as Map));
          } catch (_) {
            args = {};
          }
          final step = ToolStep(tool: c.name, label: tool?.label(args) ?? c.name);
          yield Delta(step: step);
          String out;
          try {
            if (tool == null) throw ToolError('There is no tool called ${c.name}.');
            out = await tool.run(args, env!);
            step.state = 'done';
            step.detail = _summary(out);
          } catch (e) {
            final why = e is ToolError ? e.message : (e is AiError ? e.message : (e is ApiError ? e.message : 'Something went wrong: $e'));
            out = 'Error: $why';
            step.state = 'error';
            step.detail = why;
          }
          if (_cancelled) return;
          yield Delta(step: step);
          c.args = args;
          results.add(out);
        }
        _append(turn, results);
      }
      yield const Delta(text: '\n\n_(Stopped after many tool steps.)_');
    } catch (e) {
      if (_cancelled) return;
      if (e is AiError) rethrow;
      throw AiError('The connection to ${p.name} dropped.');
    } finally {
      _client.close();
    }
  }

  static String _summary(String out) {
    final first = out.trim().split('\n').firstWhere((l) => l.trim().isNotEmpty, orElse: () => '');
    return first.length > 90 ? '${first.substring(0, 88)}…' : first;
  }

  /// Sends one round; on a 401 from a signed-in provider refreshes once, and drops the tools when
  /// the model turns out not to support them.
  Future<http.StreamedResponse?> _send(int round) async {
    final p = provider;
    for (var attempt = 0; attempt < 3; attempt++) {
      final String base;
      final Map<String, String> headers;
      try {
        (base, headers) = await _prepare(p, force: attempt > 0 && p.signedIn);
      } on AiError {
        rethrow;
      } catch (_) {
        throw AiError('Couldn\'t reach ${p.name}. Check your connection.');
      }
      if (base.isEmpty) throw AiError('Set up ${p.name} first in Settings → Providers.');
      final http.StreamedResponse res;
      try {
        res = await _client.send(_request(base, headers, round)).timeout(const Duration(seconds: 90));
      } catch (e) {
        if (_cancelled) return null;
        throw AiError(e is TimeoutException ? '${p.name} didn\'t answer in time.' : 'Couldn\'t reach ${p.name}. Check your connection.');
      }
      if (res.statusCode == 200) return res;
      final body = await res.stream.bytesToString();
      if (res.statusCode == 401 && p.signedIn && attempt == 0) continue; // a revoked token: refresh once
      if (_tools.isNotEmpty && round == 0 && const {400, 404, 422}.contains(res.statusCode) && RegExp(r'tool|function', caseSensitive: false).hasMatch(body)) {
        _tools = const []; // this model can't use tools: answer without them
        continue;
      }
      throw AiError(_errorText(res.statusCode, body));
    }
    throw AiError('${p.name} kept refusing the request.');
  }

  /// Adds the model's turn (its text and tool calls) and the tool results to the conversation.
  void _append(_Turn t, List<String> results) {
    final text = t.text.toString();
    switch (provider.wire) {
      case Wire.openai:
        _items.add({
          'role': 'assistant',
          'content': text.isEmpty ? null : text,
          'tool_calls': [
            for (final c in t.calls)
              {
                'id': c.id,
                'type': 'function',
                'function': {'name': c.name, 'arguments': jsonEncode(c.args)},
              },
          ],
        });
        for (final (i, c) in t.calls.indexed) {
          _items.add({'role': 'tool', 'tool_call_id': c.id, 'content': results[i]});
        }
      case Wire.responses:
        if (text.isNotEmpty) {
          _items.add({
            'type': 'message',
            'role': 'assistant',
            'content': [
              {'type': 'output_text', 'text': text},
            ],
          });
        }
        for (final (i, c) in t.calls.indexed) {
          _items.add({'type': 'function_call', 'call_id': c.id, 'name': c.name, 'arguments': jsonEncode(c.args)});
          _items.add({'type': 'function_call_output', 'call_id': c.id, 'output': results[i]});
        }
      case Wire.anthropic:
        _items.add({
          'role': 'assistant',
          'content': [
            if (text.isNotEmpty) {'type': 'text', 'text': text},
            for (final c in t.calls) {'type': 'tool_use', 'id': c.id, 'name': c.name, 'input': c.args},
          ],
        });
        _items.add({
          'role': 'user',
          'content': [
            for (final (i, c) in t.calls.indexed) {'type': 'tool_result', 'tool_use_id': c.id, 'content': results[i]},
          ],
        });
      case Wire.gemini:
        // the model's parts go back as they came: Gemini checks their thought signatures
        _items.add({
          'role': 'model',
          'parts': [
            if (text.isNotEmpty) {'text': text},
            ...t.rawParts,
          ],
        });
        _items.add({
          'role': 'user',
          'parts': [
            for (final (i, c) in t.calls.indexed)
              {
                'functionResponse': {
                  'name': c.name,
                  if (!c.id.startsWith('call_')) 'id': c.id,
                  'response': {'result': results[i]},
                },
              },
          ],
        });
    }
  }

  // ---- reading the stream ----

  Delta? _parse(Map<String, dynamic> j, _Turn turn) {
    switch (provider.wire) {
      case Wire.openai:
        if (j['error'] != null) throw AiError('${j['error'] is Map ? (j['error'] as Map)['message'] : j['error']}');
        final choices = j['choices'] as List?;
        if (choices == null || choices.isEmpty) return null;
        final d = (choices.first as Map)['delta'] as Map? ?? {};
        for (final (n, tc) in ((d['tool_calls'] as List?) ?? const []).indexed) {
          final i = (tc['index'] as num?)?.toInt() ?? n;
          final c = turn.byIndex.putIfAbsent(i, () {
            final c = _Call('call_$i', '');
            turn.calls.add(c);
            return c;
          });
          if (tc['id'] is String && (tc['id'] as String).isNotEmpty) c.id = tc['id'] as String;
          final f = tc['function'] as Map? ?? {};
          if (f['name'] is String) c.name += f['name'] as String;
          if (f['arguments'] is String) c.raw += f['arguments'] as String;
          if (f['arguments'] is Map) c.args = Map<String, dynamic>.from(f['arguments'] as Map);
        }
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
          case 'response.reasoning_summary_part.added':
            return turn.summaryParts++ > 0 ? const Delta(reasoning: '\n\n') : null;
          case 'response.output_item.added':
            final item = j['item'] as Map? ?? {};
            if (item['type'] == 'function_call') {
              final c = _Call('${item['call_id'] ?? item['id']}', '${item['name'] ?? ''}')..raw = item['arguments'] as String? ?? '';
              turn.calls.add(c);
              turn.byItem['${item['id']}'] = c;
            }
            return null;
          case 'response.function_call_arguments.delta':
            turn.byItem['${j['item_id']}']?.raw += j['delta'] as String? ?? '';
            return null;
          case 'response.output_item.done':
            final item = j['item'] as Map? ?? {};
            final c = turn.byItem['${item['id']}'];
            if (c != null && item['arguments'] is String) c.raw = item['arguments'] as String;
            return null;
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
          case 'content_block_start':
            final b = j['content_block'] as Map? ?? {};
            if (b['type'] == 'tool_use') {
              final c = _Call('${b['id']}', '${b['name']}');
              turn.calls.add(c);
              turn.byIndex[(j['index'] as num).toInt()] = c;
            }
            return null;
          case 'content_block_delta':
            final d = j['delta'] as Map;
            if (d['type'] == 'text_delta') return Delta(text: d['text'] as String? ?? '');
            if (d['type'] == 'thinking_delta') return Delta(reasoning: d['thinking'] as String? ?? '');
            if (d['type'] == 'input_json_delta') turn.byIndex[(j['index'] as num).toInt()]?.raw += d['partial_json'] as String? ?? '';
            return null;
          case 'error':
            throw AiError('${(j['error'] as Map?)?['message'] ?? 'The provider reported an error.'}');
          default:
            return null;
        }
      case Wire.gemini:
        if (j['error'] != null) throw AiError('${(j['error'] as Map)['message'] ?? j['error']}');
        final cands = j['candidates'] as List?;
        if (cands == null || cands.isEmpty) return null;
        final parts = ((cands.first as Map)['content'] as Map?)?['parts'] as List? ?? [];
        var text = '', reasoning = '';
        for (final part in parts) {
          final pt = Map<String, dynamic>.from(part as Map);
          if (pt['functionCall'] is Map) {
            final f = pt['functionCall'] as Map;
            turn.calls.add(_Call('${f['id'] ?? 'call_${turn.calls.length}'}', '${f['name']}')..args = Map<String, dynamic>.from(f['args'] as Map? ?? {}));
            turn.rawParts.add(pt);
            continue;
          }
          final t = pt['text'] as String? ?? '';
          if (pt['thought'] == true) {
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

/// What the model said in one round, and the tools it asked for.
class _Turn {
  final text = StringBuffer();
  final calls = <_Call>[];
  final byIndex = <int, _Call>{};
  final byItem = <String, _Call>{};
  final rawParts = <Map<String, dynamic>>[];
  int summaryParts = 0;
}

class _Call {
  _Call(this.id, this.name);
  String id;
  String name;
  String raw = ''; // arguments as they stream in
  Map<String, dynamic>? args;
}

/// A short title from the first message, so the list reads well without an extra request.
String titleFrom(String text) {
  var t = text.trim().replaceAll(RegExp(r'\s+'), ' ');
  t = t.replaceAll(RegExp(r'^(hey|hi|hello|please|can you|could you)[,!\s]+', caseSensitive: false), '');
  if (t.isEmpty) return 'New chat';
  t = t[0].toUpperCase() + t.substring(1);
  return t.length > 48 ? '${t.substring(0, 46).trimRight()}…' : t;
}
