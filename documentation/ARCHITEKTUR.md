# Architektur

```
backend/jarvis/
├── __main__.py          Start: Server, --tray (Infobereich), --open, --autostart, --diagnose
├── config.py            Einstellungen (.env, JARVIS_*), Datenordner %LOCALAPPDATA%\Jarvis
├── core.py              Jarvis-Klasse: verbindet alle Dienste, Provider-Auswahl, Undo, Nutzung
├── database/            SQLite + Migrationssystem (PRAGMA user_version)
├── security/
│   ├── tokens.py        Zugangstokens (HMAC), Refresh-Rotation, Widerruf
│   ├── pairing.py       QR-Kopplung mit Einmalcode und Prüfnummer
│   ├── permissions.py   Risikostufen, Dauerfreigaben, Taint-Regel, Genehmigungen (mit Ablauf)
│   └── secrets.py       Credential Manager / DPAPI / Keyring
├── ai/
│   ├── providers.py     Anthropic (offizielles SDK), OpenAI(-kompatibel), Ollama
│   ├── offline.py       Lokaler Basismodus (regelbasiert, ohne LLM)
│   └── agent.py         Agenten-Schleife: Kontext, Gedächtnisabruf, Werkzeuge, Genehmigungen, Audit
├── tools/               Werkzeug-Registry + System/Programme/Fenster, Dateien/Dokumente, Web, Persönliches
├── memory/              Langzeitgedächtnis mit lokaler semantischer Suche (gehashte n-Gramm-Vektoren)
├── automation/          Scheduler: Erinnerungen, Zeitpläne, Workflows, Tagesübersicht
├── jobs.py              Fernaufträge mit Statusmodell
├── services.py          Aufgaben, Erinnerungen, Listen, Gewohnheiten, Budget, Benachrichtigungen
├── voice/               STT (faster-whisper), TTS (Piper/ElevenLabs), Wake Word (openWakeWord)
├── integrations/        Home Assistant, n8n
├── network.py           Tailscale-Status
├── windows_agent/       Autostart (HKCU Run), Infobereich (pystray), App-Fenster
├── api/                 FastAPI: REST, SSE (/api/chat/stream), WebSocket (/ws)
├── web/                 Desktop-Dashboard + PWA (HTML/CSS/JS ohne Build-Schritt)
├── client.py            Python-Client / Kommandozeilen-Fernbedienung
└── diagnose.py          Fehlerdiagnose

apps/jarvis_app/         Flutter (iOS + Windows): lib/ (Dart), ios/Runner/AppDelegate.swift (App Intents)
installers/              PyInstaller-Spezifikation, Inno-Setup-Skript, Icon
scripts/                 install.ps1, start.ps1, tailscale_serve.ps1, run_tests.*
.github/workflows/       CI (Linux), Windows-Build mit Installer, iOS-Build (macOS)
```

## Ablauf eines Fernauftrags

1. iPhone `POST /api/jobs {"text": …}` mit Bearer-Zugangstoken → Status **Wartend**.
2. `JobManager` startet den Agenten (Quelle `device:<id>`) → **In Bearbeitung**.
3. Agent fragt das Modell; bei Werkzeugaufruf prüft `PermissionPolicy` Stufe, Freigaben, Taint und Fernsperre.
4. Genehmigungspflichtig → `approvals`-Eintrag, Status **Genehmigung erforderlich**, Event per WebSocket.
   Entscheidung am PC oder auf dem anfragenden iPhone; ohne Entscheidung nach 5 min verworfen.
5. Werkzeug läuft in der Benutzersitzung, Ergebnis + Audit-Eintrag.
6. Antwort → **Erfolgreich** / **Fehlgeschlagen**, Benachrichtigung; das iPhone erhält das Ergebnis per
   Long-Polling (`GET /api/jobs/{id}?wait=20`) und WebSocket.
7. Nicht erreichbarer PC → Client meldet **PC offline**; nichts wird zwischengespeichert und später ausgeführt.

## Datenmodell (SQLite)

`settings, devices, pairings, conversations, messages, memories, tasks, reminders, automations, jobs,
approvals, audit, notifications, usage, undo_log, list_items, habits, habit_log, budget_entries`.
Neue Tabellen werden als zusätzliche Migration in `database/__init__.py` angehängt.

## Ein neues Werkzeug hinzufügen

```python
@reg.tool("name", "Beschreibung für das Modell", params({...}, ["pflicht"]), LEVEL_CHANGE, module="files",
          summarize=lambda a: "Text für die Genehmigungsanzeige")
def name(ctx: ToolContext, pflicht: str) -> ToolResult:
    return ToolResult("Ergebnis", data, untrusted=False)
```
Berechtigungen, Genehmigungen, Audit-Log, Fernsperre und UI-Verwaltung greifen automatisch.
