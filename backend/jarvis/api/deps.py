"""Authentifizierung und Fehlerbehandlung für die API."""
from __future__ import annotations

import ipaddress
import time
from collections import defaultdict, deque

from fastapi import Depends, Request, WebSocket

from ..core import Jarvis
from ..security.tokens import AuthError, Principal, check_admin_token

# Header, die Tailscale Serve bzw. Reverse-Proxys setzen. Ist einer davon vorhanden, kam die
# Anfrage über das Netzwerk – das lokale Admin-Token wird dann NICHT akzeptiert.
PROXY_HEADERS = ("tailscale-user-login", "tailscale-user-name", "x-forwarded-for", "x-forwarded-host",
                 "forwarded", "x-real-ip")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def app_of(request: Request) -> Jarvis:
    return request.app.state.jarvis


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host in ("testclient", "localhost"):  # "testclient" = FastAPI-TestClient
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_local_request(conn: Request | WebSocket) -> bool:
    client = conn.client.host if conn.client else None
    if not _is_loopback(client):
        return False
    return not any(h in conn.headers for h in PROXY_HEADERS)


def resolve_principal(jarvis: Jarvis, conn: Request | WebSocket, token: str | None) -> Principal:
    if not token:
        raise ApiError(401, "auth_required", "Anmeldung erforderlich")
    if token.startswith("jv1."):
        try:
            return jarvis.tokens.verify_access(token)
        except AuthError as exc:
            raise ApiError(401, exc.code, exc.message)
    if check_admin_token(jarvis.admin_token, token):
        if not is_local_request(conn):
            jarvis.db.audit("unknown", "admin_token_remote_attempt", {"client": conn.client.host if conn.client else None},
                            risk=3, outcome="denied")
            raise ApiError(403, "admin_local_only", "Das Admin-Token ist nur lokal am PC gültig")
        return Principal(kind="admin", name="PC")
    raise ApiError(401, "token_invalid", "Ungültiges Token")


def _bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def principal(request: Request) -> Principal:
    return resolve_principal(app_of(request), request, _bearer(request))


def admin(p: Principal = Depends(principal)) -> Principal:
    if not p.is_admin:
        raise ApiError(403, "admin_required", "Nur am PC (lokal) erlaubt")
    return p


class RateLimiter:
    """Einfaches Sliding-Window-Limit pro Client (für öffentliche Kopplungs-Endpunkte)."""

    def __init__(self, limit: int, window: float):
        self.limit = limit
        self.window = window
        self.hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.time()
        q = self.hits[key]
        while q and q[0] < now - self.window:
            q.popleft()
        if len(q) >= self.limit:
            raise ApiError(429, "rate_limited", "Zu viele Versuche – bitte später erneut")
        q.append(now)
