"""OAuth 2.0 (Authorization Code + PKCE, Loopback-Redirect) für Google und Microsoft.

Ablauf: PC-Oberfläche → „Verbinden“ → Browser öffnet die Anmeldeseite des Anbieters → Rückleitung an
``http://127.0.0.1:<port>/oauth/callback`` (nur lokal) → Tokens im Windows-Schlüsselspeicher.

Voraussetzung (einmalig, durch dich): eine eigene OAuth-App beim Anbieter registrieren und die
Client-ID in Jarvis eintragen – siehe documentation/INTEGRATIONEN.md.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx


@dataclass(frozen=True)
class OAuthProvider:
    name: str
    auth_url: str
    token_url: str
    scopes: tuple[str, ...]
    redirect_host: str
    label: str


PROVIDERS = {
    "google": OAuthProvider(
        "google", "https://accounts.google.com/o/oauth2/v2/auth", "https://oauth2.googleapis.com/token",
        ("openid", "email", "https://www.googleapis.com/auth/gmail.readonly",
         "https://www.googleapis.com/auth/gmail.compose", "https://www.googleapis.com/auth/calendar.events"),
        "127.0.0.1", "Google (Gmail + Kalender)"),
    "microsoft": OAuthProvider(
        "microsoft", "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        ("offline_access", "User.Read", "Mail.ReadWrite", "Mail.Send", "Calendars.ReadWrite"),
        "localhost", "Microsoft (Outlook + Kalender)"),
}


class OAuthError(Exception):
    pass


class OAuthManager:
    """Verwaltet Anmeldungen. Tokens liegen im SecretStore unter ``<provider>_oauth`` (JSON)."""

    def __init__(self, db, secrets_store, port: int, transport: httpx.AsyncBaseTransport | None = None):
        self.db = db
        self.secrets = secrets_store
        self.port = port
        self.transport = transport
        self._pending: dict[str, dict] = {}  # state -> {provider, verifier, created}

    def client_id(self, provider: str) -> str:
        return self.db.get_setting(f"{provider}_client_id", "") or ""

    def redirect_uri(self, provider: str) -> str:
        return f"http://{PROVIDERS[provider].redirect_host}:{self.port}/oauth/callback"

    def status(self) -> dict:
        out = {}
        for name, p in PROVIDERS.items():
            tok = self._load(name)
            out[name] = {"label": p.label, "client_id_set": bool(self.client_id(name)), "connected": bool(tok),
                         "account": (tok or {}).get("account", "")}
        return out

    def connected(self) -> list[str]:
        return [n for n in PROVIDERS if self._load(n)]

    def _load(self, provider: str) -> dict | None:
        raw = self.secrets.get(f"{provider}_oauth")
        try:
            return json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return None

    def _save(self, provider: str, tok: dict) -> None:
        self.secrets.set(f"{provider}_oauth", json.dumps(tok))

    def disconnect(self, provider: str) -> None:
        self.secrets.delete(f"{provider}_oauth")

    # -- Anmeldung ------------------------------------------------------------
    def start(self, provider: str) -> str:
        if provider not in PROVIDERS:
            raise OAuthError("Unbekannter Anbieter")
        cid = self.client_id(provider)
        if not cid:
            raise OAuthError(f"Zuerst die Client-ID für {PROVIDERS[provider].label} eintragen (siehe Anleitung).")
        now = time.time()
        self._pending = {s: v for s, v in self._pending.items() if v["created"] > now - 600}
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(24)
        self._pending[state] = {"provider": provider, "verifier": verifier, "created": now}
        params = {"client_id": cid, "response_type": "code", "redirect_uri": self.redirect_uri(provider),
                  "scope": " ".join(PROVIDERS[provider].scopes), "state": state, "code_challenge": challenge,
                  "code_challenge_method": "S256"}
        if provider == "google":
            params.update(access_type="offline", prompt="consent")
        return f"{PROVIDERS[provider].auth_url}?{urlencode(params)}"

    async def finish(self, state: str, code: str) -> str:
        pend = self._pending.pop(state, None)
        if not pend or pend["created"] < time.time() - 600:
            raise OAuthError("Anmeldung abgelaufen oder ungültig – bitte erneut verbinden.")
        provider = pend["provider"]
        data = {"client_id": self.client_id(provider), "grant_type": "authorization_code", "code": code,
                "redirect_uri": self.redirect_uri(provider), "code_verifier": pend["verifier"]}
        secret = self.secrets.get(f"{provider}_client_secret")
        if secret:
            data["client_secret"] = secret
        tok = await self._token_request(provider, data)
        tok["account"] = await self._account(provider, tok["access_token"])
        self._save(provider, tok)
        return provider

    async def _token_request(self, provider: str, data: dict) -> dict:
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as c:
            r = await c.post(PROVIDERS[provider].token_url, data=data)
        body = r.json() if r.content else {}
        if r.status_code >= 400 or "access_token" not in body:
            raise OAuthError(f"Token-Anfrage fehlgeschlagen: {body.get('error_description') or body.get('error') or r.status_code}")
        return {"access_token": body["access_token"], "refresh_token": body.get("refresh_token"),
                "expires_at": time.time() + int(body.get("expires_in", 3600)) - 60}

    async def _account(self, provider: str, access: str) -> str:
        url = ("https://www.googleapis.com/oauth2/v3/userinfo" if provider == "google"
               else "https://graph.microsoft.com/v1.0/me")
        try:
            async with httpx.AsyncClient(timeout=15, transport=self.transport) as c:
                r = await c.get(url, headers={"Authorization": f"Bearer {access}"})
            j = r.json()
            return j.get("email") or j.get("mail") or j.get("userPrincipalName") or ""
        except Exception:
            return ""

    async def access_token(self, provider: str) -> str:
        tok = self._load(provider)
        if not tok:
            raise OAuthError(f"{PROVIDERS[provider].label} ist nicht verbunden (Setup → Konten verbinden).")
        if tok["expires_at"] > time.time():
            return tok["access_token"]
        if not tok.get("refresh_token"):
            raise OAuthError("Anmeldung abgelaufen – bitte erneut verbinden.")
        data = {"client_id": self.client_id(provider), "grant_type": "refresh_token",
                "refresh_token": tok["refresh_token"]}
        secret = self.secrets.get(f"{provider}_client_secret")
        if secret:
            data["client_secret"] = secret
        new = await self._token_request(provider, data)
        new["refresh_token"] = new.get("refresh_token") or tok["refresh_token"]
        new["account"] = tok.get("account", "")
        self._save(provider, new)
        return new["access_token"]

    async def request(self, provider: str, method: str, url: str, **kw) -> httpx.Response:
        token = await self.access_token(provider)
        async with httpx.AsyncClient(timeout=30, transport=self.transport) as c:
            r = await c.request(method, url, headers={"Authorization": f"Bearer {token}"}, **kw)
        if r.status_code == 401:
            raise OAuthError("Zugriff verweigert – bitte Konto neu verbinden.")
        if r.status_code >= 400:
            raise OAuthError(f"API-Fehler {r.status_code}: {r.text[:300]}")
        return r
