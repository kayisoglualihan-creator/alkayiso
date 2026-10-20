"""FastAPI-Anwendung: REST-Endpunkte, Server-Sent-Events, WebSocket und Weboberfläche (PWA)."""
from __future__ import annotations

import asyncio
import base64
import json
import platform
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, File, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import network
from ..config import APP_NAME, VERSION, Settings, load_settings
from ..core import MODULES, PROVIDERS, Jarvis
from ..memory import CATEGORIES
from ..security.permissions import LEVEL_CRITICAL
from ..security.secrets import KNOWN_SECRETS
from ..security.tokens import AuthError, Principal
from ..tools.system import system_snapshot
from ..voice import VoiceService
from .deps import ApiError, RateLimiter, admin, app_of, is_local_request, principal, resolve_principal

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    conversation_id: str | None = None


class JobIn(BaseModel):
    text: str = Field(min_length=1, max_length=5_000)
    conversation_id: str | None = None


class DecisionIn(BaseModel):
    approve: bool
    confirm_text: str | None = None


class RefreshIn(BaseModel):
    device_id: str
    refresh_token: str


class ClaimIn(BaseModel):
    pairing_id: str
    code: str
    device_name: str = Field(default="iPhone", max_length=64)
    platform: str = Field(default="ios", max_length=32)


class PollIn(BaseModel):
    pairing_id: str
    claim_secret: str


class PairDecisionIn(BaseModel):
    approve: bool


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    notes: str = ""
    due: str | float | None = None
    priority: int = Field(default=2, ge=1, le=3)
    project: str = ""


class TaskPatch(BaseModel):
    title: str | None = None
    notes: str | None = None
    status: Literal["open", "done"] | None = None
    priority: int | None = Field(default=None, ge=1, le=3)
    project: str | None = None
    due: str | float | None = None


class ReminderIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    when: str | float
    repeat: Literal["", "daily", "weekly", "weekdays"] = ""


class MemoryIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    category: str = "allgemein"
    importance: float = Field(default=0.5, ge=0, le=1)


class MemoryPatch(BaseModel):
    content: str | None = None
    category: str | None = None
    importance: float | None = Field(default=None, ge=0, le=1)


class ListItemIn(BaseModel):
    list_name: str = "einkauf"
    text: str = Field(min_length=1, max_length=300)


class AutomationIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    schedule: str
    action_type: Literal["briefing", "reminder", "prompt", "workflow"]
    payload: dict = {}
    enabled: bool = True


class GrantIn(BaseModel):
    mode: Literal["auto", "ask", "deny"]


class SecretIn(BaseModel):
    value: str = Field(min_length=1, max_length=500)


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


SETTINGS_KEYS = {
    "ai_provider": str, "ai_models": dict, "ai_max_tokens": int, "anthropic_effort": str,
    "anthropic_refusal_fallback": bool, "openai_base_url": str, "ollama_url": str, "ai_prices": dict,
    "disabled_modules": list, "remote_blocked_tools": list, "allow_remote_critical_approval": bool,
    "allowed_roots": list, "app_aliases": dict, "public_url": str, "user_name": str, "language": str,
    "tts_engine": str, "whisper_model": str, "piper_model_path": str, "elevenlabs_voice_id": str,
    "voice_rate": (int, float), "voice_volume": (int, float), "voice_name": str, "wake_word_enabled": bool,
    "home_assistant_url": str, "calendar_ics_urls": list, "n8n_webhooks": dict, "close_to_tray": bool, "setup_completed": bool, "google_client_id": str, "microsoft_client_id": str,
    "browser_headless": bool, "browser_executable": str, "browser_allow_private": bool,
}


def _start_wake(app: FastAPI) -> bool:
    from ..voice.wakeword import WakeWordLoop

    if not WakeWordLoop.available():
        return False
    if app.state.wake is None:
        app.state.wake = WakeWordLoop(app.state.jarvis, app.state.voice, asyncio.get_running_loop())
    app.state.wake.start()
    return True


