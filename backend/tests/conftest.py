import os
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["JARVIS_DISABLE_KEYRING"] = "1"

from jarvis.api.app import create_app  # noqa: E402
from jarvis.config import load_settings  # noqa: E402


def make_settings(tmp: Path):
    s = load_settings(tmp / "data")
    s.enable_scheduler = False
    s.approval_ttl = 5
    docs = tmp / "docs"
    docs.mkdir(exist_ok=True)
    s.allowed_roots = [docs, s.output_dir]
    return s


@pytest.fixture
def settings(tmp_path):
    return make_settings(tmp_path)


@pytest.fixture
def client(settings):
    app = create_app(settings, dry_run=True)
    with TestClient(app) as c:
        c.jarvis = app.state.jarvis
        c.admin = {"Authorization": f"Bearer {app.state.jarvis.admin_token}"}
        yield c


def pair_device(client, name="Test-iPhone"):
    """Führt den vollständigen Kopplungsablauf durch und gibt (device_id, auth_header, refresh) zurück."""
    start = client.post("/api/pairing/start", headers=client.admin).json()
    claim = client.post("/api/pairing/claim", json={"pairing_id": start["pairing_id"], "code": start["code"],
                                                    "device_name": name, "platform": "ios"}).json()
    client.post(f"/api/pairing/{start['pairing_id']}/decision", json={"approve": True}, headers=client.admin)
    done = client.post("/api/pairing/poll", json={"pairing_id": start["pairing_id"],
                                                  "claim_secret": claim["claim_secret"]}).json()
    assert done["status"] == "completed"
    return done["device_id"], {"Authorization": f"Bearer {done['access_token']}"}, done["refresh_token"]


def wait_job(client, job_id, headers, statuses=("succeeded", "failed", "cancelled"), timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/jobs/{job_id}", headers=headers).json()
        if job["status"] in statuses:
            return job
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} blieb bei {job['status']}")
