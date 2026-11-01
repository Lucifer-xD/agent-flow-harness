import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'ai.dart';
import 'screens/onboarding.dart';
import 'screens/home.dart';
import 'store.dart';
import 'theme.dart';

const appVersion = '1.11.0';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
  await Settings.i.load();
  await loadProviders();
  await Chats.i.load();
  pickPalette();
  runApp(const AfhApp());
}

/// Sets Afh.p from the appearance settings and the phone's light/dark setting.
void pickPalette() {
  final s = Settings.i;
  final dark = switch (s.themeMode) {
    'dark' => true,
    'light' => false,
    _ => WidgetsBinding.instance.platformDispatcher.platformBrightness == Brightness.dark,
  };
  Afh.p = Palette.byId(dark ? s.darkTheme : s.lightTheme, dark: dark);
  SystemChrome.setSystemUIOverlayStyle(Afh.overlay);
}

class AfhApp extends StatefulWidget {
  const AfhApp({super.key});
  @override
  State<AfhApp> createState() => _AfhAppState();
}

class _AfhAppState extends State<AfhApp> with WidgetsBindingObserver {
  String _shown = Afh.p.id;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    Settings.i.addListener(_restyle);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    Settings.i.removeListener(_restyle);
    super.dispose();
  }

  @override
  void didChangePlatformBrightness() => _restyle();

  // The colours are read from Afh.p while building, so a new theme redraws every widget in place
  // (keeping the pages that are open) instead of rebuilding the app.
  void _restyle() {
    pickPalette();
    if (Afh.p.id == _shown) return;
    _shown = Afh.p.id;
    setState(() {});
    void dirty(Element e) {
      e.markNeedsBuild();
      e.visitChildren(dirty);
    }

    (context as Element).visitChildren(dirty);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // write any chat still waiting for its debounced save before the system may stop the app
    if (state == AppLifecycleState.paused || state == AppLifecycleState.detached) Chats.i.flush();
  }

  @override
  Widget build(BuildContext context) {
    final t = Afh.theme();
    return MaterialApp(
      title: 'AFH',
      debugShowCheckedModeBanner: false,
      theme: t,
      darkTheme: t,
      themeMode: Afh.p.dark ? ThemeMode.dark : ThemeMode.light,
      themeAnimationDuration: Afh.med,
      builder: (context, child) => AnnotatedRegion<SystemUiOverlayStyle>(value: Afh.overlay, child: child!),
      home: Settings.i.onboarded ? const Home() : const Onboarding(),
    );
  }
}
