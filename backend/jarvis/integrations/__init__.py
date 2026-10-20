"""Optionale Integrationen (einzeln aktivierbar).

* Home Assistant (REST-API mit Long-Lived-Token) – Smart Home
* n8n (Webhook-Auslösung) – externe Workflows

Gmail/Outlook/Kalender benötigen eigene OAuth-Client-Zugangsdaten und sind in
``documentation/INTEGRATIONEN.md`` als blockiert dokumentiert.
"""
from __future__ import annotations

import httpx

from ..security.permissions import LEVEL_CHANGE, LEVEL_READ
from ..tools.registry import ToolContext, ToolRegistry, ToolResult, params


def _ha(ctx: ToolContext) -> tuple[str, str] | None:
    url = (ctx.app.db.get_setting("home_assistant_url", "") or "").rstrip("/")
    token = ctx.app.secrets.get("home_assistant_token")
    return (url, token) if url and token else None


def register(reg: ToolRegistry) -> None:
    @reg.tool("smarthome_states", "Zustände von Smart-Home-Geräten aus Home Assistant lesen (optional Filter, "
              "z. B. 'light' oder 'wohnzimmer').", params({"filter": {"type": "string"}}), LEVEL_READ,
              module="smarthome")
    async def smarthome_states(ctx: ToolContext, filter: str = "") -> ToolResult:
        cfg = _ha(ctx)
        if not cfg:
            return ToolResult("Home Assistant ist nicht eingerichtet (URL in Einstellungen, Token im Schlüsselspeicher).",
                              ok=False)
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{cfg[0]}/api/states", headers={"Authorization": f"Bearer {cfg[1]}"})
            r.raise_for_status()
        f = filter.lower()
        states = [s for s in r.json() if not f or f in s["entity_id"].lower()
                  or f in str(s.get("attributes", {}).get("friendly_name", "")).lower()]
        lines = [f"{s['entity_id']}: {s['state']}" for s in states[:60]]
        return ToolResult("\n".join(lines) or "Keine passenden Geräte.", states[:60], untrusted=True)

    @reg.tool("smarthome_action", "Ein Smart-Home-Gerät schalten (Home Assistant Service, z. B. domain=light, "
              "service=turn_on, entity_id=light.wohnzimmer).",
              params({"domain": {"type": "string"}, "service": {"type": "string"}, "entity_id": {"type": "string"},
                      "data": {"type": "object"}}, ["domain", "service", "entity_id"]), LEVEL_CHANGE,
              module="smarthome", summarize=lambda a: f"Smart Home: {a.get('domain')}.{a.get('service')} → {a.get('entity_id')}")
    async def smarthome_action(ctx: ToolContext, domain: str, service: str, entity_id: str,
                               data: dict | None = None) -> ToolResult:
        cfg = _ha(ctx)
        if not cfg:
            return ToolResult("Home Assistant ist nicht eingerichtet.", ok=False)
        if domain in {"lock", "alarm_control_panel", "homeassistant", "hassio"}:
            return ToolResult("Sicherheitsrelevante Domänen werden nicht gesteuert.", ok=False)
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{cfg[0]}/api/services/{domain}/{service}",
                             headers={"Authorization": f"Bearer {cfg[1]}"},
                             json={"entity_id": entity_id, **(data or {})})
            r.raise_for_status()
        return ToolResult(f"{domain}.{service} für {entity_id} ausgeführt.")

    @reg.tool("run_n8n_workflow", "Einen freigegebenen n8n-Workflow per Webhook auslösen (Name aus Einstellungen).",
              params({"name": {"type": "string"}, "payload": {"type": "object"}}, ["name"]), LEVEL_CHANGE,
              module="n8n", summarize=lambda a: f"n8n-Workflow auslösen: {a.get('name')}")
    async def run_n8n(ctx: ToolContext, name: str, payload: dict | None = None) -> ToolResult:
        hooks = ctx.app.db.get_setting("n8n_webhooks", {}) or {}
        url = hooks.get(name)
        if not url:
            return ToolResult(f"Kein n8n-Webhook '{name}' konfiguriert. Verfügbar: {', '.join(hooks) or 'keine'}",
                              ok=False)
        headers = {}
        secret = ctx.app.secrets.get("n8n_webhook_secret")
        if secret:
            headers["X-Jarvis-Secret"] = secret
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(url, json=payload or {}, headers=headers)
        return ToolResult(f"Workflow '{name}' ausgelöst (HTTP {r.status_code}).", {"status": r.status_code,
                                                                                    "body": r.text[:2000]},
                          ok=r.is_success, untrusted=True)
