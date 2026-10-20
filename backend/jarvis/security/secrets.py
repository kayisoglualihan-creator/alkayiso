"""Sichere Ablage von Geheimnissen.

* API-Schlüssel: Windows Credential Manager (über ``keyring``) – Fallback Umgebungsvariablen.
* Lokale Schlüsseldateien (Token-Signaturschlüssel): unter Windows mit DPAPI
  (CryptProtectData, an das Benutzerkonto gebunden) verschlüsselt, sonst Datei mit Rechten 0600.

Geheimnisse werden niemals geloggt oder über die API im Klartext zurückgegeben.
"""
from __future__ import annotations

import base64
import os
import secrets
import sys
from pathlib import Path

SERVICE = "JARVIS"

# Bekannte Geheimnisse und ihre Umgebungsvariablen-Fallbacks
KNOWN_SECRETS = {
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    "elevenlabs_api_key": "ELEVENLABS_API_KEY",
    "home_assistant_token": "HOME_ASSISTANT_TOKEN",
    "n8n_webhook_secret": "N8N_WEBHOOK_SECRET",
    "google_client_secret": "GOOGLE_CLIENT_SECRET",
}


def _keyring():
    if os.environ.get("JARVIS_DISABLE_KEYRING") == "1":
        return None
    try:
        import keyring  # type: ignore
        from keyring.backends import fail  # type: ignore

        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:
        return None


class SecretStore:
    """Liest/schreibt Geheimnisse. Fällt auf eine DPAPI-/0600-geschützte Datei zurück,
    wenn kein Systemschlüsselbund verfügbar ist (z. B. auf Servern ohne Desktop)."""

    def __init__(self, data_dir: Path):
        self.file = data_dir / "secrets.bin"
        self.kr = _keyring()

    def backend_name(self) -> str:
        if self.kr:
            return type(self.kr.get_keyring()).__name__
        return "DPAPI-Datei" if sys.platform == "win32" else "Datei (0600)"

    def _file_load(self) -> dict[str, str]:
        if not self.file.exists():
            return {}
        import json
        try:
            return json.loads(unprotect(self.file.read_bytes()).decode("utf-8"))
        except Exception:
            return {}

    def _file_save(self, data: dict[str, str]) -> None:
        import json
        write_private(self.file, protect(json.dumps(data).encode("utf-8")))

    def get(self, name: str) -> str | None:
        value = None
        if self.kr:
            try:
                value = self.kr.get_password(SERVICE, name)
            except Exception:
                value = None
        if not value:
            value = self._file_load().get(name)
        if not value and name in KNOWN_SECRETS:
            value = os.environ.get(KNOWN_SECRETS[name])
        return value or None

    def set(self, name: str, value: str) -> None:
        if self.kr:
            try:
                self.kr.set_password(SERVICE, name, value)
                return
            except Exception:
                pass
        data = self._file_load()
        data[name] = value
        self._file_save(data)

    def delete(self, name: str) -> None:
        if self.kr:
            try:
                self.kr.delete_password(SERVICE, name)
            except Exception:
                pass
        data = self._file_load()
        if name in data:
            del data[name]
            self._file_save(data)

    def status(self) -> dict[str, bool]:
        return {name: bool(self.get(name)) for name in KNOWN_SECRETS}


# ---------------------------------------------------------------------------
# DPAPI (nur Windows) – Daten an das angemeldete Benutzerkonto binden
# ---------------------------------------------------------------------------
def _dpapi(data: bytes, encrypt: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = BLOB()
    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    fn = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(blob_in), None, None, None, None, 0x01, ctypes.byref(blob_out))
    if not ok:
        raise OSError("DPAPI-Aufruf fehlgeschlagen")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)  # type: ignore[attr-defined]


def protect(data: bytes) -> bytes:
    if sys.platform == "win32":
        return b"DPAPI:" + base64.b64encode(_dpapi(data, True))
    return b"PLAIN:" + base64.b64encode(data)


def unprotect(data: bytes) -> bytes:
    if data.startswith(b"DPAPI:"):
        return _dpapi(base64.b64decode(data[6:]), False)
    if data.startswith(b"PLAIN:"):
        return base64.b64decode(data[6:])
    return data


def write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


def load_or_create_key(path: Path, nbytes: int = 32) -> bytes:
    if path.exists():
        try:
            key = unprotect(path.read_bytes())
            if len(key) >= nbytes:
                return key
        except Exception:
            pass
    key = secrets.token_bytes(nbytes)
    write_private(path, protect(key))
    return key
