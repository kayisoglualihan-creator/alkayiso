"""Berechtigungen, Risikostufen und Genehmigungen.

Stufe 1 – lesend/unkritisch: direkt ausführbar (sofern das Werkzeug aktiviert ist).
Stufe 2 – Änderungen: erfordert Genehmigung (oder ausdrückliche Dauerfreigabe am PC).
Stufe 3 – kritisch: erfordert IMMER eine aktuelle, ausdrückliche Bestätigung.

Zusätzlich: Sobald nicht vertrauenswürdige Inhalte (Webseiten, Dateien, Nachrichten) in den
Kontext gelangt sind ("tainted"), wird für jede Aktion ab Stufe 2 eine Genehmigung verlangt –
auch wenn eine Dauerfreigabe existiert. Das begrenzt Prompt-Injection-Schäden.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass

from ..database import Database
from ..events import EventBus

LEVEL_READ, LEVEL_CHANGE, LEVEL_CRITICAL = 1, 2, 3
CRITICAL_CONFIRM_TEXT = "BESTÄTIGEN"


@dataclass
class Decision:
    allowed: bool
    needs_approval: bool
    reason: str = ""


class PermissionPolicy:
    """Grants pro Werkzeug: ``auto`` | ``ask`` | ``deny``. Stufe 3 kann nie ``auto`` sein."""

    def __init__(self, db: Database):
        self.db = db

    def grants(self) -> dict[str, str]:
        return self.db.get_setting("tool_grants", {}) or {}

    def set_grant(self, tool: str, mode: str, risk: int) -> None:
        if mode not in {"auto", "ask", "deny"}:
            raise ValueError("mode muss auto, ask oder deny sein")
        if risk >= LEVEL_CRITICAL and mode == "auto":
            raise ValueError("Kritische Werkzeuge (Stufe 3) können nicht automatisch freigegeben werden")
        g = self.grants()
        g[tool] = mode
        self.db.set_setting("tool_grants", g)

    def remote_allowed(self, tool: str) -> bool:
        blocked = self.db.get_setting("remote_blocked_tools", []) or []
        return tool not in blocked

    def evaluate(self, tool: str, risk: int, *, source: str, tainted: bool) -> Decision:
        mode = self.grants().get(tool)
        if mode == "deny":
            return Decision(False, False, "Werkzeug ist in den Berechtigungen gesperrt")
        if source.startswith("device") and not self.remote_allowed(tool):
            return Decision(False, False, "Werkzeug ist für Fernzugriff gesperrt")
        if risk >= LEVEL_CRITICAL:
            return Decision(True, True, "Kritische Aktion – Bestätigung erforderlich")
        if risk == LEVEL_CHANGE:
            if tainted:
                return Decision(True, True, "Nicht vertrauenswürdige Inhalte im Kontext – Bestätigung erforderlich")
            if mode == "auto":
                return Decision(True, False)
            return Decision(True, True, "Änderung – Genehmigung erforderlich")
        if mode == "ask":
            return Decision(True, True, "Für dieses Werkzeug ist eine Genehmigung eingestellt")
        return Decision(True, False)


class ApprovalManager:
    """Verwaltet ausstehende Genehmigungen. Läuft eine Genehmigung ab, wird die Aktion
    verworfen – kritische Befehle werden niemals unbemerkt später ausgeführt."""

    def __init__(self, db: Database, bus: EventBus, ttl: int):
        self.db = db
        self.bus = bus
        self.ttl = ttl
        self._waiters: dict[str, asyncio.Future] = {}

    def create(self, *, tool: str, args: dict, risk: int, summary: str, requested_by: str,
               job_id: str | None) -> dict:
        aid = "apr_" + uuid.uuid4().hex[:16]
        now = time.time()
        row = {"id": aid, "job_id": job_id, "tool": tool, "args": json.dumps(args, ensure_ascii=False),
               "risk": risk, "summary": summary, "status": "pending", "requested_by": requested_by,
               "created_at": now, "expires_at": now + self.ttl}
        self.db.insert("approvals", row)
        public = self.public(row)
        self.bus.publish("approval.created", public)
        return public

    @staticmethod
    def public(row: dict) -> dict:
        out = dict(row)
        if isinstance(out.get("args"), str):
            out["args"] = json.loads(out["args"])
        out["requires_confirm_text"] = out["risk"] >= LEVEL_CRITICAL
        return out

    async def wait(self, approval_id: str) -> str:
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._waiters[approval_id] = fut
        try:
            return await asyncio.wait_for(fut, timeout=self.ttl)
        except TimeoutError:
            self.db.update("approvals", "id", approval_id, {"status": "expired", "decided_at": time.time()})
            self.bus.publish("approval.updated", {"id": approval_id, "status": "expired"})
            return "expired"
        finally:
            self._waiters.pop(approval_id, None)

    def decide(self, approval_id: str, approve: bool, decided_by: str, *, is_admin: bool,
               device_id: str | None, confirm_text: str | None = None) -> dict:
        row = self.db.one("SELECT * FROM approvals WHERE id = ?", (approval_id,))
        if not row:
            raise KeyError("approval_not_found")
        if row["status"] != "pending":
            raise ValueError(f"Genehmigung ist bereits {row['status']}")
        if row["expires_at"] < time.time():
            self.db.update("approvals", "id", approval_id, {"status": "expired"})
            raise ValueError("Genehmigung ist abgelaufen")
        # Geräte dürfen nur eigene Anfragen genehmigen; der PC-Besitzer alle.
        if not is_admin and row["requested_by"] != f"device:{device_id}":
            raise PermissionError("Dieses Gerät darf diese Anfrage nicht entscheiden")
        if approve and row["risk"] >= LEVEL_CRITICAL:
            if not is_admin and not self.db.get_setting("allow_remote_critical_approval", True):
                raise PermissionError("Kritische Aktionen müssen am PC bestätigt werden")
            if (confirm_text or "").strip().upper() != CRITICAL_CONFIRM_TEXT:
                raise PermissionError(f"Für kritische Aktionen bitte '{CRITICAL_CONFIRM_TEXT}' eingeben")
        status = "approved" if approve else "rejected"
        self.db.update("approvals", "id", approval_id,
                       {"status": status, "decided_at": time.time(), "decided_by": decided_by})
        self.db.audit(decided_by, f"approval_{status}", {"approval": approval_id, "tool": row["tool"]}, row["risk"])
        fut = self._waiters.get(approval_id)
        if fut and not fut.done():
            def _resolve(f=fut, st=status):
                if not f.done():
                    f.set_result(st)
            fut.get_loop().call_soon_threadsafe(_resolve)
        self.bus.publish("approval.updated", {"id": approval_id, "status": status})
        return {"id": approval_id, "status": status}

    def pending(self, device_id: str | None = None) -> list[dict]:
        now = time.time()
        self.db.execute("UPDATE approvals SET status='expired' WHERE status='pending' AND expires_at < ?", (now,))
        if device_id:
            rows = self.db.all("SELECT * FROM approvals WHERE status='pending' AND requested_by = ? "
                               "ORDER BY created_at DESC", (f"device:{device_id}",))
        else:
            rows = self.db.all("SELECT * FROM approvals WHERE status='pending' ORDER BY created_at DESC")
        return [self.public(r) for r in rows]
