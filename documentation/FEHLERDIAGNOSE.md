# Fehlerdiagnose

Zuerst: `JARVIS.exe --diagnose` (Installer) bzw. `python -m jarvis --diagnose` im Ordner `backend`.
Protokolldatei der Installer-Version: `%LOCALAPPDATA%\Jarvis\jarvis.log`.

| Problem | Ursache / Lösung |
|---|---|
| Oberfläche zeigt „Bitte Jarvis über das Startmenü öffnen“ | Das lokale Admin-Token wird beim Start übergeben. Jarvis über Startmenü/Infobereich öffnen (nicht die Adresse manuell eintippen). |
| „Port 8765 belegt“ | Jarvis läuft schon (Infobereich prüfen) oder ein anderes Programm nutzt den Port → `--port 8770` und `JARVIS_PORT` setzen. |
| iPhone: „PC offline“ | PC aus/Ruhezustand, Jarvis nicht gestartet, Tailscale auf PC oder iPhone getrennt, Serve nicht eingerichtet. Test im iPhone-Safari: `https://<pc>.<tailnet>.ts.net/api/health`. |
| Kopplung: „tailscale_required“ | Zugriff kam nicht über Tailscale Serve. `scripts\tailscale_serve.ps1` ausführen und die `https://…ts.net`-Adresse verwenden. |
| Kopplung: „Kopplung nicht mehr offen“ | QR-Code abgelaufen (5 min) oder bereits benutzt → neuen QR-Code erzeugen. |
| iPhone: „Gerät wurde widerrufen“ | Am PC entfernt oder alter Refresh-Token wiederverwendet → neu koppeln. |
| KI antwortet nur im Basismodus | Kein/ungültiger API-Schlüssel → Setup → „Verbindung testen“. Bei Ollama: `ollama serve` läuft? Modell geladen (`ollama pull qwen2.5:7b`)? |
| „Programm ist nicht freigegeben“ | Nur Programme aus der Freigabeliste. Eigene Einträge über Einstellung `app_aliases`. |
| „Zugriff verweigert: … außerhalb der freigegebenen Ordner“ | Setup → Freigegebene Ordner ergänzen. |
| Spracherkennung reagiert nicht | Mikrofonberechtigung im Browser/Windows (*Einstellungen → Datenschutz → Mikrofon*). Edge/Chrome verwenden. |
| Wake Word lokal: „wakeword_unavailable“ | `pip install -r backend\requirements-voice.txt` |
| Aktion „abgelaufen“ | Genehmigungen verfallen nach 5 Minuten (Sicherheitsfunktion) → Befehl erneut senden. |
| SmartScreen warnt beim Installer | Installer ist nicht kommerziell signiert → „Weitere Informationen → Trotzdem ausführen“. |

Datenordner zurücksetzen (löscht Gedächtnis, Aufgaben, Kopplungen): Jarvis beenden, `%LOCALAPPDATA%\Jarvis` umbenennen.
