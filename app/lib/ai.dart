// Direct chat: the phone talks to the model provider itself with the user's own key. Three wire
// formats cover everyone: OpenAI-compatible chat completions, Anthropic messages and Gemini.
import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'store.dart';

enum Wire { openai, anthropic, gemini }

class Provider {
  const Provider({
    required this.id,
    required this.name,
    required this.wire,
    required this.base,
    required this.keysUrl,
    required this.color,
    required this.blurb,
    this.fallback = const [],
    this.keyHint = '',
  });
  final String id;
  final String name;
  final Wire wire;
  final String base;
  final String keysUrl;
  final Color color;
  final String blurb;
  final List<String> fallback; // shown before the model list has been fetched
  final String keyHint;

  String get initials => name.substring(0, 1);
  String baseUrl() => (Settings.i.baseUrl(id) ?? base).replaceAll(RegExp(r'/+$'), '');
  bool get ready => (Settings.i.keys[id] ?? '').isNotEmpty || (id == 'custom' && (Settings.i.baseUrl(id) ?? '').isNotEmpty);
  List<String> get models {
    final got = Settings.i.models[id];
    return got != null && got.isNotEmpty ? got : fallback;
  }
}

const providers = <Provider>[
  Provider(
    id: 'openai',
    name: 'OpenAI',
    wire: Wire.openai,
    base: 'https://api.openai.com/v1',
    keysUrl: 'https://platform.openai.com/api-keys',
    color: Color(0xFF10A37F),
    blurb: 'GPT and o-series models',
    fallback: ['gpt-5', 'gpt-5-mini', 'gpt-4.1'],
    keyHint: 'sk-…',
  ),
  Provider(
    id: 'anthropic',
    name: 'Anthropic',
    wire: Wire.anthropic,
    base: 'https://api.anthropic.com/v1',
    keysUrl: 'https://console.anthropic.com/settings/keys',
    color: Color(0xFFD97757),
    blurb: 'Claude Opus, Sonnet and Haiku',
    fallback: ['claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5'],
    keyHint: 'sk-ant-…',
  ),
  Provider(
    id: 'gemini',
    name: 'Google Gemini',
    wire: Wire.gemini,
    base: 'https://generativelanguage.googleapis.com/v1beta',
    keysUrl: 'https://aistudio.google.com/apikey',
    color: Color(0xFF4F8DF7),
    blurb: 'Gemini Pro and Flash',
    fallback: ['gemini-2.5-pro', 'gemini-2.5-flash'],
    keyHint: 'AIza…',
  ),
  Provider(
    id: 'openrouter',
    name: 'OpenRouter',
    wire: Wire.openai,
    base: 'https://openrouter.ai/api/v1',
    keysUrl: 'https://openrouter.ai/keys',
    color: Color(0xFF8B7CF6),
    blurb: 'Hundreds of models with one key',
    fallback: ['openrouter/auto'],
    keyHint: 'sk-or-…',
  ),
  Provider(
    id: 'groq',
    name: 'Groq',
    wire: Wire.openai,
    base: 'https://api.groq.com/openai/v1',
    keysUrl: 'https://console.groq.com/keys',
    color: Color(0xFFF55036),
    blurb: 'Very fast open models',
    fallback: ['llama-3.3-70b-versatile'],
    keyHint: 'gsk_…',
  ),
  Provider(
    id: 'deepseek',
    name: 'DeepSeek',
    wire: Wire.openai,
    base: 'https://api.deepseek.com/v1',
    keysUrl: 'https://platform.deepseek.com/api_keys',
    color: Color(0xFF4D6BFE),
    blurb: 'DeepSeek chat and reasoner',
    fallback: ['deepseek-chat', 'deepseek-reasoner'],
    keyHint: 'sk-…',
  ),
  Provider(
    id: 'xai',
    name: 'xAI',
    wire: Wire.openai,
    base: 'https://api.x.ai/v1',
    keysUrl: 'https://console.x.ai',
    color: Color(0xFFE7E7E7),
    blurb: 'Grok models',
    fallback: ['grok-4'],
    keyHint: 'xai-…',
  ),
  Provider(
    id: 'mistral',
    name: 'Mistral',
    wire: Wire.openai,
    base: 'https://api.mistral.ai/v1',
    keysUrl: 'https://console.mistral.ai/api-keys',
    color: Color(0xFFFF7000),
    blurb: 'Mistral Large, Medium and Codestral',
    fallback: ['mistral-large-latest', 'mistral-medium-latest'],
    keyHint: '',
  ),
  Provider(
    id: 'custom',
    name: 'Custom server',
    wire: Wire.openai,
    base: '',
    keysUrl: '',
    color: Color(0xFFBDB0A5),
    blurb: 'Any OpenAI-compatible server: Ollama, LM Studio, vLLM…',
    keyHint: 'optional',
  ),
];

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

