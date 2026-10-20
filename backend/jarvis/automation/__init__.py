"""Automatisierungsmanager: Erinnerungen, zeitgesteuerte Aufgaben, Workflows, Tagesübersicht.

Zeitpläne:
  "daily 08:00" | "weekdays 07:30" | "weekly mon 09:00" | "every 30m" | "every 2h" | "once 2026-11-01T09:00"
Aktionstypen:
  briefing  – Tagesübersicht als Benachrichtigung
  reminder  – payload {"text": ...} als Benachrichtigung
  prompt    – payload {"prompt": ...} wird vom Agenten ausgeführt (Genehmigungen gelten weiter!)
  workflow  – payload {"steps": [{"tool": ..., "args": {...}}, ...]} – jeder Schritt wird einzeln geprüft
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import re
import time
from typing import TYPE_CHECKING

from ..security.permissions import LEVEL_READ
from ..tools.registry import ToolContext, ToolRegistry, ToolResult, params

if TYPE_CHECKING:
    from ..core import Jarvis

log = logging.getLogger("jarvis.automation")
_DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
         "mo": 0, "di": 1, "mi": 2, "do": 3, "fr": 4, "sa": 5, "so": 6}
ACTION_TYPES = {"briefing", "reminder", "prompt", "workflow"}


def next_run(schedule: str, after: float) -> float | None:
    s = schedule.strip().lower()
    base = dt.datetime.fromtimestamp(after)
    m = re.fullmatch(r"every\s+(\d+)\s*([mh])", s)
    if m:
        n = int(m.group(1)) * (60 if m.group(2) == "m" else 3600)
        if n < 60:
            raise ValueError("Mindestintervall ist 1 Minute")
        return after + n
    m = re.fullmatch(r"once\s+(.+)", s)
    if m:
        ts = dt.datetime.fromisoformat(m.group(1).strip().upper().replace(" ", "T")).timestamp()
        return ts if ts > after else None
    m = re.fullmatch(r"(daily|weekdays|weekly\s+(\w+))\s+(\d{1,2}):(\d{2})", s)
    if not m:
        raise ValueError(f"Unbekannter Zeitplan: {schedule!r}")
    hh, mm = int(m.group(3)), int(m.group(4))
    for add in range(0, 9):
        day = base.date() + dt.timedelta(days=add)
        cand = dt.datetime.combine(day, dt.time(hh, mm))
        if cand.timestamp() <= after:
            continue
        if m.group(1) == "daily":
            return cand.timestamp()
        if m.group(1) == "weekdays" and cand.weekday() < 5:
            return cand.timestamp()
        if m.group(2) and cand.weekday() == _DAYS.get(m.group(2)[:3], _DAYS.get(m.group(2)[:2], -1)):
            return cand.timestamp()
    raise ValueError(f"Unbekannter Wochentag in {schedule!r}")


class AutomationManager:
    def __init__(self, app: Jarvis):
        self.app = app
        self._task: asyncio.Task | None = None

    # -- CRUD -----------------------------------------------------------------------
    def create(self, name: str, schedule: str, action_type: str, payload: dict | None = None,
               enabled: bool = True) -> dict:
        if action_type not in ACTION_TYPES:
            raise ValueError(f"action_type muss einer von {sorted(ACTION_TYPES)} sein")
        payload = payload or {}
        if action_type == "workflow":
            self._validate_steps(payload.get("steps"))
        nr = next_run(schedule, time.time()) if schedule != "manual" else None
        aid = self.app.db.insert("automations", {
            "name": name.strip(), "schedule": schedule, "action_type": action_type,
            "payload": json.dumps(payload, ensure_ascii=False), "enabled": int(enabled), "next_run": nr,
            "created_at": time.time()})
        return self.get(aid)

    def _validate_steps(self, steps) -> None:
        if not isinstance(steps, list) or not steps:
            raise ValueError("Workflow benötigt 'steps' (Liste von {tool, args})")
        for st in steps:
            if not isinstance(st, dict) or not self.app.registry.get(st.get("tool", "")):
                raise ValueError(f"Ungültiger Workflow-Schritt: {st}")
            if st["tool"] == "run_workflow":
                raise ValueError("Workflows dürfen keine Workflows aufrufen")

    def get(self, aid: int) -> dict | None:
        r = self.app.db.one("SELECT * FROM automations WHERE id = ?", (aid,))
        if r:
            r["payload"] = json.loads(r["payload"])
            r["enabled"] = bool(r["enabled"])
        return r

    def list(self) -> list[dict]:
        out = []
        for r in self.app.db.all("SELECT * FROM automations ORDER BY name"):
            r["payload"] = json.loads(r["payload"])
            r["enabled"] = bool(r["enabled"])
            out.append(r)
        return out

    def set_enabled(self, aid: int, enabled: bool) -> dict | None:
        a = self.get(aid)
        if not a:
            return None
        nr = next_run(a["schedule"], time.time()) if enabled and a["schedule"] != "manual" else a["next_run"]
        self.app.db.update("automations", "id", aid, {"enabled": int(enabled), "next_run": nr})
        return self.get(aid)

    def delete(self, aid: int) -> bool:
        return self.app.db.execute("DELETE FROM automations WHERE id = ?", (aid,)).rowcount > 0

    def find(self, name: str) -> dict | None:
        r = self.app.db.one("SELECT id FROM automations WHERE lower(name) = lower(?)", (name.strip(),)) or \
            self.app.db.one("SELECT id FROM automations WHERE lower(name) LIKE lower(?)", (f"%{name.strip()}%",))
        return self.get(r["id"]) if r else None

    # -- Ausführung -------------------------------------------------------------------
    async def run(self, a: dict, source: str = "automation") -> str:
        kind, payload = a["action_type"], a["payload"]
        if kind == "briefing":
            b = await self.app.briefing()
            self.app.services.notify("briefing", "Tagesübersicht", b["text"])
            result = b["text"]
        elif kind == "reminder":
            self.app.services.notify("reminder", a["name"], payload.get("text", ""))
            result = "Benachrichtigung gesendet"
        elif kind == "prompt":
            out = await self.app.agent.run(payload.get("prompt", ""), source=source)
            self.app.services.notify("automation", a["name"], out["text"][:1000])
            result = out["text"]
        elif kind == "workflow":
            result = await self.run_steps(payload.get("steps", []), ToolContext(app=self.app, source=source))
            self.app.services.notify("automation", a["name"], result[:1000])
        else:
            result = f"Unbekannter Typ {kind}"
        self.app.db.update("automations", "id", a["id"], {"last_run": time.time(), "last_result": result[:2000]})
        self.app.db.audit(source, "automation_run", {"id": a["id"], "name": a["name"]})
        return result

    async def run_steps(self, steps: list[dict], ctx: ToolContext) -> str:
        async def noop(_ev: dict) -> None:
            return None

        lines = []
        for i, st in enumerate(steps, 1):
            res = await self.app.agent.execute(st["tool"], st.get("args", {}), ctx, noop)
            lines.append(f"{i}. {'✓' if res.ok else '✗'} {res.content.splitlines()[0][:200] if res.content else ''}")
            if not res.ok and st.get("stop_on_error", True):
                lines.append("Abgebrochen.")
                break
        return "\n".join(lines)

    async def tick(self) -> None:
        now = time.time()
        # Erinnerungen
        for r in self.app.db.all("SELECT * FROM reminders WHERE status = 'pending' AND due_at <= ?", (now,)):
            self.app.services.notify("reminder", "Erinnerung", r["text"])
            if r["repeat"]:
                sched = {"daily": "daily", "weekdays": "weekdays", "weekly": None}[r["repeat"]]
                t = dt.datetime.fromtimestamp(r["due_at"])
                if sched:
                    nxt = next_run(f"{sched} {t:%H:%M}", max(now, r["due_at"]))
                else:
                    nxt = r["due_at"] + 7 * 86400
                    while nxt <= now:
                        nxt += 7 * 86400
                self.app.db.update("reminders", "id", r["id"], {"due_at": nxt, "fired_at": now})
            else:
                self.app.db.update("reminders", "id", r["id"], {"status": "fired", "fired_at": now})
        # Automatisierungen
        for a in self.app.db.all("SELECT id FROM automations WHERE enabled = 1 AND next_run IS NOT NULL "
                                 "AND next_run <= ?", (now,)):
            auto = self.get(a["id"])
            try:
                nr = next_run(auto["schedule"], now)
            except ValueError:
                nr = None
            self.app.db.update("automations", "id", auto["id"], {"next_run": nr, "enabled": int(nr is not None)})
            asyncio.create_task(self._safe_run(auto))

    async def _safe_run(self, a: dict) -> None:
        try:
            await self.run(a)
        except Exception as exc:
            log.exception("Automatisierung %s fehlgeschlagen", a["name"])
            self.app.db.update("automations", "id", a["id"], {"last_result": f"Fehler: {exc}"})
            self.app.services.notify("error", f"Automatisierung '{a['name']}' fehlgeschlagen", str(exc))

    async def loop(self, interval: float) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("Scheduler-Fehler")
            await asyncio.sleep(interval)

    def start(self, interval: float) -> None:
        if not self._task:
            self._task = asyncio.create_task(self.loop(interval))

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


def register(reg: ToolRegistry) -> None:
    @reg.tool("run_workflow", "Einen gespeicherten Workflow bzw. eine Automatisierung per Name ausführen "
              "(z. B. 'Arbeitsbeginn'). Jeder Schritt wird einzeln berechtigt.",
              params({"name": {"type": "string"}}, ["name"]), LEVEL_READ, module="automation")
    async def run_workflow(ctx: ToolContext, name: str) -> ToolResult:
        auto = ctx.app.automations.find(name)
        if not auto:
            names = ", ".join(a["name"] for a in ctx.app.automations.list()) or "keine"
            return ToolResult(f"Kein Workflow '{name}' gefunden. Vorhanden: {names}", ok=False)
        if auto["action_type"] == "workflow":
            result = await ctx.app.automations.run_steps(auto["payload"].get("steps", []), ctx)
            ctx.app.db.update("automations", "id", auto["id"], {"last_run": time.time(), "last_result": result})
        elif auto["action_type"] == "prompt":
            return ToolResult("Prompt-Automatisierungen können nicht aus einem Gespräch gestartet werden.", ok=False)
        else:
            result = await ctx.app.automations.run(auto, source=ctx.source)
        return ToolResult(f"Workflow '{auto['name']}':\n{result}", {"automation": auto["id"]})

    @reg.tool("list_workflows", "Gespeicherte Workflows und Automatisierungen anzeigen.", params(), LEVEL_READ,
              module="automation")
    def list_workflows(ctx: ToolContext) -> ToolResult:
        autos = ctx.app.automations.list()
        if not autos:
            return ToolResult("Keine Automatisierungen vorhanden.", [])
        return ToolResult("\n".join(f"{a['name']} ({a['action_type']}, {a['schedule']}, "
                                    f"{'aktiv' if a['enabled'] else 'inaktiv'})" for a in autos), autos)
