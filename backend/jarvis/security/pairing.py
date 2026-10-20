"""Gerätekopplung per QR-Code.

Ablauf:
1. PC (Admin) startet Kopplung -> zeitlich begrenzter Einmalcode (QR).
2. iPhone scannt QR und sendet ``claim`` mit Code + Gerätename.
   Der Code wird dabei verbraucht (keine Wiederverwendung). Max. 5 Fehlversuche.
3. Beide Geräte zeigen eine 6-stellige Prüfnummer. PC-Nutzer bestätigt.
4. iPhone fragt mit seinem geheimen ``claim_secret`` den Status ab und erhält
   genau einmal sein Refresh-Token.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import uuid

from ..database import Database
from .tokens import AuthError, TokenService, hash_secret

MAX_ATTEMPTS = 5


class PairingService:
    def __init__(self, db: Database, tokens: TokenService, ttl: int):
        self.db = db
        self.tokens = tokens
        self.ttl = ttl

    def _expire_old(self) -> None:
        self.db.execute(
            "UPDATE pairings SET status = 'expired' WHERE expires_at < ? AND status IN ('open', 'claimed')",
            (time.time(),),
        )

    def start(self) -> dict:
        self._expire_old()
        # Nur eine offene Kopplung gleichzeitig
        self.db.execute("UPDATE pairings SET status = 'cancelled' WHERE status IN ('open', 'claimed')")
        pid = uuid.uuid4().hex
        code = secrets.token_urlsafe(24)
        now = time.time()
        self.db.insert("pairings", {
            "id": pid, "code_hash": hash_secret(code), "created_at": now,
            "expires_at": now + self.ttl, "status": "open",
        })
        return {"pairing_id": pid, "code": code, "expires_at": now + self.ttl}

    def claim(self, pairing_id: str, code: str, device_name: str, platform: str,
              tailscale_login: str | None = None) -> dict:
        self._expire_old()
        p = self.db.one("SELECT * FROM pairings WHERE id = ?", (pairing_id,))
        if not p:
            raise AuthError("pairing_not_found", "Kopplung nicht gefunden")
        if p["status"] != "open":
            raise AuthError("pairing_closed", f"Kopplung nicht mehr offen ({p['status']})")
        if not hmac.compare_digest(p["code_hash"], hash_secret(code)):
            attempts = p["attempts"] + 1
            self.db.update("pairings", "id", pairing_id, {
                "attempts": attempts, "status": "locked" if attempts >= MAX_ATTEMPTS else "open"})
            raise AuthError("pairing_code_invalid", "Kopplungscode ungültig")
        claim_secret = secrets.token_urlsafe(32)
        verify = str(int(hashlib.sha256((claim_secret + p["code_hash"]).encode()).hexdigest(), 16) % 1_000_000).zfill(6)
        self.db.update("pairings", "id", pairing_id, {
            "status": "claimed", "device_name": device_name[:64] or "iPhone",
            "platform": platform[:32] or "ios", "claim_hash": hash_secret(claim_secret),
            "verify_code": verify, "tailscale_login": tailscale_login,
        })
        return {"pairing_id": pairing_id, "claim_secret": claim_secret, "verify_code": verify,
                "status": "awaiting_approval"}

    def pending(self) -> list[dict]:
        self._expire_old()
        rows = self.db.all("SELECT id, status, device_name, platform, verify_code, expires_at, tailscale_login "
                           "FROM pairings WHERE status IN ('open', 'claimed') ORDER BY created_at DESC")
        return rows

    def decide(self, pairing_id: str, approve: bool) -> dict:
        self._expire_old()
        p = self.db.one("SELECT * FROM pairings WHERE id = ?", (pairing_id,))
        if not p or p["status"] != "claimed":
            raise AuthError("pairing_not_claimable", "Keine bestätigbare Kopplungsanfrage")
        if not approve:
            self.db.update("pairings", "id", pairing_id, {"status": "rejected"})
            return {"status": "rejected"}
        device_id = "dev_" + uuid.uuid4().hex[:16]
        self.db.insert("devices", {
            "id": device_id, "name": p["device_name"], "platform": p["platform"],
            "created_at": time.time(), "token_version": 1, "tailscale_login": p["tailscale_login"],
        })
        self.db.update("pairings", "id", pairing_id, {"status": "approved", "device_id": device_id})
        return {"status": "approved", "device_id": device_id, "device_name": p["device_name"]}

    def poll(self, pairing_id: str, claim_secret: str) -> dict:
        p = self.db.one("SELECT * FROM pairings WHERE id = ?", (pairing_id,))
        if not p or not p["claim_hash"] or not hmac.compare_digest(p["claim_hash"], hash_secret(claim_secret)):
            raise AuthError("pairing_not_found", "Kopplung nicht gefunden")
        if p["status"] == "claimed" and p["expires_at"] < time.time():
            self.db.update("pairings", "id", pairing_id, {"status": "expired"})
            return {"status": "expired"}
        if p["status"] != "approved":
            return {"status": {"claimed": "awaiting_approval"}.get(p["status"], p["status"])}
        # Token genau einmal ausgeben
        self.db.update("pairings", "id", pairing_id, {"status": "completed"})
        device = self.db.one("SELECT * FROM devices WHERE id = ?", (p["device_id"],))
        refresh = self.tokens.issue_refresh(device["id"])
        device = self.db.one("SELECT * FROM devices WHERE id = ?", (p["device_id"],))
        access, exp = self.tokens.issue_access(device)
        return {"status": "completed", "device_id": device["id"], "refresh_token": refresh,
                "access_token": access, "expires_at": exp}
