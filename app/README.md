# AFH for your phone

The AFH app for Android and iPhone, built with Flutter. Version 2 was written from scratch.

- `lib/core/` is everything that isn't a screen: model providers and streaming (`ai.dart`), the phone's
  tools (`tools.dart`), chats and settings (`store.dart`), the account and the relay (`relay.dart`), one
  live line per computer (`hub.dart`), notifications and the background line (`native.dart`), voice,
  and the Arabic texts (`l10n_ar.dart`).
- `lib/ui/` is the design system: colors and type (`look.dart`), parts (`kit.dart`), motion, markdown,
  diffs and media.
- `lib/screens/` is one file per area: Home, Chats, Threads, a thread, a computer, new work, talking, You.

Keys live in the system keystore or keychain, chats in the app's own folder. The relay passes
`/r/<computer>/...` to that computer's AFH, and `/api/events` streams its live events.

## Build

```
flutter pub get
flutter build apk --release      # signed with ~/.afh-signing/keystore.properties when present
```

The iPhone build runs on GitHub Actions (`.github/workflows/ios.yml`) and produces an unsigned
`.ipa` for AltStore or Sideloadly.

The version comes from `pubspec.yaml` (`2.0.0+20000` is versionName 2.0.0, versionCode 20000).
