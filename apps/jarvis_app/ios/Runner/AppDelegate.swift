import AppIntents
import Flutter
import Foundation
import Security
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
  }
}

// MARK: - Siri / Kurzbefehle (App Intents)
//
// "Hey Siri, frag Jarvis" bzw. Kurzbefehle-App -> Auftrag an den PC senden, Ergebnis vorlesen.
// Nutzt die von der Flutter-App im Schlüsselbund gespeicherte Kopplung (flutter_secure_storage).
// Für kritische Aktionen verlangt der PC weiterhin eine Bestätigung in der App.

enum JarvisKeychain {
  static let service = "flutter_secure_storage_service"

  static func read(_ key: String) -> String? {
    let query: [String: Any] = [
      kSecClass as String: kSecClassGenericPassword,
      kSecAttrService as String: service,
      kSecAttrAccount as String: key,
      kSecReturnData as String: true,
      kSecMatchLimit as String: kSecMatchLimitOne,
    ]
    var item: CFTypeRef?
    guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess, let data = item as? Data else { return nil }
    return String(data: data, encoding: .utf8)
  }

  static func write(_ key: String, _ value: String) {
    let query: [String: Any] = [
      kSecClass as String: kSecClassGenericPassword,
      kSecAttrService as String: service,
      kSecAttrAccount as String: key,
    ]
    let attrs: [String: Any] = [kSecValueData as String: Data(value.utf8)]
    SecItemUpdate(query as CFDictionary, attrs as CFDictionary)
  }
}

enum JarvisRemoteError: Error, CustomLocalizedStringResourceConvertible {
  case notPaired, offline, server(String)
  var localizedStringResource: LocalizedStringResource {
    switch self {
    case .notPaired: return "Jarvis ist noch nicht mit deinem PC gekoppelt. Öffne die Jarvis-App."
    case .offline: return "Dein PC ist nicht erreichbar."
    case .server(let m): return LocalizedStringResource(stringLiteral: m)
    }
  }
}

struct JarvisRemote {
  let base: String
  let deviceId: String

  static func load() throws -> JarvisRemote {
    guard let base = JarvisKeychain.read("jarvis_base_url"), let dev = JarvisKeychain.read("jarvis_device_id") else {
      throw JarvisRemoteError.notPaired
    }
    return JarvisRemote(base: base, deviceId: dev)
  }

  private func call(_ method: String, _ path: String, body: [String: Any]? = nil, token: String? = nil, timeout: TimeInterval = 30) async throws -> [String: Any] {
    var req = URLRequest(url: URL(string: base + path)!, timeoutInterval: timeout)
    req.httpMethod = method
    if let token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
    if let body {
      req.setValue("application/json", forHTTPHeaderField: "Content-Type")
      req.httpBody = try JSONSerialization.data(withJSONObject: body)
    }
    let data: Data, resp: URLResponse
    do { (data, resp) = try await URLSession.shared.data(for: req) } catch { throw JarvisRemoteError.offline }
    let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
    if let http = resp as? HTTPURLResponse, http.statusCode >= 400 {
      let msg = (json["error"] as? [String: Any])?["message"] as? String ?? "Fehler \(http.statusCode)"
      throw JarvisRemoteError.server(msg)
    }
    return json
  }

  /// Access-Token holen (Refresh-Token rotiert und wird zurückgeschrieben).
  func accessToken() async throws -> String {
    guard let refresh = JarvisKeychain.read("jarvis_refresh_token") else { throw JarvisRemoteError.notPaired }
    let out = try await call("POST", "/api/auth/refresh", body: ["device_id": deviceId, "refresh_token": refresh])
    if let newRefresh = out["refresh_token"] as? String { JarvisKeychain.write("jarvis_refresh_token", newRefresh) }
    guard let access = out["access_token"] as? String else { throw JarvisRemoteError.server("Anmeldung fehlgeschlagen") }
    return access
  }

  func run(_ text: String) async throws -> String {
    let token = try await accessToken()
    var job = try await call("POST", "/api/jobs", body: ["text": text], token: token)
    let id = job["id"] as? String ?? ""
    for _ in 0..<3 {
      job = try await call("GET", "/api/jobs/\(id)?wait=20", token: token, timeout: 35)
      let status = job["status"] as? String ?? ""
      switch status {
      case "succeeded":
        return ((job["result"] as? [String: Any])?["text"] as? String) ?? "Erledigt."
      case "failed", "cancelled":
        return ((job["result"] as? [String: Any])?["text"] as? String) ?? (job["error"] as? String ?? "Der Auftrag ist fehlgeschlagen.")
      case "approval_required":
        return "Für diese Aktion ist deine Bestätigung nötig. Bitte öffne die Jarvis-App."
      default:
        continue
      }
    }
    return "Der Auftrag läuft noch. Das Ergebnis findest du in der Jarvis-App."
  }
}

@available(iOS 16.0, *)
struct AskJarvisIntent: AppIntent {
  static var title: LocalizedStringResource = "Jarvis fragen"
  static var description = IntentDescription("Sendet einen Auftrag an Jarvis auf deinem PC und liest das Ergebnis vor.")
  static var openAppWhenRun = false

  @Parameter(title: "Auftrag", requestValueDialog: "Was soll ich auf deinem PC erledigen?")
  var request: String

  func perform() async throws -> some IntentResult & ProvidesDialog & ReturnsValue<String> {
    let answer = try await JarvisRemote.load().run(request)
    return .result(value: answer, dialog: IntentDialog(stringLiteral: answer))
  }
}

@available(iOS 16.0, *)
struct PcStatusIntent: AppIntent {
  static var title: LocalizedStringResource = "PC-Status von Jarvis"
  static var openAppWhenRun = false

  func perform() async throws -> some IntentResult & ProvidesDialog {
    let answer = try await JarvisRemote.load().run("Wie hoch ist die CPU-Auslastung meines Computers?")
    return .result(dialog: IntentDialog(stringLiteral: answer))
  }
}

@available(iOS 16.0, *)
struct JarvisShortcuts: AppShortcutsProvider {
  static var appShortcuts: [AppShortcut] {
    AppShortcut(intent: AskJarvisIntent(), phrases: ["Frag \(.applicationName)", "\(.applicationName) Auftrag"],
                shortTitle: "Jarvis fragen", systemImageName: "waveform.circle")
    AppShortcut(intent: PcStatusIntent(), phrases: ["PC-Status in \(.applicationName)", "Wie geht es meinem PC mit \(.applicationName)"],
                shortTitle: "PC-Status", systemImageName: "desktopcomputer")
  }
}
