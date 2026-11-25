// You: the account, the models, how the assistant behaves, how the app looks and what it may do.
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:local_auth/local_auth.dart';
import 'package:share_plus/share_plus.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/ai.dart';
import '../core/l10n.dart';
import '../core/native.dart';
import '../core/relay.dart';
import '../core/runs.dart';
import '../core/store.dart';
import '../core/tools.dart';
import '../core/voice.dart';
import '../ui/badge.dart';
import '../ui/convo.dart';
import '../ui/kit.dart';
import '../ui/look.dart';
import '../ui/mark.dart';
import '../ui/md.dart';
import '../ui/motion.dart';
import 'account.dart';
import 'assistants.dart';
import 'chat.dart' show phoneStepIcon;
import 'providers.dart';

const appVersion = '2.0.3';

void openWeb(String url) => launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);

class YouTab extends StatelessWidget {
  const YouTab({super.key, required this.controller});
  final ScrollController controller;

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: Listenable.merge([Settings.i, Account.i]),
    builder: (context, _) {
      final p = context.p;
      final s = Settings.i;
      final a = Account.i;
      final ready = [for (final x in providers) if (x.ready) x];
      final on = a.computers.where((c) => c.online).length;
      return AppPage(
        title: t('You'),
        back: false,
        controller: controller,
        bottom: 110,
        slivers: [
          pad([
            Panel(
              onTap: () => go(context, a.signedIn ? const AccountScreen() : const SignInScreen()),
              child: Row(
                children: [
                  Container(
                    width: 50,
                    height: 50,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(color: p.tint(p.accent), shape: BoxShape.circle),
                    child: a.signedIn
                        ? Text(a.email.isEmpty ? '·' : a.email[0].toUpperCase(), style: T.h1.copyWith(color: p.accent))
                        : Icon(LucideIcons.userRound, size: 22, color: p.accent),
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(a.signedIn ? a.email : t('Sign in to AFH'), maxLines: 1, overflow: TextOverflow.ellipsis, style: T.h3.copyWith(color: p.text)),
                        const SizedBox(height: 2),
                        Text(
                          a.signedIn ? (a.computers.isEmpty ? t('No computers yet') : t('{} of {} computers online', on, a.computers.length)) : t('Reach AFH on your computers'),
                          style: T.sub.copyWith(color: p.text2),
                        ),
                      ],
                    ),
                  ),
                  Icon(Directionality.of(context) == TextDirection.rtl ? LucideIcons.chevronLeft : LucideIcons.chevronRight, size: 18, color: p.text3),
                ],
              ),
            ),
            Group(
              title: t('Chats on this phone'),
              children: [
                Tile(
                  t('Models'),
                  sub: ready.isEmpty ? t('Connect one to start chatting') : ready.map((x) => x.name).join(', '),
                  subMax: 1,
                  icon: LucideIcons.sparkles,
                  arrow: true,
                  onTap: () => go(context, const ProvidersScreen()),
                ),
                Tile(t('Assistants'), icon: LucideIcons.drama, value: s.assistants.isEmpty ? null : '${s.assistants.length}', arrow: true, onTap: () => go(context, const AssistantsScreen())),
                Tile(
                  t('Instructions'),
                  sub: s.system.isEmpty ? t('How you like to be answered') : s.system.replaceAll('\n', ' '),
                  subMax: 1,
                  icon: LucideIcons.scrollText,
                  arrow: true,
                  onTap: () async {
                    final v = await askText(context, t('Instructions'), value: s.system, lines: 6, hint: t('Answer briefly. I\'m a web developer in Cairo.'));
                    if (v != null) s.system = v;
                  },
                ),
                Tile(t('Memory'), icon: LucideIcons.brain, value: s.memory.isEmpty ? null : '${s.memory.length}', arrow: true, onTap: () => go(context, const MemoryScreen())),
                Tile(t('Tools'), icon: LucideIcons.wrench, value: s.tools ? t('On') : t('Off'), arrow: true, onTap: () => go(context, const ToolsScreen())),
              ],
            ),
            Group(
              title: t('App'),
              children: [
                Tile(
                  t('Appearance'),
                  icon: LucideIcons.palette,
                  value: switch (s.themeMode) { 'dark' => t('Dark'), 'light' => t('Light'), _ => t('System') },
                  arrow: true,
                  onTap: () => go(context, const LookScreen()),
                ),
                Tile(t('Notifications'), icon: LucideIcons.bell, arrow: true, onTap: () => go(context, const NotifyScreen())),
                Tile(t('Voice'), icon: LucideIcons.audioLines, arrow: true, onTap: () => go(context, const VoiceScreen())),
                Tile(t('Privacy'), icon: LucideIcons.lockKeyhole, value: s.flag('lock') ? t('Locked') : null, arrow: true, onTap: () => go(context, const PrivacyScreen())),
                Tile(
                  t('Language'),
                  icon: LucideIcons.languages,
                  value: switch (s.language) { 'ar' => 'العربية', 'en' => 'English', _ => t('System') },
                  arrow: true,
                  onTap: () => actions(context, title: t('Language'), [
                    for (final (id, name) in [('system', t('System')), ('en', 'English'), ('ar', 'العربية')]) Act(name, LucideIcons.languages, () => s.put('language', id), on: s.language == id),
                  ]),
                ),
              ],
            ),
            Group(
              title: t('About'),
              children: [
                Tile(t('Get AFH for your computer'), icon: LucideIcons.download, onTap: () => openWeb('$server/download')),
                Tile(t('What\'s new'), icon: LucideIcons.gift, onTap: () => openWeb('$server/changelog')),
                Tile(t('Source code'), icon: LucideIcons.code, onTap: () => openWeb('https://github.com/Lucifer-xD/agent-flow-harness')),
                Tile(t('Licences'), icon: LucideIcons.scale, onTap: () => showLicensePage(context: context, applicationName: 'AFH', applicationVersion: appVersion)),
              ],
            ),
            const SizedBox(height: 30),
            const Center(child: AfhLogo(width: 54, intro: false)),
            const SizedBox(height: 14),
            Text('AFH $appVersion', textAlign: TextAlign.center, style: T.label.copyWith(color: p.text2)),
            const SizedBox(height: 3),
            Text(t('Keys and chats stay on this phone. No tracking.'), textAlign: TextAlign.center, style: T.small.copyWith(color: p.text3)),
          ]),
        ],
      );
    },
  );
}