Map<String, String> _headers(Provider p) {
  final key = Settings.i.keys[p.id] ?? '';
  switch (p.wire) {
    case Wire.anthropic:
      return {'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'};
    case Wire.gemini:
      return {'x-goog-api-key': key, 'content-type': 'application/json'};
    case Wire.openai:
      return {
        if (key.isNotEmpty) 'authorization': 'Bearer $key',
        'content-type': 'application/json',
        if (p.id == 'openrouter') ...{'HTTP-Referer': 'https://agentflowharness.com', 'X-Title': 'AFH'},
      };
  }
}

String _errorText(int status, String body) {
  try {
    final j = jsonDecode(body);
    final e = j is List ? j.first['error'] : j['error'];
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

/// Fetches the models this key can use.
Future<List<String>> fetchModels(Provider p) async {
  final base = p.baseUrl();
  if (base.isEmpty) throw AiError('Enter the server address first.');
  final Uri url = switch (p.wire) {
    Wire.gemini => Uri.parse('$base/models?pageSize=200'),
    Wire.anthropic => Uri.parse('$base/models?limit=100'),
    Wire.openai => Uri.parse('$base/models'),
  };
  final http.Response res;
  try {
    res = await http.get(url, headers: _headers(p)).timeout(const Duration(seconds: 20));
  } on TimeoutException {
    throw AiError('The provider didn\'t answer in time.');
  } catch (_) {
    throw AiError('Couldn\'t reach ${p.name}. Check your connection.');
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
  } else {
    ids = [for (final m in (j['data'] as List? ?? [])) m['id'] as String];
    if (p.id == 'openai') {
      ids.removeWhere(
        (id) =>
            !RegExp(r'^(gpt|o\d|chatgpt)').hasMatch(id) ||
            RegExp(r'audio|realtime|tts|transcribe|image|search|instruct|embedding|moderation|codex').hasMatch(id) ||
            RegExp(r'-\d{4}-\d{2}-\d{2}$').hasMatch(id),
      );
    }
    ids.removeWhere((id) => RegExp(r'embed|whisper|tts|moderation|guard|dall-e').hasMatch(id));
  }
  if (p.id != 'openrouter' && p.wire != Wire.anthropic) ids.sort((a, b) => b.compareTo(a));
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

  Stream<Delta> start() async* {
    final p = provider;
    final base = p.baseUrl();
    if (base.isEmpty) throw AiError('Set up ${p.name} first in Settings → Providers.');
    final msgs = history.where((m) => m.text.trim().isNotEmpty && m.error == null).toList();
    late http.Request req;
    switch (p.wire) {
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
    req.headers.addAll(_headers(p));
    req.headers['accept'] = 'text/event-stream';

    final http.StreamedResponse res;
    try {
      res = await _client.send(req).timeout(const Duration(seconds: 60));
    } catch (e) {
      if (_cancelled) return;
      throw AiError(e is TimeoutException ? '${p.name} didn\'t answer in time.' : 'Couldn\'t reach ${p.name}. Check your connection.');
    }
    if (res.statusCode != 200) {
      final body = await res.stream.bytesToString();
      throw AiError(_errorText(res.statusCode, body));
    }
    try {
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
