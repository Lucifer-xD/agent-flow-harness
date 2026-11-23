// AFH for the phone: chats with any model, and your own computers.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:local_auth/local_auth.dart';

import 'core/ai.dart';
import 'core/hub.dart';
import 'core/l10n.dart';
import 'core/native.dart';
import 'core/store.dart';
import 'screens/shell.dart';
import 'screens/welcome.dart';
import 'ui/badge.dart';
import 'ui/kit.dart';
import 'ui/look.dart';
import 'ui/mark.dart';
import 'ui/motion.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  unawaited(SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge));
  await Settings.i.load();
  pickLanguage();
  await Future.wait([loadProviders(), loadLogos(), Chats.i.load()]);
  runApp(const AfhApp());
}

class AfhApp extends StatefulWidget {
  const AfhApp({super.key});
  @override
  State<AfhApp> createState() => _AfhAppState();
}

class _AfhAppState extends State<AfhApp> with WidgetsBindingObserver {
  Pal _pal = Pal.pick();
  late String _lang = _language();
  late bool _onboarded = Settings.i.onboarded;
  late double _scale = Settings.i.textScale;
  late bool _locked = Settings.i.flag('lock');
  DateTime? _left;

  String _language() => arabic ? 'ar' : 'en';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    Settings.i.addListener(_changed);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    Settings.i.removeListener(_changed);
    super.dispose();
  }

  @override
  void didChangePlatformBrightness() => _changed();

  @override
  void didChangeLocales(List<Locale>? locales) => _changed();

  void _changed() {
    pickLanguage();
    final pal = Pal.pick();
    if (pal == _pal && _lang == _language() && _onboarded == Settings.i.onboarded && _scale == Settings.i.textScale) return;
    setState(() {
      _pal = pal;
      _lang = _language();
      _onboarded = Settings.i.onboarded;
      _scale = Settings.i.textScale;
    });
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    switch (state) {
      case AppLifecycleState.resumed:
        Notify.inFront = true;
        unawaited(Notify.clear());
        unawaited(Hubs.i.resume());
        if (Settings.i.flag('lock') && _left != null && DateTime.now().difference(_left!).inSeconds > 20) setState(() => _locked = true);
        _left = null;
      case AppLifecycleState.paused:
        Notify.inFront = false;
        _left = DateTime.now();
        Chats.i.flush();
        Hubs.i.pause();
      case AppLifecycleState.detached:
        Chats.i.flush();
      default:
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = _pal;
    return MaterialApp(
      key: ValueKey(_lang),
      title: 'AFH',
      debugShowCheckedModeBanner: false,
      theme: themeData(p),
      themeAnimationDuration: const Duration(milliseconds: 320),
      locale: locale,
      supportedLocales: const [Locale('en'), Locale('ar')],
      localizationsDelegates: const [GlobalMaterialLocalizations.delegate, GlobalWidgetsLocalizations.delegate, GlobalCupertinoLocalizations.delegate],
      builder: (context, child) {
        final mq = MediaQuery.of(context);
        final system = mq.textScaler.scale(16) / 16;
        return MediaQuery(
          data: mq.copyWith(textScaler: TextScaler.linear((system * _scale).clamp(.8, 1.6)), disableAnimations: mq.disableAnimations || Settings.i.calm),
          child: Look(
            pal: p,
            child: Stack(
              children: [
                child!,
                if (_locked) Positioned.fill(child: _Lock(onOpen: () => setState(() => _locked = false))),
              ],
            ),
          ),
        );
      },
      home: AnimatedSwitcher(
        duration: const Duration(milliseconds: 500),
        switchInCurve: Curves.easeOutQuint,
        child: _onboarded ? const Shell() : const Welcome(),
      ),
    );
  }
}

class _Lock extends StatefulWidget {
  const _Lock({required this.onOpen});
  final VoidCallback onOpen;
  @override
  State<_Lock> createState() => _LockState();
}

class _LockState extends State<_Lock> {
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _ask());
  }

  Future<void> _ask() async {
    if (_busy) return;
    _busy = true;
    try {
      if (await LocalAuthentication().authenticate(localizedReason: t('Unlock AFH'))) widget.onOpen();
    } on LocalAuthException catch (e) {
      // the phone's own lock was removed since: there is nothing left to check against
      if (e.code == LocalAuthExceptionCode.noCredentialsSet) widget.onOpen();
    } catch (_) {}
    _busy = false;
  }

  @override
  Widget build(BuildContext context) {
    final p = context.p;
    return Material(
      color: p.bg,
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(gutter),
          child: Column(
            children: [
              const Expanded(child: Center(child: AfhLogo(width: 110, intro: false))),
              Rise(0, child: Btn(t('Unlock'), icon: LucideIcons.lockKeyholeOpen, onTap: _ask)),
            ],
          ),
        ),
      ),
    );
  }
}
