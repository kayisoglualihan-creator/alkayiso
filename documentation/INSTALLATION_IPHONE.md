# Jarvis auf dem iPhone

Es gibt zwei Wege. **Sofort nutzbar** ist die Web-App (PWA). Die **native App** braucht einen
Apple-Build (Mac oder Mac-Cloud-Runner) und für die Installation ein Apple-Entwicklerkonto.

## Weg 1 – Web-App (PWA) – sofort, ohne Mac

Voraussetzung: Tailscale eingerichtet ([TAILSCALE.md](TAILSCALE.md)).

1. Am PC den Kopplungs-QR-Code anzeigen, mit der **iPhone-Kamera** scannen → Safari öffnet Jarvis.
2. Prüfnummer vergleichen, am PC bestätigen.
3. In Safari: **Teilen → „Zum Home-Bildschirm“**. Jarvis erscheint als App-Symbol im Vollbild.

Funktionen: Chat, Fernaufträge mit Live-Status, Genehmigungen, Aufgaben/Erinnerungen/Listen, Gedächtnis,
PC-Status, Verlauf, Spracheingabe (Safari-Spracherkennung) und Sprachausgabe, Offline-Anzeige mit Cache.
Grenzen der PWA: Zugangsdaten liegen im Web-Speicher (nicht im Keychain), keine Siri-Kurzbefehle,
Push-Benachrichtigungen nur mit eingerichtetem Web-Push (nicht Bestandteil dieser Version).

## Weg 2 – Native iPhone-App (Flutter + Swift)

Quellcode: `apps/jarvis_app` (Flutter) mit nativen Swift-Erweiterungen in
`ios/Runner/AppDelegate.swift` (Siri/Kurzbefehle: „Frag Jarvis“, „PC-Status in Jarvis“).
Zugangsdaten werden im **iOS-Keychain** gespeichert (nur dieses Gerät).

### Was unter Windows geht – und was nicht

* ✅ Code schreiben, `flutter analyze`, `flutter test`, Windows-Desktop-Version bauen
* ❌ iOS-App **kompilieren, signieren und installieren** – das erfordert macOS mit Xcode (Apple-Vorgabe).

Deshalb gibt es den GitHub-Actions-Workflow **„iOS-Build“** (macOS-Runner):
* **Ohne** Apple-Zugangsdaten: unsignierter Build = Kompilierprüfung (nicht installierbar).
* **Mit** Zugangsdaten: signierte IPA → Upload zu TestFlight.

### Voraussetzungen für die Installation auf deinem iPhone

1. **Apple Developer Program** (99 USD/Jahr): https://developer.apple.com/programs/ – nötig für TestFlight.
   (Kostenlos geht nur das direkte Installieren per Kabel von einem Mac aus, Gültigkeit 7 Tage.)
2. In *Certificates, Identifiers & Profiles*:
   * App-ID `de.jarvis.jarvisApp` anlegen (Capability: *Siri* nicht nötig für App Intents).
   * **Apple-Distribution-Zertifikat** erstellen und als `.p12` exportieren.
   * **App-Store-Provisioning-Profil** „JARVIS App Store“ für die App-ID erstellen.
3. In *App Store Connect* eine App mit der Bundle-ID anlegen.
4. GitHub → *Settings → Secrets and variables → Actions* folgende Secrets anlegen:
   * `APPLE_CERT_P12` – Inhalt der .p12 als Base64 (`[Convert]::ToBase64String([IO.File]::ReadAllBytes("cert.p12"))`)
   * `APPLE_CERT_PASSWORD` – Passwort der .p12
   * `APPLE_PROVISIONING_PROFILE` – Profil als Base64
5. In `apps/jarvis_app/ios/ExportOptions.plist` `TEAM_ID` ersetzen.
6. Workflow „iOS-Build“ starten → Artefakt `.ipa` → mit **Transporter** (App Store) bzw. `xcrun altool` hochladen →
   in TestFlight dich selbst als Tester eintragen → App „TestFlight“ auf dem iPhone → Jarvis installieren.

### Alternative mit Mac

```bash
cd apps/jarvis_app && flutter pub get && open ios/Runner.xcworkspace
```
In Xcode unter *Signing & Capabilities* dein Team wählen, iPhone per Kabel verbinden, ▶ Run.

### Berechtigungen der App

| Berechtigung | Wofür |
|---|---|
| Kamera | nur zum Scannen des Kopplungs-QR-Codes |
| Mikrofon + Spracherkennung | nur während du die Mikrofontaste drückst |
| Lokales Netzwerk | Verbindung über Tailscale |

### iOS-Einschränkungen (ehrlich)

* Kein dauerhaftes systemweites „Hey Jarvis“ im Hintergrund – iOS erlaubt das Drittanbieter-Apps nicht.
  Stattdessen: **Siri-Kurzbefehl „Frag Jarvis“**, Push-to-Talk in der App, Kurzbefehle-App, Action-Button (iPhone 15 Pro+).
* Hintergrund-Ausführung ist begrenzt; die App aktualisiert sich beim Öffnen. Benachrichtigungen bei
  geschlossener App erfordern Apple Push Notification Service mit Server-Zertifikat (noch nicht eingerichtet).
