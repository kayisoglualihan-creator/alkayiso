# Implementierungsstatus

Stand: 20.10.2026 · Version 0.4.0

Legende: **✅ getestet** = Code vorhanden und durch automatische Tests bzw. echten Lauf nachgewiesen ·
**🟡 implementiert, ungetestet** = Code vorhanden, aber in dieser Umgebung nicht ausführbar/prüfbar ·
**⛔ blockiert** = externe Voraussetzung fehlt · **⏳ offen** = noch nicht umgesetzt

## Wo wurde getestet?

| Umgebung | Was | Ergebnis |
|---|---|---|
| Linux-Entwicklungscontainer | 89 Backend-Tests (Unit + Integration mit echtem Serverprozess), Ruff-Lint | ✅ alle bestanden |
| Linux, Chromium (Playwright) | Weboberfläche Desktop (1440×900) + iPhone-13-Viewport: Chat, Aufgabe anlegen, Kopplung per Link mit Prüfnummernvergleich, Fernauftrag vom „iPhone“, Genehmigung ablehnen, PC-offline-Anzeige mit Cache | ✅ bestanden, keine JS-Fehler |
| Linux, Flutter 3.47.7 | `flutter analyze` (keine Befunde), `flutter test` (5 Tests) | ✅ |
| GitHub Actions `ubuntu-latest` (CI) | Backend-Tests, Lint, Flutter analyze/test | ✅ |
| GitHub Actions `windows-latest` | Backend-Tests **auf echtem Windows**, Fensterliste (user32), DPAPI-Verschlüsselung, Autostart-Befehl, **JARVIS.exe (PyInstaller) gebaut und gestartet** (Health-Check) | ✅ (siehe Windows-Build-Lauf) |
| GitHub Actions `windows-latest` | Flutter-Windows-App + Inno-Setup-Installer | siehe Abschnitt „CI-Ergebnisse“ unten |
| GitHub Actions `macos-latest` | iOS-App unsigniert kompilieren (inkl. Swift App Intents) | siehe Abschnitt „CI-Ergebnisse“ unten |

**Nicht** getestet wurde auf deinem realen PC/iPhone: echte Mikrofon-/Lautsprecher-Hardware, echtes Tailscale,
Installation auf einem iPhone, echte Claude-/OpenAI-/Ollama-Aufrufe (keine Schlüssel in der Umgebung –
die Adapter sind mit simulierten Antworten getestet).

## Phase 1 – Fundament

| Funktion | Status |
|---|---|
| FastAPI-Backend, SQLite mit Migrationen, Einstellungen, Fehlerformat | ✅ |
| Chat (REST + Server-Sent-Events), Unterhaltungsverlauf persistent | ✅ |
| KI-Provider: Claude (offizielles SDK, `claude-opus-5-5`, Effort, Ablehnungs-Fallback), OpenAI, Ollama | ✅ Adapter-Tests mit simulierten Antworten · 🟡 echte API-Aufrufe |
| Lokaler Basismodus ohne KI (deutsche/englische Befehle) | ✅ |
| Nutzungs- und Kostenübersicht | ✅ |

## Phase 2 – Sprache & Oberfläche

| Funktion | Status |
|---|---|
| Futuristisches Dashboard mit animiertem Core (Canvas, reagiert auf Zustände/Pegel) | ✅ (Browser-Test, Screenshots) |
| Spracheingabe Push-to-Talk + Sprachausgabe (Browser-APIs, unterbrechbar, Stimme/Tempo/Lautstärke) | 🟡 Code vorhanden, braucht echtes Mikrofon |
| Wake Word „Hey Jarvis“ im Browser (Dauererkennung) | 🟡 |
| Lokale Sprachschleife: openWakeWord → faster-whisper → Agent → Piper | ✅ Logik (Äußerungsende, Verarbeitung) · 🟡 mit echter Audio-Hardware |
| Server-STT/TTS-Endpunkte | ✅ Fehlerfall ohne Pakete · 🟡 mit installierten Paketen |

## Phase 3 – Computersteuerung

| Funktion | Status |
|---|---|
| Programme starten (Freigabeliste), beenden (geschützte Systemprozesse), Fenster auflisten/wechseln | ✅ Logik/Testmodus · ✅ Fensterliste auf Windows-Runner · 🟡 Programmstart auf deinem PC |
| Systemstatus (CPU, RAM, Laufwerke, Akku, Prozesse) | ✅ |
| Dateien suchen/lesen/verschieben/kopieren/Papierkorb mit Rückgängig, endgültig löschen (Stufe 3) | ✅ |
| PDF/Word/Excel lesen, Excel/Word erstellen, Zusammenfassen (KI oder lokal extraktiv), Projektübersicht | ✅ |
| Web: öffnen, Seite lesen (SSRF-Schutz), Suche (DuckDuckGo) | ✅ Lesen/Schutz · 🟡 Suche (Internet in Tests nicht genutzt) |
| Screenshot, Texteingabe (Modul standardmäßig aus) | 🟡 |
| PC sperren / herunterfahren (Stufe 2/3) | 🟡 nur Windows |
| Playwright-Browserautomatisierung (Formulare) | ⏳ |

## Phase 4 – Sicherer Fernzugriff

