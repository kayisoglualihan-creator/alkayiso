import time

from conftest import pair_device


def test_health_is_public(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_status_requires_auth(client):
    r = client.get("/api/status")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "auth_required"


def test_admin_token_works_locally(client):
    r = client.get("/api/status", headers=client.admin)
    assert r.status_code == 200
    assert r.json()["principal"]["kind"] == "admin"


def test_admin_token_rejected_through_proxy(client):
    # Über Tailscale Serve weitergeleitete Anfragen dürfen das lokale Admin-Token nicht verwenden
    for header in ({"Tailscale-User-Login": "me@example.com"}, {"X-Forwarded-For": "100.64.0.5"}):
        r = client.get("/api/status", headers={**client.admin, **header})
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "admin_local_only"


def test_pairing_full_flow_and_device_access(client):
    device_id, auth, _ = pair_device(client)
    me = client.get("/api/auth/me", headers=auth).json()
    assert me == {"kind": "device", "device_id": device_id, "name": "Test-iPhone"}
    # Geräte dürfen keine Admin-Endpunkte nutzen
    assert client.get("/api/settings", headers=auth).status_code == 403
    assert client.post("/api/pairing/start", headers=auth).status_code == 403


def test_pairing_code_single_use(client):
    start = client.post("/api/pairing/start", headers=client.admin).json()
    body = {"pairing_id": start["pairing_id"], "code": start["code"], "device_name": "A"}
    assert client.post("/api/pairing/claim", json=body).status_code == 200
    r = client.post("/api/pairing/claim", json=body)
    assert r.status_code == 400 and r.json()["error"]["code"] == "pairing_closed"


def test_pairing_wrong_code_locks_after_attempts(client):
    start = client.post("/api/pairing/start", headers=client.admin).json()
    for _ in range(5):
        r = client.post("/api/pairing/claim", json={"pairing_id": start["pairing_id"], "code": "falsch"})
        assert r.json()["error"]["code"] == "pairing_code_invalid"
    r = client.post("/api/pairing/claim", json={"pairing_id": start["pairing_id"], "code": start["code"]})
    assert r.json()["error"]["code"] == "pairing_closed"


def test_pairing_rejected_gives_no_token(client):
    start = client.post("/api/pairing/start", headers=client.admin).json()
    claim = client.post("/api/pairing/claim", json={"pairing_id": start["pairing_id"], "code": start["code"]}).json()
    poll = {"pairing_id": start["pairing_id"], "claim_secret": claim["claim_secret"]}
    assert client.post("/api/pairing/poll", json=poll).json()["status"] == "awaiting_approval"
    client.post(f"/api/pairing/{start['pairing_id']}/decision", json={"approve": False}, headers=client.admin)
    out = client.post("/api/pairing/poll", json=poll).json()
    assert out["status"] == "rejected" and "refresh_token" not in out


def test_pairing_token_issued_only_once(client):
    start = client.post("/api/pairing/start", headers=client.admin).json()
    claim = client.post("/api/pairing/claim", json={"pairing_id": start["pairing_id"], "code": start["code"]}).json()
    client.post(f"/api/pairing/{start['pairing_id']}/decision", json={"approve": True}, headers=client.admin)
    poll = {"pairing_id": start["pairing_id"], "claim_secret": claim["claim_secret"]}
    assert client.post("/api/pairing/poll", json=poll).json()["status"] == "completed"
    second = client.post("/api/pairing/poll", json=poll).json()
    assert "refresh_token" not in second


def test_pairing_expires(client):
    start = client.post("/api/pairing/start", headers=client.admin).json()
    client.jarvis.db.execute("UPDATE pairings SET expires_at = ? WHERE id = ?", (time.time() - 1, start["pairing_id"]))
    r = client.post("/api/pairing/claim", json={"pairing_id": start["pairing_id"], "code": start["code"]})
    assert r.json()["error"]["code"] == "pairing_closed"


def test_pairing_requires_tailscale_when_proxied(client):
    start = client.post("/api/pairing/start", headers=client.admin).json()
    body = {"pairing_id": start["pairing_id"], "code": start["code"]}
    r = client.post("/api/pairing/claim", json=body, headers={"X-Forwarded-For": "203.0.113.9"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "tailscale_required"
    r = client.post("/api/pairing/claim", json=body,
                    headers={"X-Forwarded-For": "100.64.0.9", "Tailscale-User-Login": "me@example.com"})
    assert r.status_code == 200


def test_qr_contains_link(client):
    start = client.post("/api/pairing/start", headers=client.admin).json()
    assert start["qr_svg"].startswith("<svg") or "<svg" in start["qr_svg"]
    assert "#pair=" in start["link"]


def test_expired_access_token_rejected(client):
    device_id, auth, _ = pair_device(client)
    device = client.jarvis.db.one("SELECT * FROM devices WHERE id = ?", (device_id,))
    tokens = client.jarvis.tokens
    old_ttl = tokens.access_ttl
    tokens.access_ttl = -10
    expired, _ = tokens.issue_access(device)
    tokens.access_ttl = old_ttl
    r = client.get("/api/status", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "token_expired"


def test_tampered_token_rejected(client):
    _, auth, _ = pair_device(client)
    tok = auth["Authorization"][7:]
    head, body, sig = tok.split(".")
    bad = f"{head}.{body}.{'A' * len(sig)}"
    r = client.get("/api/status", headers={"Authorization": f"Bearer {bad}"})
    assert r.json()["error"]["code"] == "token_invalid"


def test_refresh_rotates_and_detects_reuse(client):
    device_id, _, refresh = pair_device(client)
    r1 = client.post("/api/auth/refresh", json={"device_id": device_id, "refresh_token": refresh})
    assert r1.status_code == 200
    new = r1.json()
    assert new["refresh_token"] != refresh
    # Wiederverwendung des alten Tokens -> abgelehnt UND alle Tokens des Geräts ungültig
    r2 = client.post("/api/auth/refresh", json={"device_id": device_id, "refresh_token": refresh})
    assert r2.status_code == 401 and r2.json()["error"]["code"] == "refresh_invalid"
    r3 = client.get("/api/status", headers={"Authorization": f"Bearer {new['access_token']}"})
    assert r3.status_code == 401


def test_revoked_device_loses_access_immediately(client):
    device_id, auth, refresh = pair_device(client)
    assert client.get("/api/status", headers=auth).status_code == 200
    assert client.delete(f"/api/devices/{device_id}", headers=client.admin).status_code == 200
    r = client.get("/api/status", headers=auth)
    assert r.status_code == 401 and r.json()["error"]["code"] == "device_revoked"
    r = client.post("/api/auth/refresh", json={"device_id": device_id, "refresh_token": refresh})
    assert r.status_code == 401


def test_remote_access_switch(client):
    _, auth, _ = pair_device(client)
    client.post("/api/remote-access", json={"enabled": False}, headers=client.admin)
    r = client.get("/api/status", headers=auth)
    assert r.status_code == 401 and r.json()["error"]["code"] == "remote_disabled"
    client.post("/api/remote-access", json={"enabled": True}, headers=client.admin)
    assert client.get("/api/status", headers=auth).status_code == 200


def test_websocket_auth(client):
    import pytest
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws?token=falsch") as ws:
        ws.receive_json()
    with client.websocket_connect(f"/ws?token={client.jarvis.admin_token}") as ws:
        assert ws.receive_json()["type"] == "hello"
        client.post("/api/tasks", json={"title": "WS-Test"}, headers=client.admin)
        ev = ws.receive_json()
        assert ev["type"] == "task.changed" and ev["data"]["title"] == "WS-Test"
