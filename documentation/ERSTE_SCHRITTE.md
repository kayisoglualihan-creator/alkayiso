# Erste Schritte – Schritt für Schritt (ca. 30–40 Minuten)

Nach jedem Schritt gibt es einen **✔ Kontrollpunkt**. Klappt etwas nicht: stopp, notiere die Schrittnummer und schick mir die Rückmeldung (siehe ganz unten).

---

## Schritt 1 – Installer herunterladen
1. Am PC im Browser öffnen: https://github.com/kayisoglualihan-creator/alkayiso/actions/workflows/windows-build.yml (bei GitHub angemeldet sein).
2. Den **obersten Lauf mit grünem Haken ✅** anklicken.
3. Ganz unten bei **Artifacts** auf **JARVIS-Windows-Installer** klicken → eine ZIP-Datei wird heruntergeladen.
4. ZIP im Explorer öffnen → `JARVIS-Setup-0.4.0.exe` auf den Desktop ziehen.

✔ Die Datei `JARVIS-Setup-0.4.0.exe` liegt auf deinem Desktop.

## Schritt 2 – Installieren
1. `JARVIS-Setup-0.4.0.exe` doppelklicken.
2. Erscheint „Der Computer wurde durch Windows geschützt“: **Weitere Informationen → Trotzdem ausführen** (der Installer hat kein kostenpflichtiges Signaturzertifikat).
3. Im Assistenten **„Jarvis beim Windows-Login automatisch starten“** anhaken → Weiter → Installieren.
4. Fehlt Tailscale, kommt ein Hinweis → **OK** (Tailscale folgt in Schritt 5).
5. Mit **„JARVIS jetzt starten“** abschließen.

✔ Ein dunkles Fenster mit dem animierten Jarvis-Kreis öffnet sich. Rechts unten im Infobereich ist ein türkiser Kreis zu sehen (eventuell unter dem Pfeil ^). Der **Einrichtungsassistent** erscheint.

## Schritt 3 – Einrichtungsassistent & Claude-Schlüssel
1. **Schritt „Willkommen“:** deinen Vornamen eintragen → Weiter.
2. **Claude-Schlüssel besorgen** (in einem Browser-Tab):
   * https://console.anthropic.com öffnen → anmelden/registrieren.
   * *Billing* → Guthaben aufladen (z. B. 5–10 $; ohne Guthaben funktioniert der Schlüssel nicht).
   * *API Keys* → **Create Key** → Name „JARVIS“ → Schlüssel (`sk-ant-…`) **kopieren**. Er wird nur einmal angezeigt.
3. Im Assistenten **„KI-Modell“**: Anbieter **Anthropic Claude** wählen → Schlüssel einfügen → **Testen**.
4. **Ordner:** die vorgeschlagenen Ordner (Dokumente, Desktop, Downloads) passen meist → Weiter.
5. **Autostart:** anhaken → Weiter. **iPhone:** jetzt überspringen (Weiter) → **Los geht's**.

✔ Nach „Testen“ steht: „✓ claude-opus-5-5 antwortet: Bereit“. Danach im Chat **„Hallo, wer bist du?“** eingeben → Jarvis antwortet frei formuliert. Oben steht „KI: claude-opus-5-5“.

> Gib den Schlüssel nie an andere weiter – auch nicht an mich. Er liegt sicher im Windows-Anmeldeinformationsspeicher.

## Schritt 4 – Diagnose
1. Startmenü → Ordner **JARVIS** → **JARVIS Diagnose**.
2. Der Editor öffnet `diagnose.txt`.

✔ Erwartet: fast alles ✓. „✗ Tailscale installiert“ ist an dieser Stelle **normal**. „! Port 8765 belegt – läuft Jarvis bereits?“ ist ebenfalls normal, weil Jarvis ja läuft.
*(Falls sich kein Editor öffnet: Ältere Builds schreiben das Ergebnis nach `%LOCALAPPDATA%\Jarvis\jarvis.log` – Windows-Taste+R, `%LOCALAPPDATA%\Jarvis` eingeben, Datei öffnen.)*

