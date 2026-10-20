# Sicherheitskonzept

## Grundsätze

* **Least Privilege:** Jarvis kann nur, was als Werkzeug implementiert ist – es gibt **keine Remote-Shell**
  und keine Ausführung beliebiger KI-generierter Befehle. Programme nur aus einer Freigabeliste,
  Dateien nur in freigegebenen Ordnern (inkl. Schutz gegen `..`/Symlink-Ausbrüche).
* **Keine heimliche Überwachung:** Mikrofon nur bei aktiver Taste bzw. ausdrücklich aktiviertem Wake Word
  (Zustand sichtbar). Kamera nur beim QR-Scan. Screenshots nur als genehmigungspflichtige Aktion.
* **Lokal zuerst:** Backend nur auf `127.0.0.1`. Fernzugriff ausschließlich über Tailscale Serve, kein Funnel,
  keine Portfreigabe. Jarvis warnt, wenn Funnel aktiv ist.

## Authentifizierung

| Wer | Wie |
|---|---|
| PC-Besitzer (Desktop) | Zufälliges **lokales Admin-Token** pro Start (Datei mit Benutzerrechten). Wird abgelehnt, sobald die Anfrage nicht direkt von `127.0.0.1` kommt oder Proxy-/Tailscale-Header trägt – auch ein geleaktes Token nützt aus der Ferne nichts. Übergabe an die Oberfläche im URL-Fragment (`#…`, wird nie an Server gesendet/geloggt). |
| Gekoppelte Geräte | Kopplung per QR (Einmalcode, 5 min, max. 5 Fehlversuche, Bestätigung am PC mit Prüfnummer). Danach **HMAC-signierte Zugangstokens (15 min)** + **rotierende Refresh-Tokens (30 Tage)**; Refresh-Token nur als SHA-256-Hash gespeichert. Wiederverwendung eines alten Refresh-Tokens sperrt alle Tokens des Geräts. |
| Widerruf | Jede Anfrage prüft den aktuellen Gerätestatus in der Datenbank → Widerruf wirkt **sofort**, auch für offene WebSockets. Globaler Schalter „Fernzugriff erlaubt“. |

Der Signaturschlüssel liegt unter Windows **DPAPI-verschlüsselt** (an dein Benutzerkonto gebunden) im Datenordner.
API-Schlüssel im **Windows-Anmeldeinformationsspeicher** (Credential Manager via `keyring`), auf dem iPhone im **Keychain**.
Die iPhone-App enthält keine API-Schlüssel – KI-Anfragen laufen immer über deinen PC.

## Berechtigungsstufen

| Stufe | Beispiele | Verhalten |
|---|---|---|
| 1 – unkritisch | Systemstatus, Uhrzeit, Dateien suchen/lesen, Webseite lesen, Aufgaben anlegen, freigegebenes Programm starten | direkt (falls Werkzeug nicht gesperrt) |
| 2 – Änderungen | Dateien verschieben/kopieren, in Papierkorb, Ordner/Dokumente erstellen, Programme beenden, PC sperren, Smart Home schalten | **Genehmigung** (Vorschau der Aktion); Dauerfreigabe pro Werkzeug am PC möglich; Verschieben/Papierkorb **rückgängig machbar** |
| 3 – kritisch | Datei endgültig löschen, PC herunterfahren | **immer** aktuelle Bestätigung mit Eingabe „BESTÄTIGEN“; kann nicht dauerhaft freigegeben werden |

* Genehmigungen **verfallen nach 5 Minuten**. Abgelaufene oder abgelehnte Aktionen werden verworfen.
* Nach einem Neustart werden offene Aufträge als fehlgeschlagen markiert – **nichts wird später unbemerkt ausgeführt**.
* Geräte sehen und entscheiden nur **eigene** Aufträge/Genehmigungen.
* Einzelne Werkzeuge lassen sich nur für Fernzugriff sperren (`remote_blocked_tools`).

## Prompt-Injection-Schutz

* Inhalte aus Webseiten, Dateien, Suchergebnissen, Smart-Home-Zuständen und n8n werden als
  `<untrusted_data>` markiert; das Systemprompt verbietet, daraus Anweisungen zu übernehmen.
* **Taint-Regel:** Sobald solche Inhalte im aktuellen Auftrag gelesen wurden, verlangt **jede** Aktion ab Stufe 2
  eine Genehmigung – auch wenn sie sonst dauerhaft freigegeben ist. Das Gedächtnis kann dann nicht beschrieben werden.
* Web-Abrufe blockieren private/lokale Adressen (SSRF-Schutz – z. B. kein Zugriff auf `127.0.0.1` oder den Router).
* Smart Home: Schlösser/Alarmanlagen werden grundsätzlich nicht gesteuert.

## Protokollierung

Jede Werkzeugausführung, Genehmigung, Kopplung, Geräteentfernung und Einstellungsänderung landet im
Audit-Log (*Verlauf → Aktionsprotokoll*). **Geheimnisse werden nie protokolliert** (bei API-Schlüsseln nur der Name).

## Getestete Sicherheitseigenschaften

Siehe `backend/tests/test_auth_pairing.py`, `test_agent_permissions.py`, `test_integration.py`:
abgelaufene/manipulierte Tokens, Refresh-Rotation und Wiederverwendungserkennung, sofortiger Widerruf,
Admin-Token über Proxy abgelehnt, Kopplungscode einmalig/Sperre nach Fehlversuchen/Ablauf, Genehmigungen
(annehmen, ablehnen, Ablauf), kritische Bestätigung, Taint-Regel, Pfade außerhalb der Freigaben, SSRF,
Geräte-Isolation, gesperrte Fernwerkzeuge.

## Bekannte Restrisiken

* Wer Zugriff auf dein entsperrtes Windows-Konto hat, hat Zugriff auf Jarvis (wie auf alle deine Programme).
* Die PWA speichert ihr Refresh-Token im Browser-Speicher (weniger geschützt als der iOS-Keychain der nativen App).
* LLM-Anbieter (Claude/OpenAI) erhalten die Gesprächsinhalte; für maximale Privatsphäre Ollama (lokal) verwenden.
