"""OAuth-Anmeldung (PKCE, Loopback) und E-Mail/Kalender-Werkzeuge gegen simulierte Google-/Microsoft-APIs."""
import asyncio
import base64
import datetime as dt
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx

from jarvis.security.permissions import LEVEL_CRITICAL
from jarvis.tools.registry import ToolContext

SENT = []


def fake_api(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "oauth2.googleapis.com/token" in url or "login.microsoftonline.com" in url:
        form = parse_qs(request.content.decode())
        assert "code_verifier" in form or form["grant_type"] == ["refresh_token"]
        return httpx.Response(200, json={"access_token": "AT-" + form["grant_type"][0], "refresh_token": "RT",
                                         "expires_in": 3600})
    if "userinfo" in url:
        return httpx.Response(200, json={"email": "ich@gmail.com"})
    if url.endswith("/graph.microsoft.com/v1.0/me"):
        return httpx.Response(200, json={"mail": "ich@outlook.de"})
    if "gmail/v1/users/me/messages/send" in url:
        SENT.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "s1"})
    if "gmail/v1/users/me/drafts" in url:
        return httpx.Response(200, json={"id": "d1"})
    if "gmail/v1/users/me/messages/m1" in url:
        if request.url.params.get("format") == "full":
            body = base64.urlsafe_b64encode("Hallo, bitte Rechnung prüfen.".encode()).decode()
            return httpx.Response(200, json={"payload": {"mimeType": "text/plain", "body": {"data": body},
                                                         "headers": [{"name": "From", "value": "chef@firma.de"}]}})
        return httpx.Response(200, json={"snippet": "Bitte Rechnung prüfen", "labelIds": ["UNREAD"], "payload": {
            "headers": [{"name": "From", "value": "chef@firma.de"}, {"name": "Subject", "value": "Rechnung"}]}})
    if "gmail/v1/users/me/messages" in url:
        return httpx.Response(200, json={"messages": [{"id": "m1"}]})
    if "calendar/v3/calendars/primary/events" in url:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "e1"})
        start = (dt.datetime.now() + dt.timedelta(hours=1)).astimezone()
        return httpx.Response(200, json={"items": [{"summary": "Kundentermin", "start": {"dateTime": start.isoformat()},
                                                    "end": {"dateTime": (start + dt.timedelta(hours=1)).isoformat()}}]})
    return httpx.Response(404, json={"error": "unbekannt " + url})


def connect(client, provider="google"):
    j = client.jarvis
    j.oauth.transport = httpx.MockTransport(fake_api)
    client.patch("/api/settings", json={f"{provider}_client_id": "cid-123"}, headers=client.admin)
    r = client.post(f"/api/integrations/{provider}/connect", headers=client.admin)
    assert r.status_code == 200
    q = parse_qs(urlparse(r.json()["url"]).query)
    assert q["code_challenge_method"] == ["S256"] and q["client_id"] == ["cid-123"]
    assert q["redirect_uri"][0].startswith("http://127.0.0.1:" if provider == "google" else "http://localhost:")
    cb = client.get(f"/oauth/callback?state={q['state'][0]}&code=abc")
    assert cb.status_code == 200 and "verbunden" in cb.text
    return q["state"][0]


def test_connect_requires_client_id(client):
    r = client.post("/api/integrations/google/connect", headers=client.admin)
    assert r.status_code == 400 and r.json()["error"]["code"] == "oauth_not_configured"


def test_oauth_flow_and_state_single_use(client):
    state = connect(client)
    st = client.get("/api/integrations", headers=client.admin).json()["accounts"]["google"]
    assert st["connected"] and st["account"] == "ich@gmail.com"
    # gleicher state nochmals -> abgelehnt
    assert client.get(f"/oauth/callback?state={state}&code=abc").status_code == 400
    # Rückleitung über Proxy (nicht lokal) -> abgelehnt
    assert client.get("/oauth/callback?state=x&code=y", headers={"X-Forwarded-For": "1.2.3.4"}).status_code == 403


def test_token_refresh(client):
    connect(client)
    j = client.jarvis
    tok = json.loads(j.secrets.get("google_oauth"))
    tok["expires_at"] = time.time() - 10
    j.secrets.set("google_oauth", json.dumps(tok))
    assert asyncio.run(j.oauth.access_token("google")) == "AT-refresh_token"


def test_email_tools(client):
    connect(client)
    ctx = ToolContext(app=client.jarvis, source="desktop")
    reg = client.jarvis.registry
    r = asyncio.run(reg.get("email_list").run(ctx, {}))
    assert r.ok and r.untrusted and "chef@firma.de: Rechnung" in r.content
    r = asyncio.run(reg.get("email_read").run(ctx, {"message_id": "m1"}))
    assert "Rechnung prüfen" in r.content and r.untrusted
    r = asyncio.run(reg.get("email_draft").run(ctx, {"to": "a@b.de", "subject": "Hi", "body": "Test"}))
    assert r.ok and "NICHT gesendet" in r.content
    assert reg.get("email_send").risk == LEVEL_CRITICAL and reg.get("email_draft").risk == 2
    r = asyncio.run(reg.get("email_send").run(ctx, {"to": "a@b.de", "subject": "Hi", "body": "Test"}))
    assert r.ok and base64.urlsafe_b64decode(SENT[-1]["raw"]).decode().count("To: a@b.de") == 1


def test_email_send_needs_confirmation_via_agent(client):
    from conftest import wait_job

    from jarvis.ai.providers import LLMResponse, Provider, ToolCall

    class P(Provider):
        name = "scripted"

        def __init__(self):
            super().__init__("m")
            self.done = False

        async def complete(self, system, messages, tools, on_text=None):
            if messages[-1]["role"] == "tool":
                return LLMResponse(messages[-1]["content"])
            return LLMResponse("", [ToolCall("c", "email_send", {"to": "x@y.de", "subject": "S", "body": "B"})])

    connect(client)
    SENT.clear()
    client.jarvis.set_provider_override(P())
    job = client.post("/api/jobs", json={"text": "schick mail"}, headers=client.admin).json()
    wait_job(client, job["id"], client.admin, statuses=("approval_required",))
    a = client.get("/api/approvals", headers=client.admin).json()[0]
    assert a["requires_confirm_text"] and "E-MAIL SENDEN" in a["summary"]
    assert SENT == []
    client.post(f"/api/approvals/{a['id']}", json={"approve": False}, headers=client.admin)
    wait_job(client, job["id"], client.admin)
    assert SENT == []


def test_google_calendar_in_briefing_and_create(client):
    connect(client)
    b = client.get("/api/briefing", headers=client.admin).json()
    assert "Kundentermin" in b["text"]
    ctx = ToolContext(app=client.jarvis, source="desktop")
    r = asyncio.run(client.jarvis.registry.get("calendar_create").run(ctx, {"title": "Zahnarzt", "start": "morgen 10 uhr"}))
    assert r.ok and "Zahnarzt" in r.content


def test_not_connected_message(client):
    ctx = ToolContext(app=client.jarvis, source="desktop")
    r = asyncio.run(client.jarvis.registry.get("email_list").run(ctx, {}))
    assert not r.ok and "Kein E-Mail" in r.content
