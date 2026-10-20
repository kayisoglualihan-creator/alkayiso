"""Kurzlebige Zugangstokens (HMAC-SHA256), rotierende Refresh-Tokens, lokales Admin-Token."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from ..database import Database


class AuthError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass
class Principal:
    kind: str  # "admin" (lokaler PC-Besitzer) oder "device" (gekoppeltes Gerät)
    device_id: str | None = None
    name: str = ""

    @property
    def is_admin(self) -> bool:
        return self.kind == "admin"

    @property
    def actor(self) -> str:
        return "desktop" if self.is_admin else f"device:{self.device_id}"


class TokenService:
    def __init__(self, db: Database, signing_key: bytes, access_ttl: int, refresh_ttl: int):
        self.db = db
        self.key = signing_key
        self.access_ttl = access_ttl
        self.refresh_ttl = refresh_ttl

    # -- Access-Tokens ------------------------------------------------------
    def _sign(self, payload: dict) -> str:
        body = _b64(json.dumps(payload, separators=(",", ":")).encode())
        sig = _b64(hmac.new(self.key, body.encode(), hashlib.sha256).digest())
        return f"jv1.{body}.{sig}"

    def issue_access(self, device: dict) -> tuple[str, int]:
        now = int(time.time())
        exp = now + self.access_ttl
        token = self._sign({"typ": "access", "sub": device["id"], "ver": device["token_version"],
                            "iat": now, "exp": exp, "jti": secrets.token_hex(8)})
        return token, exp

    def verify_access(self, token: str) -> Principal:
        try:
            prefix, body, sig = token.split(".")
        except ValueError:
            raise AuthError("token_invalid", "Ungültiges Token-Format")
        if prefix != "jv1":
            raise AuthError("token_invalid", "Unbekanntes Token-Format")
        expected = _b64(hmac.new(self.key, body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            raise AuthError("token_invalid", "Token-Signatur ungültig")
        payload = json.loads(_unb64(body))
        if payload.get("typ") != "access":
            raise AuthError("token_invalid", "Falscher Token-Typ")
        if payload.get("exp", 0) < time.time():
            raise AuthError("token_expired", "Token abgelaufen – bitte erneuern")
        device = self.db.one("SELECT * FROM devices WHERE id = ?", (payload["sub"],))
        # Widerruf wirkt sofort: jede Anfrage prüft den aktuellen Gerätezustand.
        if not device or device["revoked_at"]:
            raise AuthError("device_revoked", "Gerät wurde widerrufen")
        if device["token_version"] != payload.get("ver"):
            raise AuthError("token_revoked", "Token wurde widerrufen")
        if not self.db.get_setting("remote_access_enabled", True):
            raise AuthError("remote_disabled", "Fernzugriff ist am PC deaktiviert")
        self.db.update("devices", "id", device["id"], {"last_seen": time.time()})
        return Principal(kind="device", device_id=device["id"], name=device["name"])

    # -- Refresh-Tokens -----------------------------------------------------
    def issue_refresh(self, device_id: str) -> str:
        token = "jvr_" + secrets.token_urlsafe(40)
        self.db.update("devices", "id", device_id, {
            "refresh_hash": hash_secret(token),
            "refresh_expires": time.time() + self.refresh_ttl,
        })
        return token

    def refresh(self, device_id: str, refresh_token: str) -> dict:
        device = self.db.one("SELECT * FROM devices WHERE id = ?", (device_id,))
        if not device or device["revoked_at"]:
            raise AuthError("device_revoked", "Gerät wurde widerrufen")
        if not self.db.get_setting("remote_access_enabled", True):
            raise AuthError("remote_disabled", "Fernzugriff ist am PC deaktiviert")
        if not device["refresh_hash"] or not hmac.compare_digest(device["refresh_hash"], hash_secret(refresh_token)):
            # Mögliche Wiederverwendung eines alten Tokens -> alle Tokens des Geräts ungültig machen
            self.db.update("devices", "id", device_id, {"refresh_hash": None,
                                                        "token_version": device["token_version"] + 1})
            self.db.audit(f"device:{device_id}", "refresh_rejected", risk=3, outcome="denied")
            raise AuthError("refresh_invalid", "Refresh-Token ungültig – Gerät bitte neu koppeln")
        if (device["refresh_expires"] or 0) < time.time():
            raise AuthError("refresh_expired", "Sitzung abgelaufen – Gerät bitte neu koppeln")
        access, exp = self.issue_access(device)
        new_refresh = self.issue_refresh(device_id)
        return {"access_token": access, "expires_at": exp, "refresh_token": new_refresh, "device_id": device_id}

    def revoke_device(self, device_id: str) -> bool:
        device = self.db.one("SELECT * FROM devices WHERE id = ?", (device_id,))
        if not device:
            return False
        self.db.update("devices", "id", device_id, {
            "revoked_at": time.time(), "refresh_hash": None, "token_version": device["token_version"] + 1})
        return True


def check_admin_token(expected: str, presented: str | None) -> bool:
    return bool(presented) and hmac.compare_digest(expected, presented)
