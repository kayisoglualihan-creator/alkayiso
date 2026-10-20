"""Fehlerdiagnose: ``python -m jarvis.diagnose`` prüft Umgebung, Abhängigkeiten, Datenordner,
Port, Tailscale, KI-Anbieter und Sprachdienste und gibt verständliche Hinweise aus."""
from __future__ import annotations

import importlib.util
import platform
import socket
import sys

from .config import VERSION, load_settings
from .network import tailscale_status

OK, WARN, ERR = "✓", "!", "✗"


def check(name: str, ok: bool | None, detail: str = "", hint: str = "") -> bool:
    sym = OK if ok else (WARN if ok is None else ERR)
    print(f" {sym} {name}{': ' + detail if detail else ''}")
    if not ok and hint:
        print(f"     → {hint}")
    return bool(ok)


def main() -> int:
    print(f"J.A.R.V.I.S. Diagnose (Version {VERSION})\n")
    s = load_settings()
    check("Python", sys.version_info >= (3, 11), platform.python_version(), "Python 3.11 oder neuer installieren")
    check("Betriebssystem", True, f"{platform.system()} {platform.release()}")
    for mod, pkg in [("fastapi", "fastapi"), ("uvicorn", "uvicorn"), ("psutil", "psutil"), ("qrcode", "qrcode"),
                     ("pypdf", "pypdf"), ("docx", "python-docx"), ("openpyxl", "openpyxl"), ("anthropic", "anthropic")]:
        check(f"Paket {pkg}", importlib.util.find_spec(mod) is not None, hint="pip install -r backend/requirements.txt")
    print()
    check("Datenordner", s.data_dir.exists(), str(s.data_dir))
    check("Freigegebene Ordner", True, ", ".join(str(p) for p in s.allowed_roots if p.exists()) or "keiner vorhanden")
    sock = socket.socket()
    try:
        sock.bind((s.host, s.port))
        check(f"Port {s.port}", True, "frei (Jarvis läuft gerade nicht)")
    except OSError:
        check(f"Port {s.port}", None, "belegt – läuft Jarvis bereits?", "Falls nicht: anderen Port mit --port wählen")
    finally:
        sock.close()
    print()
    ts = tailscale_status()
    check("Tailscale installiert", ts["installed"], hint=ts.get("hint", ""))
    if ts["installed"]:
        check("Tailscale verbunden", ts["running"], ts.get("tailnet") or "", ts.get("hint", ""))
        check("Tailscale Serve", ts.get("serve_configured"), ts.get("https_url", ""), "scripts\\tailscale_serve.ps1 ausführen")
        check("Tailscale Funnel aus", not ts.get("funnel_enabled"), hint="'tailscale funnel reset' ausführen!")
    print()
    # Bewusst KEIN Jarvis-Objekt erzeugen (würde das Admin-Token eines laufenden Servers ersetzen)
    from .database import Database
    from .security.secrets import SecretStore
    from .voice import VoiceService
    db = Database(s.db_path)
    secrets = SecretStore(s.data_dir)
    provider = db.get_setting("ai_provider", "offline")
    key = {"anthropic": "anthropic_api_key", "openai": "openai_api_key"}.get(provider)
    check("KI-Anbieter", not key or bool(secrets.get(key)), provider,
          "API-Schlüssel in den Einstellungen hinterlegen (sonst lokaler Basismodus)")
    check("Schlüsselspeicher", True, secrets.backend_name())
    v = VoiceService(s.data_dir, secrets, db).status()
    check("faster-whisper (STT)", v["stt_faster_whisper"] or None, hint="optional: pip install -r backend/requirements-voice.txt")
    check("Piper (TTS)", v["tts_piper"] or None, hint="optional: Stimme (.onnx) nach %LOCALAPPDATA%\\Jarvis\\voices legen")
    check("openWakeWord", v["wakeword_openwakeword"] or None, hint="optional, für 'Hey Jarvis' ohne Browser")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
