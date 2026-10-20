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
| Browser-Automatisierung (Playwright) | ✅ mit echtem Chromium getestet | Nutzt unter Windows den installierten Edge (sichtbares Fenster). Ausfüllen/Klicken = Stufe 2 mit Vorschau-Screenshot; Absenden/Kaufen/Bezahlen nur über `browser_submit_critical` (Stufe 3). Einstellungen: `browser_headless`, `browser_executable` |
| Gmail / Google Calendar | ✅ implementiert (gegen simulierte API getestet) – du brauchst eine eigene Client-ID | Anleitung unten |
| Outlook / Microsoft 365 / Outlook-Kalender | ✅ implementiert (gegen simulierte API getestet) – du brauchst eine eigene Client-ID | Anleitung unten |
| Kalender über iCal-Adresse (ohne Anmeldung, nur lesen) | ✅ | Setup → Kalender (iCal-Adressen) |
| Messenger | ⛔ blockiert | offizielle APIs (z. B. Telegram-Bot, WhatsApp Business) erfordern eigene Konten/Tokens |

## E-Mail & Kalender verbinden

Werkzeuge: `email_list`, `email_read` (Stufe 1, Inhalte gelten als nicht vertrauenswürdig), `email_draft` (Stufe 2),
**`email_send` (Stufe 3 – immer Bestätigung mit „BESTÄTIGEN“)**, `calendar_events` (1), `calendar_create` (2).
Termine erscheinen automatisch in der Tagesübersicht. Tokens liegen im Windows-Anmeldeinformationsspeicher.

### Google (Gmail + Google Kalender) – ca. 10 Minuten

1. https://console.cloud.google.com → oben „Projekt auswählen“ → **Neues Projekt** „JARVIS“.
2. *APIs & Dienste → Bibliothek*: **Gmail API** und **Google Calendar API** jeweils aktivieren.
3. *APIs & Dienste → OAuth-Zustimmungsbildschirm* (bzw. „Google Auth Platform“): Typ **Extern**, App-Name „JARVIS“,
   deine E-Mail eintragen. Unter **Testnutzer** deine eigene Gmail-Adresse hinzufügen. (Veröffentlichen ist nicht nötig.)
4. *APIs & Dienste → Anmeldedaten → Anmeldedaten erstellen → OAuth-Client-ID* → Anwendungstyp **Desktop-App**.
5. Client-ID und Client-Schlüssel kopieren.
6. In Jarvis: *Setup → Konten verbinden → Google*: Client-ID eintragen → Speichern. Den Client-Schlüssel unter
   *Setup → API-Schlüssel → „google_client_secret“* speichern.
7. **Verbinden** klicken → im Browserfenster mit deinem Google-Konto anmelden → „Konto verbunden“.

Hinweis: Im Testmodus läuft die Google-Anmeldung nach 7 Tagen ab und muss dann neu verbunden werden. Das umgehst du,
indem du die App im Zustimmungsbildschirm auf **„In Produktion“** stellst (für den Eigengebrauch ohne Google-Prüfung möglich;
Google zeigt dann beim Anmelden einen Warnhinweis „nicht verifiziert“ → *Erweitert → Weiter zu JARVIS*).

### Microsoft (Outlook.com / Microsoft 365) – ca. 5 Minuten

1. https://entra.microsoft.com (oder portal.azure.com) → *App-Registrierungen → Neue Registrierung*.
2. Name „JARVIS“, Kontotypen: **„Konten in einem beliebigen Organisationsverzeichnis und persönliche Microsoft-Konten“**.
3. Umleitungs-URI: Plattform **„Öffentlicher Client/nativ (mobil und Desktop)“**, URI `http://localhost:8765/oauth/callback`
   (genau so; wird auch in Jarvis unter Setup angezeigt).
4. *Authentifizierung*: „Öffentliche Clientflows zulassen“ → **Ja**.
5. *API-Berechtigungen → Microsoft Graph → Delegiert*: `Mail.ReadWrite`, `Mail.Send`, `Calendars.ReadWrite`, `User.Read`, `offline_access`.
6. Die **Anwendungs-ID (Client-ID)** kopieren (kein Geheimnis nötig).
7. In Jarvis: *Setup → Konten verbinden → Microsoft*: Client-ID eintragen → Speichern → **Verbinden**.

Läuft Jarvis auf einem anderen Port als 8765, muss die Umleitungs-URI entsprechend angepasst werden.

## Hinweise zu Finanzen und Gesundheit

* Budgetfunktionen sind **reine Erfassung/Auswertung** deiner Eingaben. Keine Bankzugänge, keine Transaktionen.
* Gewohnheiten/Training: nur deine eigenen Einträge. Jarvis stellt keine Diagnosen und erfindet keine Gesundheitsdaten.
