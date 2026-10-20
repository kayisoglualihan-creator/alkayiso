"""Fernaufträge (z. B. vom iPhone): Status wartend -> in Bearbeitung -> (Genehmigung erforderlich) ->
erfolgreich / fehlgeschlagen. Jeder Statuswechsel wird per Eventbus an verbundene Clients gemeldet."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import Jarvis

STATUSES = {"pending", "running", "approval_required", "succeeded", "failed", "cancelled"}


class JobManager:
    def __init__(self, app: Jarvis):
        self.app = app
        self._tasks: dict[str, asyncio.Task] = {}

    def public(self, row: dict) -> dict:
        out = dict(row)
        if out.get("result"):
            try:
                out["result"] = json.loads(out["result"])
            except (TypeError, json.JSONDecodeError):
                pass
        out["approvals"] = [self.app.approvals.public(a) for a in self.app.db.all(
            "SELECT * FROM approvals WHERE job_id = ? ORDER BY created_at", (row["id"],))]
        return out

    def get(self, job_id: str) -> dict | None:
        row = self.app.db.one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        return self.public(row) if row else None

    def list(self, device_id: str | None = None, limit: int = 30) -> list[dict]:
        if device_id:
            rows = self.app.db.all("SELECT * FROM jobs WHERE device_id = ? ORDER BY created_at DESC LIMIT ?",
                                   (device_id, limit))
        else:
            rows = self.app.db.all("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self.public(r) for r in rows]

    def _set(self, job_id: str, status: str, **extra) -> None:
        self.app.db.update("jobs", "id", job_id, {"status": status, "updated_at": time.time(), **extra})
        job = self.get(job_id)
        self.app.bus.publish("job.updated", job)

    def submit(self, text: str, source: str, device_id: str | None = None,
               conversation_id: str | None = None) -> dict:
        if not text.strip():
            raise ValueError("Leerer Auftrag")
        job_id = "job_" + uuid.uuid4().hex[:16]
        now = time.time()
        self.app.db.insert("jobs", {"id": job_id, "source": source, "device_id": device_id, "text": text.strip(),
                                    "status": "pending", "conversation_id": conversation_id,
                                    "created_at": now, "updated_at": now})
        self.app.db.audit(source, "job_submitted", {"job": job_id, "text": text[:200]})
        self._tasks[job_id] = asyncio.create_task(self._run(job_id, text, source, conversation_id, device_id))
        return self.get(job_id)

    async def _run(self, job_id: str, text: str, source: str, conversation_id: str | None,
                   device_id: str | None = None) -> None:
        async def emit(ev: dict) -> None:
            if ev["type"] == "approval_required":
                self._set(job_id, "approval_required")
            elif ev["type"] in ("approval_result", "tool_call"):
                self._set(job_id, "running")
            self.app.bus.publish("job.event", {"job_id": job_id, "device_id": device_id, **ev})

        self._set(job_id, "running")
        try:
            out = await self.app.agent.run(text, source=source, conversation_id=conversation_id, job_id=job_id,
                                           emit=emit)
            failed_all = out["actions"] and all(not a["ok"] for a in out["actions"])
            self._set(job_id, "failed" if failed_all else "succeeded",
                      result=json.dumps(out, ensure_ascii=False, default=str),
                      conversation_id=out["conversation_id"],
                      error="Keine Aktion war erfolgreich" if failed_all else None)
            self.app.services.notify("job", "Auftrag abgeschlossen" if not failed_all else "Auftrag fehlgeschlagen",
                                     out["text"][:500])
        except asyncio.CancelledError:
            self._set(job_id, "cancelled", error="Abgebrochen")
            raise
        except Exception as exc:
            self._set(job_id, "failed", error=f"{type(exc).__name__}: {exc}")
        finally:
            self._tasks.pop(job_id, None)

    def cancel(self, job_id: str) -> bool:
        task = self._tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            # zugehörige offene Genehmigungen verwerfen
            self.app.db.execute("UPDATE approvals SET status='cancelled' WHERE job_id = ? AND status='pending'",
                                (job_id,))
            return True
        return False

    async def wait(self, job_id: str, timeout: float = 30) -> dict | None:
        task = self._tasks.get(job_id)
        if task:
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout)
            except TimeoutError:
                pass
        return self.get(job_id)

    async def shutdown(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        # Beim Neustart offene Aufträge als fehlgeschlagen markieren – nichts wird später heimlich ausgeführt.
        self.app.db.execute("UPDATE jobs SET status='failed', error='Abgebrochen (Jarvis wurde beendet)' "
                            "WHERE status IN ('pending','running','approval_required')")

    def recover_after_restart(self) -> None:
        self.app.db.execute("UPDATE jobs SET status='failed', error='Abgebrochen (Jarvis wurde neu gestartet)' "
                            "WHERE status IN ('pending','running','approval_required')")
        self.app.db.execute("UPDATE approvals SET status='expired' WHERE status='pending'")