# ---------------------------------------------------------------------------
def create_app(settings: Settings | None = None, *, dry_run: bool = False) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        jarvis = Jarvis(settings, dry_run=dry_run)
        app.state.jarvis = jarvis
        app.state.voice = VoiceService(settings.data_dir, jarvis.secrets, jarvis.db)
        app.state.wake = None
        await jarvis.start()
        if jarvis.db.get_setting("wake_word_enabled", False):
            _start_wake(app)
        yield
        if app.state.wake:
            app.state.wake.stop()
        await jarvis.stop()

    app = FastAPI(title="JARVIS CORE API", version=VERSION, lifespan=lifespan,
                  description="Persönlicher KI-Assistent – lokale API (Standard: nur 127.0.0.1, Fernzugriff über "
                              "Tailscale Serve).")
    claim_limit = RateLimiter(10, 300)

    @app.exception_handler(ApiError)
    async def api_error(_req: Request, exc: ApiError):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status)

    @app.exception_handler(AuthError)
    async def auth_error(_req: Request, exc: AuthError):
        status = 404 if exc.code == "pairing_not_found" else 400 if exc.code.startswith("pairing") else 401
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=status)

    @app.exception_handler(ValueError)
    async def value_error(_req: Request, exc: ValueError):
        return JSONResponse({"error": {"code": "invalid_input", "message": str(exc)}}, status_code=400)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    # ------------------------------------------------------------------ Status
    @app.get("/api/health", tags=["status"])
    def health():
        return {"status": "ok", "name": APP_NAME, "version": VERSION, "time": time.time()}

    @app.get("/api/status", tags=["status"])
    def status(request: Request, p: Principal = Depends(principal)):
        j = app_of(request)
        cfg = j.ai_config()
        provider = j.provider()
        return {
            "online": True, "version": VERSION, "hostname": platform.node(), "uptime_s": int(time.time() - j.started_at),
            "system": system_snapshot(), "ai": {"provider": provider.name, "model": provider.model,
                                               "configured_provider": cfg["provider"]},
            "open_tasks": j.db.one("SELECT COUNT(*) AS n FROM tasks WHERE status='open'")["n"],
            "pending_approvals": len(j.approvals.pending(None if p.is_admin else p.device_id)),
            "unread_notifications": j.db.one("SELECT COUNT(*) AS n FROM notifications WHERE read=0")["n"],
            "remote_access_enabled": bool(j.db.get_setting("remote_access_enabled", True)),
            "principal": {"kind": p.kind, "device_id": p.device_id, "name": p.name},
            "dry_run": j.dry_run,
        }

    # ------------------------------------------------------------------ Auth & Pairing
    @app.get("/api/auth/me", tags=["auth"])
    def me(p: Principal = Depends(principal)):
        return {"kind": p.kind, "device_id": p.device_id, "name": p.name}

    @app.post("/api/auth/refresh", tags=["auth"])
    def refresh(body: RefreshIn, request: Request):
        return app_of(request).tokens.refresh(body.device_id, body.refresh_token)

    def public_base(request: Request) -> str:
        j = app_of(request)
        url = j.db.get_setting("public_url", "") or settings.public_url
        if not url:
            ts = network.tailscale_status()
            url = ts.get("https_url") or ""
        return (url or str(request.base_url)).rstrip("/")

    @app.post("/api/pairing/start", tags=["pairing"])
    def pairing_start(request: Request, _: Principal = Depends(admin)):
        import qrcode
        import qrcode.image.svg

        j = app_of(request)
        p = j.pairing.start()
        base = public_base(request)
        payload = {"v": 1, "url": base, "pid": p["pairing_id"], "code": p["code"], "host": platform.node()}
        enc = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
        link = f"{base}/#pair={enc}"
        img = qrcode.make(link, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
        svg = img.to_string(encoding="unicode")
        j.db.audit("desktop", "pairing_started", {"pairing": p["pairing_id"]})
        return {**p, "link": link, "payload": payload, "qr_svg": svg, "base_url": base,
                "tailscale_url_detected": base.startswith("https://") and ".ts.net" in base}

    @app.get("/api/pairing/pending", tags=["pairing"])
    def pairing_pending(request: Request, _: Principal = Depends(admin)):
        return app_of(request).pairing.pending()

    @app.post("/api/pairing/{pairing_id}/decision", tags=["pairing"])
    def pairing_decision(pairing_id: str, body: PairDecisionIn, request: Request, _: Principal = Depends(admin)):
        j = app_of(request)
        out = j.pairing.decide(pairing_id, body.approve)
        j.db.audit("desktop", "pairing_" + out["status"], {"pairing": pairing_id, "device": out.get("device_id")}, 3)
        j.bus.publish("devices.changed", {}, admin_only=True)
        return out

    @app.post("/api/pairing/claim", tags=["pairing"])
    def pairing_claim(body: ClaimIn, request: Request):
        j = app_of(request)
        claim_limit.check(request.client.host if request.client else "?")
        ts_login = request.headers.get("tailscale-user-login")
        if settings.require_tailscale_for_pairing and not ts_login and not is_local_request(request):
            raise ApiError(403, "tailscale_required",
                           "Kopplung nur über das private Tailscale-Netzwerk (Tailscale Serve) möglich")
        out = j.pairing.claim(body.pairing_id, body.code, body.device_name, body.platform, ts_login)
        j.db.audit("unauthenticated", "pairing_claimed", {"pairing": body.pairing_id, "device": body.device_name,
                                                          "tailscale_login": ts_login}, 2)
        j.bus.publish("pairing.claimed", {"pairing_id": body.pairing_id, "device_name": body.device_name,
                                          "verify_code": out["verify_code"]}, admin_only=True)
        return out

    @app.post("/api/pairing/poll", tags=["pairing"])
    def pairing_poll(body: PollIn, request: Request):
        return app_of(request).pairing.poll(body.pairing_id, body.claim_secret)

    # ------------------------------------------------------------------ Geräte
    @app.get("/api/devices", tags=["devices"])
    def devices(request: Request, _: Principal = Depends(admin)):
        return app_of(request).db.all("SELECT id, name, platform, created_at, last_seen, revoked_at, tailscale_login "
                                      "FROM devices ORDER BY created_at DESC")

    @app.delete("/api/devices/{device_id}", tags=["devices"])
    def revoke_device(device_id: str, request: Request, _: Principal = Depends(admin)):
        j = app_of(request)
        if not j.tokens.revoke_device(device_id):
            raise ApiError(404, "device_not_found", "Gerät nicht gefunden")
        j.db.audit("desktop", "device_revoked", {"device": device_id}, 3)
        j.bus.publish("device.revoked", {"device_id": device_id})
        return {"revoked": device_id}

    @app.get("/api/remote-access", tags=["devices"])
    def remote_access_get(request: Request, _: Principal = Depends(admin)):
        return {"enabled": bool(app_of(request).db.get_setting("remote_access_enabled", True))}

    @app.post("/api/remote-access", tags=["devices"])
    def remote_access_set(body: dict, request: Request, _: Principal = Depends(admin)):
        j = app_of(request)
        enabled = bool(body.get("enabled"))
        j.db.set_setting("remote_access_enabled", enabled)
        j.db.audit("desktop", "remote_access_" + ("enabled" if enabled else "disabled"), risk=3)
        return {"enabled": enabled}

    # ------------------------------------------------------------------ Konten (OAuth: Google, Microsoft)
    @app.get("/api/integrations", tags=["integrations"])
    def integrations(request: Request, _: Principal = Depends(admin)):
        j = app_of(request)
        return {"accounts": j.oauth.status(),
                "redirect_uris": {p: j.oauth.redirect_uri(p) for p in ("google", "microsoft")}}

    @app.post("/api/integrations/{provider}/connect", tags=["integrations"])
    def integration_connect(provider: str, request: Request, _: Principal = Depends(admin)):
        from ..integrations.oauth import OAuthError
        try:
            return {"url": app_of(request).oauth.start(provider)}
        except OAuthError as exc:
            raise ApiError(400, "oauth_not_configured", str(exc))

    @app.delete("/api/integrations/{provider}", tags=["integrations"])
    def integration_disconnect(provider: str, request: Request, _: Principal = Depends(admin)):
        j = app_of(request)
        j.oauth.disconnect(provider)
        j.db.audit("desktop", "oauth_disconnected", {"provider": provider}, 2)
        return {"connected": False}

    @app.get("/oauth/callback", include_in_schema=False)
    async def oauth_callback(request: Request, state: str = "", code: str = "", error: str = ""):
        from ..integrations.oauth import OAuthError
        page = ('<!doctype html><meta charset="utf-8"><title>JARVIS</title><body style="background:#02060d;color:#e6f6ff;'
                'font-family:Segoe UI,sans-serif;display:grid;place-items:center;height:100vh"><div style="text-align:center">'
                '<h2 style="color:#00e5ff;letter-spacing:.2em">J.A.R.V.I.S.</h2><p>{msg}</p></div>')
        if not is_local_request(request):  # Rückleitung erfolgt immer im Browser auf diesem PC
            return HTMLResponse(page.format(msg="Nur lokal am PC möglich."), status_code=403)
        if error or not code:
            return HTMLResponse(page.format(msg=f"Anmeldung abgebrochen ({error or 'kein Code'})."), status_code=400)
        j = app_of(request)
        try:
            provider = await j.oauth.finish(state, code)
        except OAuthError as exc:
            return HTMLResponse(page.format(msg=str(exc)), status_code=400)
        j.db.audit("desktop", "oauth_connected", {"provider": provider}, 3)
        j.bus.publish("integrations.changed", {"provider": provider}, admin_only=True)
        return HTMLResponse(page.format(msg="Konto verbunden. Du kannst dieses Fenster schließen."))

    @app.get("/api/system/autostart", tags=["settings"])
    def autostart_get(_: Principal = Depends(admin)):
        from ..windows_agent import IS_WINDOWS, autostart_enabled
        return {"supported": IS_WINDOWS, "enabled": autostart_enabled()}

    @app.post("/api/system/autostart", tags=["settings"])
    def autostart_set(body: dict, request: Request, _: Principal = Depends(admin)):
        from ..windows_agent import IS_WINDOWS, set_autostart
        if not IS_WINDOWS:
            raise ApiError(501, "autostart_unsupported", "Autostart ist nur unter Windows verfügbar")
        enabled = set_autostart(bool(body.get("enabled")))
        app_of(request).db.audit("desktop", "autostart_" + ("on" if enabled else "off"), risk=2)
        return {"supported": True, "enabled": enabled}

    @app.get("/api/network/tailscale", tags=["devices"])
    def tailscale(_: Principal = Depends(admin)):
        return network.tailscale_status()

    # ------------------------------------------------------------------ Chat
    @app.post("/api/chat", tags=["chat"])
    async def chat(body: ChatIn, request: Request, p: Principal = Depends(principal)):
        return await app_of(request).agent.run(body.message, source=p.actor, conversation_id=body.conversation_id)

    @app.post("/api/chat/stream", tags=["chat"])
    async def chat_stream(body: ChatIn, request: Request, p: Principal = Depends(principal)):
        j = app_of(request)
        queue: asyncio.Queue = asyncio.Queue()

        async def emit(ev: dict) -> None:
            await queue.put(ev)

        async def runner():
            try:
                await j.agent.run(body.message, source=p.actor, conversation_id=body.conversation_id, emit=emit)
            except Exception as exc:
                await queue.put({"type": "error", "code": "internal", "message": str(exc)})
            finally:
                await queue.put(None)

        task = asyncio.create_task(runner())

        async def gen():
            while True:
                ev = await queue.get()
                if ev is None:
                    break
                yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
            await task

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/api/conversations", tags=["chat"])
    def conversations(request: Request, _: Principal = Depends(principal)):
        return app_of(request).db.all("SELECT * FROM conversations ORDER BY updated_at DESC LIMIT 100")

    @app.get("/api/conversations/{cid}/messages", tags=["chat"])
    def conversation_messages(cid: str, request: Request, _: Principal = Depends(principal)):
        rows = app_of(request).db.all("SELECT * FROM messages WHERE conversation_id = ? ORDER BY id", (cid,))
        for r in rows:
            r["meta"] = json.loads(r["meta"]) if r["meta"] else None
        return rows

    @app.delete("/api/conversations/{cid}", tags=["chat"])
    def conversation_delete(cid: str, request: Request, _: Principal = Depends(principal)):
        app_of(request).db.execute("DELETE FROM conversations WHERE id = ?", (cid,))
        return {"deleted": cid}

    # ------------------------------------------------------------------ Fernaufträge
    @app.post("/api/jobs", tags=["remote"], status_code=202)
    async def job_submit(body: JobIn, request: Request, p: Principal = Depends(principal)):
        return app_of(request).jobs.submit(body.text, p.actor, p.device_id, body.conversation_id)

    @app.get("/api/jobs", tags=["remote"])
    def job_list(request: Request, p: Principal = Depends(principal)):
        return app_of(request).jobs.list(None if p.is_admin else p.device_id)

    def _own_job(request: Request, p: Principal, job_id: str) -> dict:
        job = app_of(request).jobs.get(job_id)
        if not job or (not p.is_admin and job["device_id"] != p.device_id):
            raise ApiError(404, "job_not_found", "Auftrag nicht gefunden")
        return job

    @app.get("/api/jobs/{job_id}", tags=["remote"])
    async def job_get(job_id: str, request: Request, wait: float = Query(0, ge=0, le=25),
                      p: Principal = Depends(principal)):
        _own_job(request, p, job_id)
        if wait:
            return await app_of(request).jobs.wait(job_id, wait)
        return app_of(request).jobs.get(job_id)

    @app.post("/api/jobs/{job_id}/cancel", tags=["remote"])
    async def job_cancel(job_id: str, request: Request, p: Principal = Depends(principal)):
        _own_job(request, p, job_id)
        return {"cancelled": app_of(request).jobs.cancel(job_id)}

    # ------------------------------------------------------------------ Genehmigungen
    @app.get("/api/approvals", tags=["approvals"])
    def approvals(request: Request, p: Principal = Depends(principal)):
        return app_of(request).approvals.pending(None if p.is_admin else p.device_id)

    @app.post("/api/approvals/{approval_id}", tags=["approvals"])
    def approval_decide(approval_id: str, body: DecisionIn, request: Request, p: Principal = Depends(principal)):
        try:
            return app_of(request).approvals.decide(approval_id, body.approve, p.actor, is_admin=p.is_admin,
                                                    device_id=p.device_id, confirm_text=body.confirm_text)
        except KeyError:
            raise ApiError(404, "approval_not_found", "Genehmigung nicht gefunden")
        except PermissionError as exc:
            raise ApiError(403, "approval_forbidden", str(exc))
        except ValueError as exc:
            raise ApiError(409, "approval_closed", str(exc))

    # ------------------------------------------------------------------ Aufgaben
    @app.get("/api/tasks", tags=["tasks"])
    def tasks(request: Request, status: str = "all", project: str | None = None, _: Principal = Depends(principal)):
        return app_of(request).services.list_tasks(status, project)

    @app.post("/api/tasks", tags=["tasks"], status_code=201)
    def task_add(body: TaskIn, request: Request, _: Principal = Depends(principal)):
        return app_of(request).services.add_task(body.title, body.notes, body.due, body.priority, body.project)

    @app.patch("/api/tasks/{tid}", tags=["tasks"])
    def task_patch(tid: int, body: TaskPatch, request: Request, _: Principal = Depends(principal)):
        t = app_of(request).services.update_task(tid, **body.model_dump())
        if not t:
            raise ApiError(404, "task_not_found", "Aufgabe nicht gefunden")
        return t

    @app.delete("/api/tasks/{tid}", tags=["tasks"])
    def task_delete(tid: int, request: Request, _: Principal = Depends(principal)):
        if not app_of(request).services.delete_task(tid):
            raise ApiError(404, "task_not_found", "Aufgabe nicht gefunden")
        return {"deleted": tid}

    # ------------------------------------------------------------------ Erinnerungen
    @app.get("/api/reminders", tags=["tasks"])
    def reminders(request: Request, include_done: bool = False, _: Principal = Depends(principal)):
        return app_of(request).services.list_reminders(include_done)

    @app.post("/api/reminders", tags=["tasks"], status_code=201)
    def reminder_add(body: ReminderIn, request: Request, _: Principal = Depends(principal)):
        return app_of(request).services.add_reminder(body.text, body.when, body.repeat)

    @app.delete("/api/reminders/{rid}", tags=["tasks"])
    def reminder_delete(rid: int, request: Request, _: Principal = Depends(principal)):
        return {"deleted": app_of(request).services.delete_reminder(rid)}

    @app.get("/api/briefing", tags=["tasks"])
    async def briefing(request: Request, _: Principal = Depends(principal)):
        return await app_of(request).briefing()

    # ------------------------------------------------------------------ Gedächtnis
    @app.get("/api/memory", tags=["memory"])
    def memory_list(request: Request, q: str | None = None, category: str | None = None,
                    _: Principal = Depends(principal)):
        m = app_of(request).memory
        return m.search(q, limit=20, min_score=0.05) if q else m.list(category)

    @app.post("/api/memory", tags=["memory"], status_code=201)
    def memory_add(body: MemoryIn, request: Request, p: Principal = Depends(principal)):
        if body.category not in CATEGORIES:
            raise ApiError(400, "invalid_category", f"Kategorie muss eine von {CATEGORIES} sein")
        return app_of(request).memory.add(body.content, body.category, body.importance, source=p.actor)

    @app.patch("/api/memory/{mid}", tags=["memory"])
    def memory_patch(mid: int, body: MemoryPatch, request: Request, _: Principal = Depends(principal)):
        m = app_of(request).memory.update(mid, body.content, body.category, body.importance)
        if not m:
            raise ApiError(404, "memory_not_found", "Erinnerung nicht gefunden")
        return m

    @app.delete("/api/memory/{mid}", tags=["memory"])
    def memory_delete(mid: int, request: Request, _: Principal = Depends(principal)):
        if not app_of(request).memory.delete(mid):
            raise ApiError(404, "memory_not_found", "Erinnerung nicht gefunden")
        return {"deleted": mid}

    @app.delete("/api/memory", tags=["memory"])
    def memory_clear(request: Request, confirm: bool = False, _: Principal = Depends(admin)):
        if not confirm:
            raise ApiError(400, "confirm_required", "Zum vollständigen Löschen ?confirm=true angeben")
        j = app_of(request)
        n = j.memory.clear()
        j.db.audit("desktop", "memory_cleared", {"count": n}, 3)
        return {"deleted": n}

    # ------------------------------------------------------------------ Listen / Gewohnheiten / Budget
    @app.get("/api/lists", tags=["personal"])
    def lists(request: Request, name: str | None = None, _: Principal = Depends(principal)):
        return app_of(request).services.list_items(name)

    @app.post("/api/lists", tags=["personal"], status_code=201)
    def list_add(body: ListItemIn, request: Request, _: Principal = Depends(principal)):
        return app_of(request).services.list_add(body.list_name, body.text)

    @app.patch("/api/lists/{iid}", tags=["personal"])
    def list_check(iid: int, body: dict, request: Request, _: Principal = Depends(principal)):
        app_of(request).services.list_check(iid, bool(body.get("checked", True)))
        return {"id": iid, "checked": bool(body.get("checked", True))}

    @app.delete("/api/lists/{iid}", tags=["personal"])
    def list_remove(iid: int, request: Request, _: Principal = Depends(principal)):
        return {"deleted": app_of(request).services.list_remove(iid)}

    @app.get("/api/habits", tags=["personal"])
    def habits(request: Request, _: Principal = Depends(principal)):
        return app_of(request).services.habit_stats()

    @app.post("/api/habits/{name}/log", tags=["personal"])
    def habit_log(name: str, request: Request, _: Principal = Depends(principal)):
        return app_of(request).services.habit_log(name)

    @app.get("/api/budget", tags=["personal"])
    def budget(request: Request, month: str | None = None, _: Principal = Depends(principal)):
        return app_of(request).services.budget_summary(month)

    @app.post("/api/budget", tags=["personal"], status_code=201)
    def budget_add(body: dict, request: Request, _: Principal = Depends(principal)):
        return app_of(request).services.budget_add(float(body["amount"]), str(body.get("category", "sonstiges")),
                                                   str(body.get("note", "")))

    # ------------------------------------------------------------------ Benachrichtigungen
    @app.get("/api/notifications", tags=["notifications"])
    def notifications(request: Request, unread: bool = False, _: Principal = Depends(principal)):
        return app_of(request).services.notifications(unread)

    @app.post("/api/notifications/read", tags=["notifications"])
    def notifications_read(request: Request, body: dict | None = None, _: Principal = Depends(principal)):
        app_of(request).services.mark_read((body or {}).get("id"))
        return {"ok": True}

    # ------------------------------------------------------------------ Automatisierungen
    @app.get("/api/automations", tags=["automation"])
    def automations(request: Request, _: Principal = Depends(principal)):
        return app_of(request).automations.list()

    @app.post("/api/automations", tags=["automation"], status_code=201)
    def automation_add(body: AutomationIn, request: Request, _: Principal = Depends(admin)):
        j = app_of(request)
        a = j.automations.create(body.name, body.schedule, body.action_type, body.payload, body.enabled)
        j.db.audit("desktop", "automation_created", {"id": a["id"], "name": a["name"]}, 2)
        return a

    @app.patch("/api/automations/{aid}", tags=["automation"])
    def automation_toggle(aid: int, body: dict, request: Request, _: Principal = Depends(admin)):
        a = app_of(request).automations.set_enabled(aid, bool(body.get("enabled")))
        if not a:
            raise ApiError(404, "automation_not_found", "Automatisierung nicht gefunden")
        return a

    @app.delete("/api/automations/{aid}", tags=["automation"])
    def automation_delete(aid: int, request: Request, _: Principal = Depends(admin)):
        return {"deleted": app_of(request).automations.delete(aid)}

    @app.post("/api/automations/{aid}/run", tags=["automation"])
    async def automation_run(aid: int, request: Request, p: Principal = Depends(principal)):
        j = app_of(request)
        a = j.automations.get(aid)
        if not a:
            raise ApiError(404, "automation_not_found", "Automatisierung nicht gefunden")
        if a["action_type"] == "prompt" and not p.is_admin:
            raise ApiError(403, "admin_required", "Prompt-Automatisierungen nur am PC")
        return {"result": await j.automations.run(a, source=p.actor)}

    # ------------------------------------------------------------------ Einstellungen & Berechtigungen
    @app.get("/api/settings", tags=["settings"])
    def settings_get(request: Request, _: Principal = Depends(admin)):
        j = app_of(request)
        values = {k: j.db.get_setting(k) for k in SETTINGS_KEYS}
        return {"values": values, "ai": j.ai_config(), "modules": MODULES, "disabled_modules": sorted(j.disabled_modules()),
                "secrets": j.secrets.status(), "secret_backend": j.secrets.backend_name(), "providers": PROVIDERS,
                "allowed_roots": [str(p) for p in (j.db.get_setting("allowed_roots") or settings.allowed_roots)],
                "data_dir": str(settings.data_dir), "output_dir": str(settings.output_dir),
                "voice": request.app.state.voice.status()}

    @app.patch("/api/settings", tags=["settings"])
    def settings_patch(body: dict[str, Any], request: Request, _: Principal = Depends(admin)):
        j = app_of(request)
        changed = {}
        for key, value in body.items():
            typ = SETTINGS_KEYS.get(key)
            if typ is None:
                raise ApiError(400, "unknown_setting", f"Unbekannte Einstellung: {key}")
            if value is not None and not isinstance(value, typ):
                raise ApiError(400, "invalid_setting", f"Falscher Typ für {key}")
            if key == "ai_provider" and value not in PROVIDERS:
                raise ApiError(400, "invalid_setting", f"Provider muss einer von {PROVIDERS} sein")
            if key == "disabled_modules" and any(m not in MODULES for m in value):
                raise ApiError(400, "invalid_setting", "Unbekanntes Modul")
            j.db.set_setting(key, value)
            changed[key] = value
        j.db.audit("desktop", "settings_changed", {"keys": list(changed)}, 2)
        return {"changed": list(changed)}

    @app.put("/api/secrets/{name}", tags=["settings"])
    def secret_set(name: str, body: SecretIn, request: Request, _: Principal = Depends(admin)):
        if name not in KNOWN_SECRETS:
            raise ApiError(400, "unknown_secret", "Unbekannter Schlüsselname")
        j = app_of(request)
        j.secrets.set(name, body.value.strip())
        j.db.audit("desktop", "secret_set", {"name": name}, 3)  # Wert wird nie geloggt
        return {"name": name, "stored": True, "backend": j.secrets.backend_name()}

    @app.delete("/api/secrets/{name}", tags=["settings"])
    def secret_delete(name: str, request: Request, _: Principal = Depends(admin)):
        if name not in KNOWN_SECRETS:
            raise ApiError(400, "unknown_secret", "Unbekannter Schlüsselname")
        app_of(request).secrets.delete(name)
        return {"name": name, "stored": False}

    @app.post("/api/ai/test", tags=["settings"])
    async def ai_test(request: Request, _: Principal = Depends(admin)):
        j = app_of(request)
        provider = j.provider()
        try:
            resp = await provider.complete("Antworte mit genau einem Wort.", [{"role": "user", "content": "Sag 'Bereit'."}], [])
        except Exception as exc:
            return {"ok": False, "provider": provider.name, "error": str(exc)}
        j.record_usage(provider, resp)
        return {"ok": True, "provider": provider.name, "model": provider.model, "reply": resp.text[:200]}

    @app.get("/api/tools", tags=["settings"])
    def tools(request: Request, _: Principal = Depends(admin)):
        j = app_of(request)
        grants = j.policy.grants()
        disabled = j.disabled_modules()
        blocked = set(j.db.get_setting("remote_blocked_tools", []) or [])
        return [{"name": t.name, "description": t.description, "risk": t.risk, "module": t.module,
                 "grant": grants.get(t.name, "default"), "active": t.module not in disabled and t.available(),
                 "remote_blocked": t.name in blocked} for t in j.registry.all()]

    @app.put("/api/tools/{name}/grant", tags=["settings"])
    def tool_grant(name: str, body: GrantIn, request: Request, _: Principal = Depends(admin)):
        j = app_of(request)
        tool = j.registry.get(name)
        if not tool:
            raise ApiError(404, "tool_not_found", "Werkzeug nicht gefunden")
        try:
            j.policy.set_grant(name, body.mode, tool.risk)
        except ValueError as exc:
            raise ApiError(400, "invalid_grant", str(exc))
        j.db.audit("desktop", "grant_changed", {"tool": name, "mode": body.mode}, 3 if tool.risk >= LEVEL_CRITICAL else 2)
        return {"tool": name, "mode": body.mode}

    @app.get("/api/audit", tags=["settings"])
    def audit(request: Request, limit: int = Query(100, le=1000), _: Principal = Depends(admin)):
        rows = app_of(request).db.all("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))
        for r in rows:
            r["detail"] = json.loads(r["detail"]) if r["detail"] else None
        return rows

    @app.get("/api/usage", tags=["settings"])
    def usage(request: Request, _: Principal = Depends(admin)):
        db = app_of(request).db
        return {"total": db.one("SELECT COALESCE(SUM(input_tokens),0) AS input_tokens, "
                                "COALESCE(SUM(output_tokens),0) AS output_tokens, COALESCE(SUM(cost),0) AS cost, "
                                "COUNT(*) AS calls FROM usage"),
                "by_model": db.all("SELECT provider, model, SUM(input_tokens) AS input_tokens, SUM(output_tokens) "
                                   "AS output_tokens, SUM(cost) AS cost, COUNT(*) AS calls FROM usage "
                                   "GROUP BY provider, model")}

    @app.get("/api/undo", tags=["settings"])
    def undo_list(request: Request, _: Principal = Depends(admin)):
        return app_of(request).db.all("SELECT * FROM undo_log WHERE done = 0 ORDER BY id DESC LIMIT 50")

    @app.post("/api/undo/{uid}", tags=["settings"])
    def undo_apply(uid: int, request: Request, _: Principal = Depends(admin)):
        return {"result": app_of(request).apply_undo(uid)}

    # ------------------------------------------------------------------ Sprache
    @app.get("/api/voice/status", tags=["voice"])
    def voice_status(request: Request, _: Principal = Depends(principal)):
        return request.app.state.voice.status()

    @app.post("/api/voice/wakeword", tags=["voice"])
    async def voice_wakeword(body: dict, request: Request, _: Principal = Depends(admin)):
        """Lokale Wake-Word-Schleife ("Hey Jarvis") am PC ein-/ausschalten."""
        j = app_of(request)
        enabled = bool(body.get("enabled"))
        j.db.set_setting("wake_word_enabled", enabled)
        if enabled:
            if not _start_wake(request.app):
                raise ApiError(501, "wakeword_unavailable",
                               "openWakeWord/sounddevice nicht installiert (requirements-voice.txt)")
        elif request.app.state.wake:
            request.app.state.wake.stop()
        j.db.audit("desktop", "wakeword_" + ("on" if enabled else "off"), risk=2)
        return {"enabled": enabled}

    @app.post("/api/voice/transcribe", tags=["voice"])
    async def voice_transcribe(request: Request, audio: UploadFile = File(...), language: str = "de",
                               _: Principal = Depends(principal)):
        data = await audio.read()
        if len(data) > 25 * 1024 * 1024:
            raise ApiError(413, "audio_too_large", "Audio zu groß (max. 25 MB)")
        suffix = Path(audio.filename or "a.webm").suffix or ".webm"
        try:
            return await request.app.state.voice.transcribe(data, suffix, language or None)
        except RuntimeError as exc:
            raise ApiError(501, "stt_unavailable", str(exc))

    @app.post("/api/voice/speak", tags=["voice"])
    async def voice_speak(body: SpeakIn, request: Request, _: Principal = Depends(principal)):
        try:
            audio, mime = await request.app.state.voice.speak(body.text)
        except RuntimeError as exc:
            raise ApiError(501, "tts_unavailable", str(exc))
        return Response(audio, media_type=mime)

    # ------------------------------------------------------------------ WebSocket
    @app.websocket("/ws")
    async def ws(websocket: WebSocket, token: str | None = None):
        j: Jarvis = websocket.app.state.jarvis
        try:
            p = resolve_principal(j, websocket, token)
        except ApiError as exc:
            await websocket.close(code=4401, reason=exc.code)
            return
        await websocket.accept()
        sid, queue = j.bus.subscribe(admin=p.is_admin)
        await websocket.send_json({"type": "hello", "data": {"kind": p.kind, "device_id": p.device_id}})

        async def reader():
            while True:
                msg = await websocket.receive_text()
                if msg == "ping":
                    await websocket.send_text("pong")

        read_task = asyncio.create_task(reader())
        try:
            while True:
                get = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait({get, read_task}, timeout=25, return_when=asyncio.FIRST_COMPLETED)
                if read_task in done:
                    get.cancel()
                    break
                if get not in done:
                    get.cancel()
                    # Widerruf wirkt auch auf offene Verbindungen
                    if not p.is_admin:
                        try:
                            j.tokens.verify_access(token or "")
                        except AuthError:
                            await websocket.close(code=4401, reason="revoked")
                            break
                    await websocket.send_json({"type": "keepalive", "ts": time.time()})
                    continue
                ev = get.result()
                if not p.is_admin:
                    if ev["type"] == "device.revoked" and ev["data"].get("device_id") == p.device_id:
                        await websocket.close(code=4401, reason="revoked")
                        break
                    if ev["type"].startswith("job") and (ev["data"] or {}).get("device_id") not in (None, p.device_id):
                        continue
                    if ev["type"].startswith("approval") and ev["data"].get("requested_by") not in (None, p.actor):
                        continue
                await websocket.send_json(json.loads(json.dumps(ev, default=str)))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            read_task.cancel()
            j.bus.unsubscribe(sid)

    # ------------------------------------------------------------------ Weboberfläche (PWA)
    if WEB_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

        @app.get("/manifest.webmanifest", include_in_schema=False)
        def manifest():
            return FileResponse(WEB_DIR / "manifest.webmanifest", media_type="application/manifest+json")

        @app.get("/sw.js", include_in_schema=False)
        def sw():
            return FileResponse(WEB_DIR / "sw.js", media_type="application/javascript",
                                headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})

    return app
