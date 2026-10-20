# J.A.R.V.I.S. – Just A Rather Very Intelligent System

Persönlicher KI-Assistent für **Windows-PC** und **iPhone** – mit sicherer Fernsteuerung über Tailscale,
Sprachsteuerung, Langzeitgedächtnis, Automatisierungen und einem futuristischen HUD-Interface.

> **Aktueller Stand:** siehe [`documentation/STATUS.md`](documentation/STATUS.md) – dort steht ehrlich,
> was implementiert, getestet, ungetestet oder durch externe Voraussetzungen blockiert ist.

## Komponenten

| Komponente | Technik | Ordner |
|---|---|---|
| **JARVIS CORE** – KI-Kern, API, Sicherheit, Gedächtnis, Werkzeuge, Automatisierung | Python 3.12, FastAPI, SQLite | `backend/jarvis/` |
| **JARVIS DESKTOP** – Dashboard mit animiertem Core, Chat, Sprache, Genehmigungen, Setup | Web-Oberfläche im App-Fenster (Edge/Chrome `--app`) + Infobereich; zusätzlich Flutter-Windows-App | `backend/jarvis/web/`, `apps/jarvis_app/` |
| **JARVIS MOBILE** – iPhone-Fernbedienung | Native Flutter-iOS-App mit Siri-Kurzbefehlen **und** installierbare Web-App (PWA) als Sofortlösung | `apps/jarvis_app/`, `backend/jarvis/web/` |

```
iPhone (App / PWA) ──► Tailscale (privat, WireGuard) ──► Tailscale Serve (HTTPS) ──► 127.0.0.1:8765 JARVIS CORE
                                                                                         │
                         Geräte-Token (15 min) + Refresh-Rotation + Widerruf ◄───────────┤
                         Berechtigungsstufen 1-3 + Genehmigungen + Audit-Log ◄───────────┤
                                                                                         ▼
                                                              Werkzeuge: Programme, Dateien, Dokumente,
                                                              Browser/Web, System, Aufgaben, Gedächtnis …
```

## Schnellstart (Windows)

1. **Installer** (empfohlen): `JARVIS-Setup-x.y.z.exe` aus den GitHub-Actions-Artefakten
   (*Actions → Windows-Build → Artefakt „JARVIS-Windows-Installer“*) ausführen.
   **Oder aus dem Quellcode:** Python 3.12 installieren, dann in PowerShell im Projektordner:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Autostart
   scripts\start.ps1
   ```
2. Jarvis öffnet sich als App-Fenster. Ohne API-Schlüssel läuft der **lokale Basismodus**
   (Befehle wie „Öffne VS Code“, „CPU-Auslastung“, „Neue Aufgabe … morgen 9 Uhr“, „Fasse die neueste PDF zusammen“).
3. Für freie Gespräche: **Setup → KI-Modell** → Claude, OpenAI oder Ollama wählen und Schlüssel speichern.
4. iPhone verbinden: [`documentation/TAILSCALE.md`](documentation/TAILSCALE.md) und
   [`documentation/INSTALLATION_IPHONE.md`](documentation/INSTALLATION_IPHONE.md).

## Dokumentation

* [Installation Windows](documentation/INSTALLATION_WINDOWS.md)
* [Installation iPhone (App, TestFlight, PWA)](documentation/INSTALLATION_IPHONE.md)
* [Tailscale & sicherer Fernzugriff](documentation/TAILSCALE.md)
* [Sicherheitskonzept](documentation/SICHERHEIT.md)
* [Architektur](documentation/ARCHITEKTUR.md)
* [API-Referenz](documentation/API.md) (live: `http://127.0.0.1:8765/docs`)
* [Integrationen (E-Mail, Kalender, Smart Home, n8n)](documentation/INTEGRATIONEN.md)
* [Fehlerdiagnose](documentation/FEHLERDIAGNOSE.md)
* [Implementierungsstatus & nächste Schritte](documentation/STATUS.md)

## Entwicklung

```bash
scripts/run_tests.sh          # Linux/macOS: Backend-Tests + Flutter analyze/test
scripts\run_tests.ps1         # Windows
python -m jarvis --diagnose   # Umgebung prüfen (im Ordner backend/)
```