// ---- look ----

class LookScreen extends StatelessWidget {
  const LookScreen({super.key});
  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: Settings.i,
    builder: (context, _) {
      final p = context.p;
      final s = Settings.i;
      const ids = ['system', 'light', 'dark'];
      return AppPage(
        title: t('Appearance'),
        slivers: [
          pad([
            Panel(
              pad: const EdgeInsets.fromLTRB(16, 18, 16, 18),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Align(
                    alignment: AlignmentDirectional.centerEnd,
                    child: Mine(t('Is the new build ready?'), pad: const EdgeInsetsDirectional.only(start: 40)),
                  ),
                  const SizedBox(height: 14),
                  Row(
                    children: [
                      Icon(LucideIcons.terminal, size: 14, color: p.text3),
                      const SizedBox(width: 9),
                      Text(t('Ran the tests'), style: T.small.copyWith(color: p.text3)),
                      const SizedBox(width: 10),
                      Icon(LucideIcons.check, size: 14, color: p.good),
                    ],
                  ),
                  const SizedBox(height: 10),
                  Md(t('Yes. All **48 tests** pass, and the page now loads in `0.4s`.')),
                ],
              ),
            ),
            const SizedBox(height: 16),
            Seg([t('System'), t('Light'), t('Dark')], ids.indexOf(s.themeMode).clamp(0, 2), (i) => s.put('look.mode', ids[i]), icons: const [LucideIcons.sunMoon, LucideIcons.sun, LucideIcons.moon], height: 44),
            Head(t('Colour')),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                for (final e in accents.entries)
                  Press(
                    onTap: () => s.put('look.accent', e.key),
                    label: t(e.value.$1),
                    scale: .86,
                    child: AnimatedContainer(
                      duration: med,
                      curve: Curves.easeOutCubic,
                      width: 40,
                      height: 40,
                      padding: const EdgeInsets.all(4),
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        border: Border.all(color: s.accent == e.key ? (p.dark ? e.value.$2 : e.value.$3) : Colors.transparent, width: 2),
                      ),
                      child: DecoratedBox(
                        decoration: BoxDecoration(color: p.dark ? e.value.$2 : e.value.$3, shape: BoxShape.circle),
                      ),
                    ),
                  ),
              ],
            ),
            Group(
              title: t('Text size'),
              children: [
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
                  child: Row(
                    children: [
                      Text('A', style: T.small.copyWith(color: p.text2)),
                      Expanded(
                        child: Slider(
                          value: s.textScale.clamp(.85, 1.3),
                          min: .85,
                          max: 1.3,
                          divisions: 9,
                          activeColor: p.accent,
                          inactiveColor: p.fill2,
                          onChanged: (v) {
                            Tap.tick();
                            s.put('look.text', v);
                          },
                        ),
                      ),
                      Text('A', style: T.h1.copyWith(color: p.text2)),
                    ],
                  ),
                ),
              ],
            ),
            Group(
              title: t('More'),
              children: [
                ToggleTile(t('Pure black'), s.black, (v) => s.put('look.black', v), icon: LucideIcons.moonStar, sub: t('In dark mode, for OLED screens')),
                ToggleTile(t('Haptics'), s.haptics, (v) => s.put('look.haptics', v), icon: LucideIcons.vibrate, sub: t('Small taps you can feel')),
                ToggleTile(t('Calm'), s.calm, (v) => s.put('look.calm', v), icon: LucideIcons.leaf, sub: t('Fewer animations')),
              ],
            ),
          ]),
        ],
      );
    },
  );
}