| Funktion | Status |
|---|---|
| Kopplung per QR (Einmalcode, Ablauf, Fehlversuch-Sperre, Prüfnummer, Bestätigung am PC) | ✅ |
| Kurzlebige Tokens, Refresh-Rotation, Wiederverwendungserkennung, sofortiger Widerruf, Fernzugriff-Schalter | ✅ |
| Admin-Token nur lokal (Proxy-/Tailscale-Header werden erkannt) | ✅ |
| Fernaufträge mit Statusmodell, Live-Updates (WebSocket + Long-Polling), Geräte-Isolation | ✅ |
| Tailscale-Statusprüfung, Funnel-Warnung, Serve-Skript | ✅ ohne Tailscale (Hinweis) · 🟡 mit echtem Tailscale |
| PC offline korrekt erkannt, keine spätere heimliche Ausführung | ✅ |

## Phase 5 – iPhone

| Funktion | Status |
|---|---|
| PWA (installierbar, Offline-Cache, Warteschlange für Aufgaben) | ✅ im iPhone-Viewport (Chromium) · 🟡 auf echtem Safari/iPhone |
| Native Flutter-App: Kopplung (QR-Scanner), Chat/Fernaufträge, Genehmigungen, Aufgaben, Gedächtnis, PC-Status, Sprache, Keychain | ✅ analyze/test · siehe CI-Ergebnis iOS-Build · 🟡 auf echtem Gerät |
| Siri/Kurzbefehle („Frag Jarvis“, „PC-Status“) per App Intents (Swift) | 🟡 (Kompilierung im iOS-Build) |
| Signierte Installation / TestFlight | ⛔ Apple-Developer-Konto + Zertifikate nötig (Anleitung: INSTALLATION_IPHONE.md) |
| Push-Benachrichtigungen bei geschlossener App (APNs) | ⛔ APNs-Schlüssel + Apple-Konto nötig · ⏳ |

## Phase 6 – Persönliche Intelligenz

| Funktion | Status |
|---|---|
| Langzeitgedächtnis: semantische Suche, Relevanz, Korrektur, Löschen, Komplettlöschung, Zusammenführen von Duplikaten, Abruf in den Kontext | ✅ |
| Schutz: keine Gedächtniseinträge aus nicht vertrauenswürdigen Inhalten | ✅ |
| Aufgaben, Erinnerungen (einmalig/täglich/werktags/wöchentlich), Listen, Gewohnheiten, Budget | ✅ |
| Automatisierungen (Zeitpläne, Workflows, KI-Aufträge, Tagesübersicht), Benachrichtigungen | ✅ |
| Kalender über iCal-Adressen inkl. Wiederholungen, Termine in der Tagesübersicht | ✅ |

## Phase 7 – Integrationen

| Funktion | Status |
|---|---|
| Home Assistant, n8n | 🟡 implementiert, nicht gegen echte Instanzen getestet |
| Gmail/Google Calendar (OAuth), Outlook/Microsoft Graph | ⛔ eigene OAuth-App-Registrierung nötig (siehe INTEGRATIONEN.md) |
| Messenger | ⛔ |

## Phase 8 – Auslieferung

| Funktion | Status |
|---|---|
| PyInstaller-Build JARVIS.exe | ✅ auf Windows-Runner gebaut und gestartet |
| Inno-Setup-Installer (pro Benutzer, Autostart-Option, Tailscale-Hinweis) | siehe CI-Ergebnis |
| Diagnosewerkzeug, Installations-/Start-/Testskripte, Dokumentation | ✅ |
| Codesignatur des Installers | ⛔ kostenpflichtiges Zertifikat (sonst SmartScreen-Hinweis) |

## Bekannte Einschränkungen

* Token-Streaming ist für Claude umgesetzt (Weboberfläche); OpenAI/Ollama liefern die Antwort pro Schritt.
* Lokale semantische Suche nutzt gehashte n-Gramm-Vektoren (kein neuronales Embedding) – gut für Wortvarianten, schwächer bei reinen Synonymen.
* Lokaler Basismodus versteht nur definierte Befehlsmuster; freie Gespräche erfordern Claude/OpenAI/Ollama.
* Kalenderzeiten mit TZID werden als lokale Zeit interpretiert.

## Nächste Schritte (Fortsetzungsanweisungen)

1. **Auf deinem PC:** Installer aus dem Windows-Build-Artefakt installieren, `JARVIS.exe --diagnose`, Claude-Schlüssel eintragen, Tailscale + `tailscale_serve.ps1`, iPhone per PWA koppeln. Rückmeldungen → Fehler beheben.
2. Apple-Developer-Konto → Secrets hinterlegen → iOS-Build liefert TestFlight-IPA.
3. Token-Streaming auch für OpenAI/Ollama und in der Flutter-App (dort aktuell Fernaufträge mit Statusabfrage).
4. Google/Microsoft OAuth (Loopback-Flow) → E-Mail-Werkzeuge (Senden = Stufe 3) und Kalender schreiben.
5. Playwright-Werkzeug für Formulare (Stufe 2, Vorschau-Screenshot vor dem Absenden).
6. APNs-Push (benötigt Apple-Schlüssel; Relay nötig, da der PC selbst Push nicht direkt auslösen sollte ohne Zertifikat).
7. Optionale neuronale Embeddings über Ollama (`nomic-embed-text`) als zweiter Embedder.

Einstieg für Entwickler: `documentation/ARCHITEKTUR.md`; Tests: `scripts/run_tests.sh`.
