import Flutter
import UIKit

@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  func didInitializeImplicitFlutterEngine(_ engineBridge: FlutterImplicitEngineBridge) {
    GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)
    // a picture copied in another app, for "Paste the copied picture"
    FlutterMethodChannel(name: "afh/clipboard", binaryMessenger: engineBridge.applicationRegistrar.messenger())
      .setMethodCallHandler { call, result in
        switch call.method {
        case "has": result(UIPasteboard.general.hasImages)
        case "get":
          if let data = UIPasteboard.general.image?.jpegData(compressionQuality: 0.88) {
            result(FlutterStandardTypedData(bytes: data))
          } else {
            result(nil)
          }
        default: result(FlutterMethodNotImplemented)
        }
      }
    FlutterMethodChannel(name: "afh/keyboard", binaryMessenger: engineBridge.applicationRegistrar.messenger())
      .setMethodCallHandler { _, result in
        for case let scene as UIWindowScene in UIApplication.shared.connectedScenes {
          for window in scene.windows { window.endEditing(true) }
        }
        result(nil)
      }
  }
}
