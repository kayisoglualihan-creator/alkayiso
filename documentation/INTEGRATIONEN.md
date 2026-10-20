# Integrationen

Alle Module lassen sich unter *Setup → Module* einzeln aktivieren/deaktivieren.

| Modul | Status | Einrichtung |
|---|---|---|
| Programme, Fenster, System | ✅ implementiert | Freigabeliste erweiterbar über Einstellung `app_aliases` (z. B. `{"obsidian": ["C:\\…\\Obsidian.exe"]}`) |
| Dateien & Dokumente (PDF, Word, Excel, Text) | ✅ implementiert | freigegebene Ordner unter Setup |
| Browser/Web (öffnen, lesen, suchen) | ✅ implementiert | Websuche über DuckDuckGo-HTML (best effort, kann sich ändern) |
| Aufgaben, Erinnerungen, Listen, Gewohnheiten, Budget | ✅ implementiert | – |
| Automatisierungen & Workflows | ✅ implementiert | *Abläufe* |
| Home Assistant (Smart Home) | ✅ implementiert, ungetestet gegen echte Instanz | Setup: `home_assistant_url` (per API `PATCH /api/settings`), Long-Lived-Token als Schlüssel `home_assistant_token` |
| n8n | ✅ implementiert, ungetestet gegen echte Instanz | `PATCH /api/settings {"n8n_webhooks": {"Rechnungen": "https://n8n.local/webhook/…"}}`, optional Secret `n8n_webhook_secret` (Header `X-Jarvis-Secret`) |
| Bildschirm/Tastatur | ✅ implementiert (Screenshot, Texteingabe), standardmäßig **aus** | Modul „Bildschirm/Tastatur“ aktivieren, für Texteingabe `pyautogui` |
| Browser-Automatisierung mit Playwright | ⏳ geplant | aktuell: Seiten lesen per HTTP; Formulare ausfüllen noch nicht |
| Gmail / Google Calendar | ⛔ blockiert | benötigt eigenes Google-Cloud-Projekt mit OAuth-Client-ID (Desktop-App) |
| Outlook / Microsoft-Kalender | ⛔ blockiert | benötigt Azure-App-Registrierung (Microsoft Graph, Delegated: Mail.ReadWrite, Calendars.ReadWrite) |
| Messenger | ⛔ blockiert | offizielle APIs (z. B. Telegram-Bot, WhatsApp Business) erfordern eigene Konten/Tokens |

## Warum E-Mail/Kalender blockiert sind

Die offiziellen APIs erfordern eine von **dir** registrierte OAuth-Anwendung – Zugangsdaten, die nicht
erfunden oder geteilt werden können. Geplantes Vorgehen (siehe STATUS.md, nächste Schritte):
1. OAuth-„Installed App“-Ablauf mit Loopback-Redirect (`http://127.0.0.1:<port>/oauth/callback`), Tokens im Credential Manager.
2. Werkzeuge: `email_list/summarize` (Stufe 1), `email_draft` (Stufe 2), `email_send` (**Stufe 3**, nie ohne ausdrückliche Bestätigung),
   `calendar_list` (1), `calendar_create` (2).
3. Tagesübersicht um Termine erweitern.

## Hinweise zu Finanzen und Gesundheit

* Budgetfunktionen sind **reine Erfassung/Auswertung** deiner Eingaben. Keine Bankzugänge, keine Transaktionen.
* Gewohnheiten/Training: nur deine eigenen Einträge. Jarvis stellt keine Diagnosen und erfindet keine Gesundheitsdaten.
