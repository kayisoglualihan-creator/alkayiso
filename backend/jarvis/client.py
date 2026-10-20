"""Kleiner Python-Client für die JARVIS-API (für Skripte, Tests und als Kommandozeilen-Fernbedienung).

Beispiel:
    python -m jarvis.client --url https://mein-pc.tailnet.ts.net --creds geraet.json status
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx


class PCOffline(Exception):
    """Der PC (bzw. das Jarvis-Backend) ist nicht erreichbar."""


class JarvisClient:
    def __init__(self, base_url: str, *, admin_token: str | None = None, device: dict | None = None,
                 timeout: float = 15):
        self.base_url = base_url.rstrip("/")
        self.admin_token = admin_token
        self.device = device  # {"device_id", "refresh_token", "access_token", "expires_at"}
        self.http = httpx.Client(timeout=timeout)

    def _token(self) -> str:
        if self.admin_token:
            return self.admin_token
        if not self.device:
            raise RuntimeError("Nicht gekoppelt")
        if not self.device.get("access_token") or self.device.get("expires_at", 0) - 30 < time.time():
            self.refresh()
        return self.device["access_token"]

    def _req(self, method: str, path: str, **kw) -> dict:
        try:
            r = self.http.request(method, self.base_url + path, **kw)
        except httpx.TransportError as exc:
            raise PCOffline(f"PC offline: {exc}") from exc
        if r.status_code >= 400:
            try:
                err = r.json()["error"]
            except Exception:
                err = {"code": "http_" + str(r.status_code), "message": r.text[:200]}
            raise RuntimeError(f"{err['code']}: {err['message']}")
        return r.json()

    def _auth(self, method: str, path: str, **kw) -> dict:
        return self._req(method, path, headers={"Authorization": f"Bearer {self._token()}"}, **kw)

    # -- Öffentlich ----------------------------------------------------------
    def health(self) -> dict:
        return self._req("GET", "/api/health")

    def is_online(self) -> bool:
        try:
            self.health()
            return True
        except PCOffline:
            return False

    def refresh(self) -> None:
        out = self._req("POST", "/api/auth/refresh", json={"device_id": self.device["device_id"],
                                                          "refresh_token": self.device["refresh_token"]})
        self.device.update(access_token=out["access_token"], expires_at=out["expires_at"],
                           refresh_token=out["refresh_token"])

    def pair(self, pairing_id: str, code: str, name: str = "CLI", wait: float = 120) -> dict:
        claim = self._req("POST", "/api/pairing/claim", json={"pairing_id": pairing_id, "code": code,
                                                              "device_name": name, "platform": "cli"})
        print(f"Prüfnummer: {claim['verify_code']} – bitte am PC bestätigen …", file=sys.stderr)
        end = time.time() + wait
        while time.time() < end:
            out = self._req("POST", "/api/pairing/poll", json={"pairing_id": pairing_id,
                                                               "claim_secret": claim["claim_secret"]})
            if out["status"] == "completed":
                self.device = {k: out[k] for k in ("device_id", "refresh_token", "access_token", "expires_at")}
                return self.device
            if out["status"] in ("rejected", "expired", "cancelled"):
                raise RuntimeError(f"Kopplung {out['status']}")
            time.sleep(1.5)
        raise TimeoutError("Kopplung nicht bestätigt")

    def status(self) -> dict:
        return self._auth("GET", "/api/status")

    def chat(self, message: str) -> dict:
        return self._auth("POST", "/api/chat", json={"message": message}, timeout=300)

    def submit(self, text: str) -> dict:
        return self._auth("POST", "/api/jobs", json={"text": text})

    def job(self, job_id: str, wait: float = 0) -> dict:
        return self._auth("GET", f"/api/jobs/{job_id}", params={"wait": wait}, timeout=wait + 15)

    def run(self, text: str, timeout: float = 120) -> dict:
        """Fernauftrag senden und auf Ergebnis warten. Wirft PCOffline, wenn der PC nicht erreichbar ist."""
        job = self.submit(text)
        end = time.time() + timeout
        while job["status"] not in ("succeeded", "failed", "cancelled") and time.time() < end:
            job = self.job(job["id"], wait=min(20, max(1, end - time.time())))
        return job

    def tasks(self) -> list:
        return self._auth("GET", "/api/tasks")

    def add_task(self, title: str, due: str | None = None) -> dict:
        return self._auth("POST", "/api/tasks", json={"title": title, "due": due})


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="jarvis.client")
    p.add_argument("--url", required=True)
    p.add_argument("--creds", default="jarvis_device.json", help="Datei mit Gerätezugang (nach 'pair')")
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("pair")
    pp.add_argument("link", help="Kopplungslink aus dem QR-Code (…#pair=…)")
    sub.add_parser("status")
    rp = sub.add_parser("run")
    rp.add_argument("text")
    args = p.parse_args(argv)
    creds = Path(args.creds)
    device = json.loads(creds.read_text()) if creds.exists() else None
    c = JarvisClient(args.url, device=device)
    try:
        if args.cmd == "pair":
            import base64
            enc = args.link.split("#pair=", 1)[1]
            payload = json.loads(base64.urlsafe_b64decode(enc + "=" * (-len(enc) % 4)))
            c.pair(payload["pid"], payload["code"])
            print("Gekoppelt.")
        elif args.cmd == "status":
            print(json.dumps(c.status(), indent=2, ensure_ascii=False))
        elif args.cmd == "run":
            job = c.run(args.text)
            print(f"[{job['status']}] {(job.get('result') or {}).get('text') or job.get('error')}")
    except PCOffline as exc:
        print(f"PC offline – {exc}", file=sys.stderr)
        return 2
    finally:
        if c.device:
            creds.write_text(json.dumps(c.device))
    return 0


if __name__ == "__main__":
    sys.exit(main())
