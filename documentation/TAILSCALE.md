# Sicherer Fernzugriff mit Tailscale

Jarvis ist **niemals** direkt aus dem Internet erreichbar. Das Backend lauscht nur auf `127.0.0.1:8765`.
Dein iPhone erreicht es ausschließlich über dein privates Tailscale-Netz (WireGuard-verschlüsselt) und
**Tailscale Serve** (HTTPS mit gültigem Zertifikat). Keine Portfreigabe am Router, **kein Tailscale Funnel**.

## Einrichtung (einmalig, ca. 10 Minuten)

1. **Konto:** https://login.tailscale.com – mit Google/Microsoft/Apple anmelden (kostenloser Plan genügt).
2. **PC:** `winget install Tailscale.Tailscale` → im Infobereich anmelden.
3. **iPhone:** App „Tailscale“ aus dem App Store → mit **demselben Konto** anmelden → VPN erlauben.
4. **HTTPS aktivieren:** Tailscale-Admin → *DNS* → *MagicDNS* und *HTTPS Certificates* einschalten.
5. **Serve einrichten (PC):**
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\tailscale_serve.ps1
   ```
   Ausgabe: `https://<pc-name>.<tailnet>.ts.net` – das ist die Adresse für das iPhone.
   (Beim Installer: Startmenü → „Tailscale Serve einrichten“.)
6. **Prüfen:** Jarvis → *PC* → Kasten „iPhone verbinden“ zeigt „✓ Tailscale aktiv“ und „✓ Serve konfiguriert“.
   Oder: `JARVIS.exe --diagnose`.

## iPhone koppeln

1. Am PC: *PC → iPhone verbinden → QR-Code anzeigen* (gültig 5 Minuten, Einmalcode).
2. iPhone: Jarvis-App → „QR-Code scannen“ (oder bei der Web-App: Kamera-App auf den QR-Code richten).
3. Beide Geräte zeigen eine **6-stellige Prüfnummer** – vergleichen, am PC **Verbinden** klicken.
4. Fertig. Das iPhone erhält ein gerätegebundenes Refresh-Token (rotierend) und kurzlebige Zugangstokens (15 min).

## Optional: Zugriff weiter einschränken (Tailscale-ACL)

Im Tailscale-Admin unter *Access Controls* kann der Zugriff auf deinen PC auf deine eigenen Geräte begrenzt werden:
```json
{ "acls": [ { "action": "accept", "src": ["autogroup:member"], "dst": ["<pc-name>:443"] } ] }
```

## Fernzugriff abschalten / Gerät entfernen

* *PC → Gekoppelte Geräte → Entfernen* – wirkt **sofort** (auch offene WebSocket-Verbindungen werden getrennt).
* *PC → „Fernzugriff erlaubt“* ausschalten – alle Geräte gesperrt, PC-Bedienung lokal bleibt möglich.
* Infobereich-Menü → „Fernzugriff an/aus“.
* Vollständig: `tailscale serve reset`.

## Wake-on-LAN

Über Tailscale kann ein schlafender PC **nicht** geweckt werden (Tailscale läuft ja auf dem PC selbst).
WoL bräuchte ein zweites, immer laufendes Gerät im Heimnetz (z. B. Router/Raspberry Pi mit Tailscale)
– bewusst nicht Bestandteil dieser Version. Ein ausgeschalteter PC wird im iPhone korrekt als **„PC offline“** angezeigt.
