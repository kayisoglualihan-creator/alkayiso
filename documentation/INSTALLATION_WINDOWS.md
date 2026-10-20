# Installation unter Windows 10/11

## Variante A – Installer (empfohlen, keine Programmierkenntnisse nötig)

1. Auf GitHub: **Actions → „Windows-Build (Installer)“ → letzter grüner Lauf → Artefakt `JARVIS-Windows-Installer`** herunterladen und entpacken.
2. `JARVIS-Setup-0.4.0.exe` doppelklicken. Es werden **keine Administratorrechte** benötigt
   (Installation nach `%LOCALAPPDATA%\Programs\JARVIS`).
   *Hinweis:* Da der Installer nicht mit einem kostenpflichtigen Codesignatur-Zertifikat signiert ist, zeigt
   Windows SmartScreen evtl. „Unbekannter Herausgeber“ → *Weitere Informationen → Trotzdem ausführen*.
3. Optionen im Assistenten: **Autostart beim Login** und **Desktop-Verknüpfung**.
4. Jarvis startet mit Symbol im Infobereich (Taskleiste, rechts unten) und öffnet das Dashboard.
   Fehlt Tailscale, weist der Installer darauf hin.

## Variante B – aus dem Quellcode

```powershell
winget install Python.Python.3.12
git clone <repo> JARVIS; cd JARVIS
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Autostart   # optional: -Voice
scripts\start.ps1
```

## Ersteinrichtung (deutschsprachig, in der Oberfläche unter „Setup“)

| Schritt | Wo | Hinweis |
|---|---|---|
| KI-Anbieter wählen | Setup → KI-Modell | Claude (`claude-opus-5-5`), OpenAI, Ollama (lokal) oder lokaler Basismodus |
| API-Schlüssel | Setup → API-Schlüssel | gespeichert im Windows-Anmeldeinformationsspeicher, nie im Klartext angezeigt |
| Verbindung testen | Setup → „Verbindung testen“ | sendet eine Mini-Anfrage an das Modell |
| Freigegebene Ordner | Setup → Freigegebene Ordner | Jarvis greift **nur** auf diese Ordner zu |
| Module | Setup → Module | z. B. Bildschirm/Tastatur, Smart Home, n8n ein-/ausschalten |
| Berechtigungen | Setup → Berechtigungen | pro Werkzeug: Standard / Automatisch / Immer fragen / Gesperrt |
| Mikrofon & Stimme | Setup → Sprache, Core-Ansicht | Browser-Spracherkennung (Edge/Chrome) oder lokal (faster-whisper) |
| Tailscale & iPhone | PC → iPhone verbinden | siehe TAILSCALE.md |
| Autostart | Infobereich-Menü → „Autostart beim Login“ | Registry `HKCU\…\Run` (nur aktueller Benutzer) |

## Optionale lokale Sprachdienste

```powershell
.venv\Scripts\pip install -r backend\requirements-voice.txt
```
* **faster-whisper** (Spracherkennung, lokal) – lädt beim ersten Gebrauch das Modell `small` (~460 MB).
* **Piper** (Sprachausgabe, lokal) – deutsche Stimme herunterladen, z. B. `de_DE-thorsten-high.onnx` + `.onnx.json`
  von https://huggingface.co/rhasspy/piper-voices, nach `%LOCALAPPDATA%\Jarvis\voices\` legen.
* **openWakeWord** – „Hey Jarvis“ ohne Browser: *Setup → Sprache → „Hey Jarvis“ lokal am PC*.

Ohne diese Pakete funktioniert Sprache trotzdem über die Browser-Sprach-APIs (Edge/Chrome).

## Warum kein Windows-Dienst?

Jarvis läuft bewusst als Programm in **deiner angemeldeten Sitzung** (Autostart beim Login), nicht als
Windows-Dienst: Dienste laufen in „Session 0“ und können weder Fenster steuern noch Programme sichtbar
auf deinem Desktop starten (Session-0-Isolation). Beim Schließen des Fensters läuft Jarvis im Infobereich weiter.

## Deinstallation

*Einstellungen → Apps → J.A.R.V.I.S. → Deinstallieren*. Deine Daten (Gedächtnis, Aufgaben) bleiben in
`%LOCALAPPDATA%\Jarvis` und können dort manuell gelöscht werden.