## Schritt 5 – Tailscale am PC
1. https://tailscale.com/download/windows → herunterladen und installieren.
2. Im Infobereich auf das Tailscale-Symbol → **Log in** → mit Google, Microsoft oder Apple anmelden. Dieses Konto verwendest du später auch am iPhone.
3. Im Browser https://login.tailscale.com/admin/dns öffnen:
   * **MagicDNS** muss aktiviert sein.
   * Bei **HTTPS Certificates** auf **Enable HTTPS** klicken und bestätigen.

✔ Unter https://login.tailscale.com/admin/machines ist dein PC als „Connected“ aufgeführt.

## Schritt 6 – Tailscale Serve einrichten
1. Startmenü → **JARVIS** → **Tailscale Serve einrichten**. Ein blaues PowerShell-Fenster öffnet sich.
2. Am Ende steht: `Jarvis ist im Tailnet erreichbar unter: https://<dein-pc>.<tailnet>.ts.net` → **diese Adresse notieren**.

✔ In Jarvis links auf **PC** klicken. Im Kasten „iPhone verbinden“ stehen „✓ Tailscale aktiv“ und „✓ Tailscale Serve konfiguriert“.

*Falls das Fenster sofort zugeht oder einen Fehler zeigt: PowerShell als normaler Benutzer öffnen und eingeben:*
```powershell
tailscale serve --bg --https=443 http://127.0.0.1:8765
tailscale serve status
```

## Schritt 7 – Tailscale am iPhone
1. App Store → **Tailscale** installieren → öffnen → mit **demselben Konto** wie am PC anmelden → VPN-Konfiguration **Erlauben**.
2. In der Tailscale-App muss der Schalter auf **Connected** stehen.
3. In **Safari** die Adresse aus Schritt 6 öffnen und `/api/health` anhängen, z. B. `https://mein-pc.tail1234.ts.net/api/health`.

✔ Safari zeigt `{"status":"ok","name":"JARVIS",…}`. Beim allerersten Aufruf kann es bis zu 30 Sekunden dauern, weil das Zertifikat erst erstellt wird.

## Schritt 8 – iPhone koppeln
1. Am PC: Jarvis → **PC** → **QR-Code anzeigen**. Unter dem QR-Code darf **keine** Warnung „Keine Tailscale-HTTPS-Adresse erkannt“ stehen.
2. iPhone: **Kamera-App** auf den QR-Code richten → auf den gelben Link tippen → Safari öffnet Jarvis.
3. Das iPhone zeigt „Bitte am PC bestätigen“ und eine **6-stellige Nummer**. Am PC erscheint ein Fenster mit derselben Nummer → vergleichen → **Verbinden**.
4. iPhone: in Safari **Teilen-Symbol** → **Zum Home-Bildschirm** → Hinzufügen.

✔ Auf dem Home-Bildschirm ist ein JARVIS-Symbol, das sich im Vollbild öffnet. Am PC unter „Gekoppelte Geräte“ steht „iPhone (Web-App)“.

## Schritt 9 – Funktionstest vom iPhone
Im iPhone-Jarvis eingeben (oder die Mikrofontaste nutzen):
1. **„Wie hoch ist die CPU-Auslastung meines Computers?“** → ✔ Antwort mit CPU/RAM, Status **Erfolgreich**.
2. **„Öffne den Editor“** → ✔ Am PC öffnet sich der Windows-Editor.
3. **„Schließe notepad“** → ✔ Oben erscheint „Genehmigung erforderlich“ → **Ausführen** → der Editor schließt sich.
4. Tailscale am iPhone ausschalten und etwas senden → ✔ Anzeige „PC offline“, nichts wird ausgeführt.

🎉 Fertig.

---

## Rückmeldung an mich

Schick mir bei Problemen:
1. Die **Schrittnummer** und was du erwartet bzw. stattdessen gesehen hast (ein Screenshot ist ideal).
2. Den Inhalt von **`diagnose.txt`** (Startmenü → JARVIS Diagnose).
3. Bei Abstürzen oder Fehlern die letzten ~50 Zeilen aus **`%LOCALAPPDATA%\Jarvis\jarvis.log`**.

**Niemals mitschicken:** API-Schlüssel (`sk-ant-…`), den Inhalt von `secrets.bin`, `signing.key` oder `local_admin_token`. Diagnose und Log enthalten keine Schlüssel.
