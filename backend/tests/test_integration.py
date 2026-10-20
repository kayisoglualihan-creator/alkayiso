"""Integrationstests mit echtem Serverprozess (uvicorn) und dem Python-Client.

Deckt ab: App startet, Texteingabe, Aufgabe speichern, Aufgabe nach Neustart vorhanden,
authentifizierter Client ruft PC-Status ab, harmloser Fernbefehl, nicht autorisierter Befehl
blockiert, widerrufenes Gerät verliert sofort Zugriff, nicht erreichbarer PC wird als offline erkannt.
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from jarvis.client import JarvisClient, PCOffline

BACKEND = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.integration


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Server:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.port = free_port()
        self.proc = None

    def start(self):
        env = {**os.environ, "JARVIS_DATA_DIR": str(self.data_dir), "JARVIS_DISABLE_KEYRING": "1",
               "JARVIS_ENABLE_SCHEDULER": "0", "JARVIS_ALLOWED_ROOTS": str(self.data_dir / "output")}
        self.proc = subprocess.Popen([sys.executable, "-m", "jarvis", "--port", str(self.port)], cwd=BACKEND, env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                if httpx.get(f"{self.url}/api/health", timeout=1).status_code == 200:
                    return self
            except httpx.TransportError:
                time.sleep(0.1)
        raise RuntimeError("Server startet nicht")

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    @property
    def admin(self):
        return (self.data_dir / "local_admin_token").read_text().strip()

    def stop(self):
        if self.proc:
            self.proc.terminate()
            self.proc.wait(10)
            self.proc = None


@pytest.fixture
def server(tmp_path):
    s = Server(tmp_path / "data").start()
    yield s
    s.stop()


def pair(server: Server) -> JarvisClient:
    admin = JarvisClient(server.url, admin_token=server.admin)
    start = admin._auth("POST", "/api/pairing/start")
    dev = JarvisClient(server.url)
    claim = dev._req("POST", "/api/pairing/claim", json={"pairing_id": start["pairing_id"], "code": start["code"],
                                                         "device_name": "Integration-iPhone"})
    admin._auth("POST", f"/api/pairing/{start['pairing_id']}/decision", json={"approve": True})
    out = dev._req("POST", "/api/pairing/poll", json={"pairing_id": start["pairing_id"], "claim_secret": claim["claim_secret"]})
    dev.device = {k: out[k] for k in ("device_id", "refresh_token", "access_token", "expires_at")}
    return dev


def test_full_system(server, tmp_path):
    admin = JarvisClient(server.url, admin_token=server.admin)
    # 1+2: App läuft und verarbeitet eine Texteingabe
    out = admin.chat("Jarvis, wie spät ist es?")
    assert out["actions"][0]["tool"] == "get_time" and "Uhr" in out["text"]
    # 4: Aufgabe speichern
    admin.add_task("Integrationstest-Aufgabe", "morgen 9 uhr")
    # 6: Authentifizierter Geräteclient ruft PC-Status ab
    phone = pair(server)
    st = phone.status()
    assert st["online"] and st["principal"]["kind"] == "device" and "cpu_percent" in st["system"]
    # 7: harmloser Fernbefehl
    job = phone.run("Wie hoch ist die CPU-Auslastung meines Computers?")
    assert job["status"] == "succeeded" and "CPU" in job["result"]["text"]
    # 8: nicht autorisierter Befehl wird blockiert (ohne Token und mit gefälschtem Token)
    r = httpx.post(f"{server.url}/api/jobs", json={"text": "Öffne notepad"})
    assert r.status_code == 401
    r = httpx.post(f"{server.url}/api/jobs", json={"text": "x"}, headers={"Authorization": "Bearer jv1.e30.AAAA"})
    assert r.status_code == 401
    # Admin-Token über Proxy-Header -> abgelehnt
    r = httpx.get(f"{server.url}/api/status", headers={"Authorization": f"Bearer {server.admin}",
                                                       "Tailscale-User-Login": "x@y"})
    assert r.status_code == 403
    # 9: Widerruf wirkt sofort
    admin._auth("DELETE", f"/api/devices/{phone.device['device_id']}")
    with pytest.raises(RuntimeError, match="device_revoked"):
        phone.status()
    # 5: Aufgabe nach Neustart vorhanden
    server.stop()
    server.start()
    admin2 = JarvisClient(server.url, admin_token=server.admin)
    assert any(t["title"] == "Integrationstest-Aufgabe" for t in admin2.tasks())


def test_offline_pc_detected(tmp_path):
    # 10: nicht erreichbarer PC -> eindeutige Offline-Meldung, keine angebliche Ausführung
    c = JarvisClient(f"http://127.0.0.1:{free_port()}", admin_token="x", timeout=2)
    assert c.is_online() is False
    with pytest.raises(PCOffline):
        c.run("Öffne VS Code")


def test_webui_served(server):
    r = httpx.get(server.url + "/")
    assert r.status_code == 200 and "J.A.R.V.I.S." in r.text
    assert httpx.get(server.url + "/static/app.js").status_code == 200
    assert httpx.get(server.url + "/manifest.webmanifest").json()["short_name"] == "JARVIS"
    assert httpx.get(server.url + "/sw.js").status_code == 200
