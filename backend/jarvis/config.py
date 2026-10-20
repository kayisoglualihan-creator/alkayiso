"""Zentrale Konfiguration für JARVIS CORE.

Konfiguration kommt aus drei Quellen (in dieser Reihenfolge, spätere überschreiben frühere):
1. Eingebaute Standardwerte
2. Umgebungsvariablen (``JARVIS_*``) bzw. ``.env``-Datei
3. Laufzeit-Einstellungen aus der Datenbank (über die Einstellungs-API änderbar)

Geheimnisse (API-Schlüssel) werden NICHT hier gespeichert, sondern über
``jarvis.security.secrets`` (Windows Credential Manager / Keyring / Umgebungsvariablen).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "JARVIS"
VERSION = "0.4.0"


def _default_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Jarvis"
    xdg = os.environ.get("XDG_DATA_HOME")
    return Path(xdg) / "jarvis" if xdg else Path.home() / ".local" / "share" / "jarvis"


def _load_dotenv(path: Path) -> None:
    """Minimaler .env-Parser (keine zusätzliche Abhängigkeit). Bestehende Variablen gewinnen."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "ja", "on"}


@dataclass
class Settings:
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 8765
    # Öffentliche Basis-URL für den QR-Code (z. B. https://mein-pc.tailnet-xyz.ts.net)
    public_url: str = ""
    access_token_ttl: int = 15 * 60          # Sekunden
    refresh_token_ttl: int = 30 * 24 * 3600  # Sekunden
    pairing_ttl: int = 5 * 60                # Sekunden
    approval_ttl: int = 5 * 60               # Sekunden – danach verfällt eine Genehmigung
    # Pairing nur über Tailscale Serve (Header Tailscale-User-Login) oder lokal zulassen
    require_tailscale_for_pairing: bool = True
    scheduler_interval: float = 20.0
    enable_scheduler: bool = True
    allowed_roots: list[Path] = field(default_factory=list)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jarvis.db"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "output"

    @property
    def trash_dir(self) -> Path:
        return self.data_dir / "trash"

    @property
    def admin_token_file(self) -> Path:
        return self.data_dir / "local_admin_token"


def load_settings(data_dir: str | Path | None = None) -> Settings:
    _load_dotenv(Path.cwd() / ".env")
    ddir = Path(data_dir or os.environ.get("JARVIS_DATA_DIR") or _default_data_dir()).expanduser()
    if data_dir is None:
        _load_dotenv(ddir / ".env")
    home = Path.home()
    roots_env = os.environ.get("JARVIS_ALLOWED_ROOTS")
    if roots_env:
        roots = [Path(p).expanduser() for p in roots_env.split(os.pathsep) if p.strip()]
    else:
        roots = [home / "Documents", home / "Desktop", home / "Downloads",
                 home / "Dokumente", ddir / "output"]
    s = Settings(
        data_dir=ddir,
        host=os.environ.get("JARVIS_HOST", "127.0.0.1"),
        port=int(os.environ.get("JARVIS_PORT", "8765")),
        public_url=os.environ.get("JARVIS_PUBLIC_URL", ""),
        require_tailscale_for_pairing=_env_bool("JARVIS_REQUIRE_TAILSCALE_PAIRING", True),
        enable_scheduler=_env_bool("JARVIS_ENABLE_SCHEDULER", True),
        allowed_roots=roots,
    )
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.output_dir.mkdir(parents=True, exist_ok=True)
    s.trash_dir.mkdir(parents=True, exist_ok=True)
    return s
