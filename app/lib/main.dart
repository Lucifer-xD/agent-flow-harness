import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'screens/onboarding.dart';
import 'screens/shell.dart';
import 'store.dart';
import 'theme.dart';

const appVersion = '1.10.0';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
  SystemChrome.setSystemUIOverlayStyle(
    const SystemUiOverlayStyle(
      statusBarColor: Colors.transparent,
      statusBarIconBrightness: Brightness.light,
      statusBarBrightness: Brightness.dark,
      systemNavigationBarColor: Colors.transparent,
      systemNavigationBarDividerColor: Colors.transparent,
      systemNavigationBarIconBrightness: Brightness.light,
      systemNavigationBarContrastEnforced: false,
    ),
  );
  await Settings.i.load();
  await Chats.i.load();
  runApp(const AfhApp());
}

class AfhApp extends StatefulWidget {
  const AfhApp({super.key});
  @override
  State<AfhApp> createState() => _AfhAppState();
}

class _AfhAppState extends State<AfhApp> with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // write any chat still waiting for its debounced save before the system may stop the app
    if (state == AppLifecycleState.paused || state == AppLifecycleState.detached) Chats.i.flush();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AFH',
      debugShowCheckedModeBanner: false,
      theme: Afh.theme(),
      darkTheme: Afh.theme(),
      themeMode: ThemeMode.dark,
      home: Settings.i.onboarded ? const Shell() : const Onboarding(),
    );
  }
}