// ---- notifications ----

class NotifyScreen extends StatelessWidget {
  const NotifyScreen({super.key});
  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: Settings.i,
    builder: (context, _) {
      final s = Settings.i;
      Future<void> set(String k, bool v) async {
        s.put(k, v);
        if (v && !await Notify.allowed() && context.mounted) toast(context, t('Allow notifications for AFH in the phone\'s settings.'), bad: true);
        Notify.working();
      }

      return AppPage(
        title: t('Notifications'),
        slivers: [
          pad([
            Group(
              children: [
                ToggleTile(t('When a thread needs you'), s.flag('notify.asks', true), (v) => set('notify.asks', v), icon: LucideIcons.hand, sub: t('Allow or deny from the notification itself')),
                ToggleTile(t('When work is done'), s.flag('notify.done', true), (v) => set('notify.done', v), icon: LucideIcons.circleCheck, sub: t('Threads that finish, replies you left the app for')),
              ],
            ),
            if (!isIOS) const SizedBox(height: 12),
            if (!isIOS)
              Group(
                note: t('While a thread works, a quiet notification keeps the line to your computer open. It goes away when the work is done.'),
                children: [ToggleTile(t('Stay connected while working'), s.flag('notify.live', true), (v) => set('notify.live', v), icon: LucideIcons.radio)],
              )
            else
              Padding(
                padding: const EdgeInsets.only(top: 18),
                child: Note(t('iPhone closes the connection to your computer soon after you leave the app, so threads can only notify you while AFH is open or just left.'), icon: LucideIcons.info),
              ),
          ]),
        ],
      );
    },
  );
}

// ---- voice ----

class VoiceScreen extends StatefulWidget {
  const VoiceScreen({super.key});
  @override
  State<VoiceScreen> createState() => _VoiceScreenState();
}

class _VoiceScreenState extends State<VoiceScreen> {
  List<(String, String)>? _langs;

  @override
  void dispose() {
    Voice.i.hush();
    super.dispose();
  }

