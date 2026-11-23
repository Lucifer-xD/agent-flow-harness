// Assistants: your own instructions under a name, with their own model if you like.
import 'package:flutter/material.dart';

import '../core/ai.dart';
import '../core/l10n.dart';
import '../core/store.dart';
import '../ui/badge.dart';
import '../ui/kit.dart';
import '../ui/look.dart';
import '../ui/motion.dart';
import 'chat.dart';
import 'pick.dart';

const _icons = <String, IconData>{
  'sparkles': LucideIcons.sparkles,
  'pen': LucideIcons.penLine,
  'code': LucideIcons.code,
  'book': LucideIcons.bookOpen,
  'languages': LucideIcons.languages,
  'briefcase': LucideIcons.briefcase,
  'heart': LucideIcons.heartPulse,
  'chef': LucideIcons.chefHat,
  'plane': LucideIcons.plane,
  'music': LucideIcons.music,
  'scale': LucideIcons.scale,
  'grad': LucideIcons.graduationCap,
};

IconData assistantIcon(String id) => _icons[id] ?? LucideIcons.sparkles;

/// An assistant with an empty id means "none".
Future<Assistant?> pickAssistant(BuildContext context, String? current) async {
  Assistant? got;
  await actions(context, title: t('Assistant'), [
    Act(t('None'), LucideIcons.circleOff, () => got = Assistant(id: ''), on: current == null),
    for (final a in Settings.i.assistants) Act(a.name, assistantIcon(a.icon), () => got = a, sub: a.system.replaceAll('\n', ' '), on: a.id == current),
    null,
    Act(t('Make an assistant'), LucideIcons.plus, () => go(context, const AssistantScreen())),
  ]);
  return got;
}

class AssistantsScreen extends StatelessWidget {
  const AssistantsScreen({super.key});

  static final ideas = [
    ('languages', 'Translator', 'Translate everything I write between Arabic and English. Keep the tone, and add a short note only when a word has no exact match.'),
    ('pen', 'Editor', 'Improve my writing. Fix mistakes, make it clear and natural, and keep my voice. Reply with the improved text first, then list what you changed in a few words.'),
    ('code', 'Code reviewer', 'Review the code I send. Find bugs first, then things that are hard to read. Be specific, show the fix, and skip praise.'),
    ('grad', 'Tutor', 'Teach me step by step. Ask what I already know, explain with small examples, and check I understood before moving on.'),
  ];

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: Settings.i,
    builder: (context, _) {
      final list = Settings.i.assistants;
      return AppPage(
        title: t('Assistants'),
        sub: t('Your own instructions under a name, ready for any chat.'),
        actions: [Ic(LucideIcons.plus, tip: t('Make an assistant'), onTap: () => go(context, const AssistantScreen()))],
        slivers: [
          pad([
            if (list.isNotEmpty)
              Group(
                children: [
                  for (final a in list)
                    Tile(
                      a.name,
                      sub: a.system.replaceAll('\n', ' '),
                      lead: Square(assistantIcon(a.icon), color: context.p.accent),
                      trail: Ic(LucideIcons.pencil, size: 34, icon_: 16, color: context.p.text3, tip: t('Edit'), onTap: () => go(context, AssistantScreen(a: a))),
                      onTap: () => go(context, ChatScreen(newChat(assistant: a), focus: true)),
                    ),
                ],
              ),
            Head(t('Ideas')),
            for (final (icon, name, system) in ideas)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: Panel(
                  onTap: () => go(
                    context,
                    AssistantScreen(
                      a: Assistant(id: newId(), name: t(name), system: t(system), icon: icon),
                    ),
                  ),
                  child: Row(
                    children: [
                      Square(assistantIcon(icon)),
                      const SizedBox(width: 13),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(t(name), style: T.row.copyWith(color: context.p.text)),
                            const SizedBox(height: 2),
                            Text(t(system), maxLines: 2, overflow: TextOverflow.ellipsis, style: T.small.copyWith(color: context.p.text3)),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
          ]),
        ],
      );
    },
  );
}

class AssistantScreen extends StatefulWidget {
  const AssistantScreen({super.key, this.a});
  final Assistant? a;
  @override
  State<AssistantScreen> createState() => _AssistantScreenState();
}

class _AssistantScreenState extends State<AssistantScreen> {
  late final _name = TextEditingController(text: widget.a?.name ?? '');
  late final _sys = TextEditingController(text: widget.a?.system ?? '');
  late String _icon = widget.a?.icon ?? 'sparkles';
  late String? _model = widget.a?.model;

  bool get _saved => widget.a != null && Settings.i.assistant(widget.a!.id) != null;

  @override
  void dispose() {
    _name.dispose();
    _sys.dispose();
    super.dispose();
  }

  void _save() {
    final name = _name.text.trim();
    if (name.isEmpty) return toast(context, t('Give it a name.'), bad: true);
    final a = Assistant(id: widget.a?.id ?? newId(), name: name, system: _sys.text.trim(), icon: _icon, model: _model);
    Settings.i.assistants = [
      for (final x in Settings.i.assistants) x.id == a.id ? a : x,
      if (Settings.i.assistant(a.id) == null) a,
    ];
    Navigator.pop(context);
  }

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final slash = _model?.indexOf('/') ?? -1;
    return AppPage(
      title: _saved ? t('Edit assistant') : t('New assistant'),
      actions: [Btn(t('Save'), small: true, wide: false, onTap: _save), const SizedBox(width: 6)],
      slivers: [
        pad([
          Field(_name, label: t('Name'), hint: t('Translator')),
          const SizedBox(height: 18),
          Field(_sys, label: t('Instructions'), hint: t('How it should answer, what it should know, what to avoid…'), lines: 5, maxLines: 14),
          Head(t('Icon')),
          Wrap(
            spacing: 9,
            runSpacing: 9,
            children: [
              for (final e in _icons.entries)
                Press(
                  onTap: () => setState(() => _icon = e.key),
                  child: AnimatedContainer(
                    duration: med,
                    width: 46,
                    height: 46,
                    decoration: BoxDecoration(color: _icon == e.key ? p.inv : p.fill, borderRadius: BorderRadius.circular(15)),
                    child: Icon(e.value, size: 20, color: _icon == e.key ? p.onInv : p.text2),
                  ),
                ),
            ],
          ),
          Group(
            title: t('Model'),
            children: [
              Tile(
                _model == null ? t('The one used last') : prettyModel(_model!.substring(slash + 1)),
                lead: _model == null ? const Square(LucideIcons.shuffle) : LogoBox(_model!.substring(0, slash), model: _model!),
                arrow: true,
                onTap: () async {
                  final got = await pickModel(context, phoneModels(), current: _model, phone: true);
                  if (got != null) setState(() => _model = got.row.key);
                },
              ),
              if (_model != null) Tile(t('Use the one used last'), icon: LucideIcons.x, onTap: () => setState(() => _model = null)),
            ],
          ),
          if (_saved) ...[
            const SizedBox(height: 24),
            Btn(
              t('Delete'),
              kind: Kind.danger,
              onTap: () async {
                if (!await confirm(context, t('Delete {}?', widget.a!.name), t('Chats made with it stay.'), t('Delete'), danger: true)) return;
                Settings.i.assistants = [for (final x in Settings.i.assistants) if (x.id != widget.a!.id) x];
                if (context.mounted) Navigator.pop(context);
              },
            ),
          ],
        ]),
      ],
    );
  }
}
