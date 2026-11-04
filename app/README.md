# AFH for your phone

The AFH app for Android and iPhone, built with Flutter. Two halves, plus tools for the assistant:

- **Chats** — talk to model providers straight from the phone with the user's own API keys
  (`lib/ai.dart`: OpenAI-compatible, Anthropic and Gemini streaming). Keys live in the system
  keystore/keychain, chats in the app's own folder (`lib/store.dart`).
- **Computers** — remote control of AFH on the user's computers through the AFH account server
  (`lib/remote.dart`): the relay passes `/r/<computer>/…` to that computer's AFH, and `/api/events`
  streams its live events.

## Build

```
flutter pub get
flutter build apk --release      # signed with ~/.afh-signing/keystore.properties when present
```

The iPhone build runs on GitHub Actions (`.github/workflows/ios.yml`) and produces an unsigned
`.ipa` for AltStore or Sideloadly.

The version comes from `pubspec.yaml` (`1.10.0+11000` → versionName 1.10.0, versionCode 11000).