  Future<void> _pick() async {
    if (_langs == null) {
      final l = await Voice.i.locales();
      _langs = [for (final x in l) (x.localeId, x.name)];
    }
    if (!mounted) return;
    if (_langs!.isEmpty) return toast(context, t('Speech isn\'t available on this phone. Check the microphone permission.'), bad: true);
    await sheet<void>(
      context,
      title: t('Language I speak'),
      full: true,
      (c) => ListView(
        padding: EdgeInsets.only(bottom: 20 + MediaQuery.paddingOf(c).bottom),
        children: [
          for (final (id, name) in [('', t('The phone\'s language')), ..._langs!])
            Tile(
              name,
              trail: Settings.i.str('voice.lang') == id ? Icon(LucideIcons.check, size: 18, color: c.p.accent) : null,
              onTap: () {
                Settings.i.put('voice.lang', id.isEmpty ? null : id);
                Navigator.pop(c);
              },
            ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: Listenable.merge([Settings.i, Voice.i]),
    builder: (context, _) {
      final p = context.p;
      final s = Settings.i;
      final reading = Voice.i.speaking == 'test';
      return AppPage(
        title: t('Voice'),
        sub: t('For the microphone, reading aloud and talking hands-free.'),
        slivers: [
          pad([
            Group(
              children: [
                Tile(t('Language I speak'), icon: LucideIcons.mic, value: s.str('voice.lang').isEmpty ? t('The phone\'s language') : s.str('voice.lang'), arrow: true, onTap: _pick),
              ],
            ),
            Group(
              title: t('Reading speed'),
              children: [
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
                  child: Row(
                    children: [
                      Icon(LucideIcons.turtle, size: 18, color: p.text2),
                      Expanded(
                        child: Slider(
                          value: s.dbl('voice.rate', .5).clamp(.3, .8),
                          min: .3,
                          max: .8,
                          divisions: 10,
                          activeColor: p.accent,
                          inactiveColor: p.fill2,
                          onChanged: (v) {
                            Tap.tick();
                            s.put('voice.rate', v);
                          },
                        ),
                      ),
                      Icon(LucideIcons.rabbit, size: 18, color: p.text2),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 18),
            Btn(
              reading ? t('Stop') : t('Try it'),
              icon: reading ? LucideIcons.square : LucideIcons.volume2,
              kind: Kind.soft,
              onTap: () => reading ? Voice.i.hush() : Voice.i.speak('test', t('This is how replies sound when they are read aloud.')),
            ),
          ]),
        ],
      );
    },
  );
}

// ---- privacy ----

class PrivacyScreen extends StatelessWidget {
  const PrivacyScreen({super.key});

  Future<void> _lock(BuildContext context, bool v) async {
    final auth = LocalAuthentication();
    try {
      if (!await auth.isDeviceSupported()) {
        if (context.mounted) toast(context, t('Set a screen lock on the phone first.'), bad: true);
        return;
      }
      if (!await auth.authenticate(localizedReason: t('Unlock AFH'))) return;
      Settings.i.put('lock', v);
    } catch (e) {
      if (context.mounted) toast(context, t('Set a screen lock on the phone first.'), bad: true);
    }
  }

  Future<void> _export(BuildContext context) async {
    final f = File('${Directory.systemTemp.path}/afh-chats.md');
    await f.writeAsString([for (final c in Chats.i.all) c.export()].join('\n\n---\n\n'));
    await SharePlus.instance.share(ShareParams(files: [XFile(f.path, mimeType: 'text/markdown')]));
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: Listenable.merge([Settings.i, Chats.i]),
    builder: (context, _) {
      final p = context.p;
      final n = Chats.i.all.length;
      return AppPage(
        title: t('Privacy'),
        slivers: [
          pad([
            Group(
              children: [
                ToggleTile(t('Lock the app'), Settings.i.flag('lock'), (v) => _lock(context, v), icon: LucideIcons.fingerprintPattern, sub: t('Face, fingerprint or the phone\'s passcode to open AFH')),
              ],
            ),
            Group(
              title: t('Chats on this phone'),
              children: [
                Tile(t('Save all chats'), sub: t('One Markdown file'), icon: LucideIcons.fileDown, onTap: n == 0 ? null : () => _export(context)),
                Tile(
                  t('Delete all chats'),
                  sub: n == 1 ? t('1 chat') : t('{} chats', n),
                  icon: LucideIcons.trash2,
                  color: p.bad,
                  onTap: n == 0
                      ? null
                      : () async {
                          if (!await confirm(context, t('Delete all chats?'), t('They are removed from this phone for good.'), t('Delete'), danger: true)) return;
                          for (final r in Runs.i.live.values.toList()) {
                            r.stop();
                          }
                          Chats.i.deleteAll();
                          if (context.mounted) toast(context, t('Deleted'));
                        },
                ),
              ],
            ),
            Padding(
              padding: const EdgeInsets.only(top: 20),
              child: Note(
                t('Keys sit in the phone\'s own keystore and go only to the provider they belong to. What you ask a computer goes through the AFH relay to that computer, and isn\'t kept on the way.'),
                icon: LucideIcons.shieldCheck,
              ),
            ),
          ]),
        ],
      );
    },
  );
}

// ---- memory and tools ----

class MemoryScreen extends StatelessWidget {
  const MemoryScreen({super.key});
  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: Settings.i,
    builder: (context, _) {
      final p = context.p;
      final list = Settings.i.memory;
      Future<void> add() async {
        final v = await askText(context, t('Remember'), hint: t('I\'m vegetarian and I live in Cairo.'), lines: 3);
        if (v != null && v.isNotEmpty) Settings.i.memory = [...list, v];
      }

      return AppPage(
        title: t('Memory'),
        sub: t('What every chat on this phone knows about you.'),
        actions: [Ic(LucideIcons.plus, tip: t('Add'), onTap: add)],
        slivers: [
          pad([
            if (list.isEmpty)
              Empty(LucideIcons.brain, t('Nothing remembered yet'), t('Say "remember that…" in a chat, or add something here.'), action: t('Add'), onTap: add)
            else
              Group(
                children: [
                  for (final (i, m) in list.indexed)
                    Tile(
                      m,
                      titleMax: 4,
                      trail: Ic(LucideIcons.x, size: 32, icon_: 15, color: p.text3, tip: t('Forget'), onTap: () => Settings.i.memory = [...list]..removeAt(i)),
                      onTap: () async {
                        final v = await askText(context, t('Edit'), value: m, lines: 3);
                        if (v != null && v.isNotEmpty) Settings.i.memory = [...list]..[i] = v;
                      },
                    ),
                ],
              ),
          ]),
        ],
      );
    },
  );
}

const _toolNames = <String, String>{
  'web_search': 'Search the web',
  'read_webpage': 'Read web pages',
  'get_weather': 'Weather',
  'get_location': 'Where you are',
  'get_device_info': 'About the phone',
  'calculate': 'Calculator',
  'read_clipboard': 'Read the clipboard',
  'copy_to_clipboard': 'Copy to the clipboard',
  'open_link': 'Open links',
  'open_maps': 'Maps',
  'start_call': 'Start a call',
  'draft_text_message': 'Draft a text message',
  'draft_email': 'Draft an email',
  'find_contact': 'Look up a contact',
  'set_reminder': 'Reminders',
  'add_calendar_event': 'Calendar',
  'remember': 'Remember things',
  'forget': 'Forget things',
  'list_computers': 'See your computers',
  'run_on_computer': 'Start work on a computer',
  'read_computer_thread': 'Read a thread on a computer',
};

class ToolsScreen extends StatelessWidget {
  const ToolsScreen({super.key});
  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: Settings.i,
    builder: (context, _) {
      final on = Settings.i.tools;
      return AppPage(
        title: t('Tools'),
        sub: t('What models may use while they answer. Anything that leaves the chat is asked first.'),
        slivers: [
          pad([
            Group(
              children: [ToggleTile(t('Use tools'), on, (v) => Settings.i.tools = v, icon: LucideIcons.wrench, sub: t('Off: models only talk'))],
            ),
            const SizedBox(height: 12),
            AnimatedOpacity(
              opacity: on ? 1 : .4,
              duration: med,
              child: Group(
                children: [for (final x in phoneTools()) Tile(t(_toolNames[x.name] ?? x.name), icon: phoneStepIcon(x.name))],
              ),
            ),
          ]),
        ],
      );
    },
  );
}

/// A row for a connected provider, used where models are listed.
class ProviderRow extends StatelessWidget {
  const ProviderRow(this.p, {super.key});
  final Provider p;
  @override
  Widget build(BuildContext context) => Tile(p.name, sub: connectedText(p), lead: LogoBox(p.id, name: p.name), arrow: true, onTap: () => go(context, ProviderScreen(p)));
}
