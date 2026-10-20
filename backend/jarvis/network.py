"""Tailscale-Statusprüfung (nur lesend). Konfiguration von Tailscale Serve erfolgt bewusst
über das Skript ``scripts/tailscale_serve.ps1`` bzw. manuell – nicht automatisch durch die KI."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys


def _tailscale_bin() -> str | None:
    exe = shutil.which("tailscale")
    if exe:
        return exe
    if sys.platform == "win32":
        for cand in (r"C:\Program Files\Tailscale\tailscale.exe", r"C:\Program Files (x86)\Tailscale\tailscale.exe"):
            if shutil.os.path.exists(cand):
                return cand
    return None


def tailscale_status() -> dict:
    exe = _tailscale_bin()
    if not exe:
        return {"installed": False, "running": False,
                "hint": "Tailscale ist nicht installiert. Download: https://tailscale.com/download/windows"}
    try:
        out = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"installed": True, "running": False, "hint": f"tailscale nicht ausführbar: {exc}"}
    if out.returncode != 0:
        return {"installed": True, "running": False, "hint": (out.stderr or out.stdout).strip()[:300]}
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        return {"installed": True, "running": False, "hint": "Unerwartete Ausgabe von tailscale status"}
    self_node = data.get("Self") or {}
    dns = (self_node.get("DNSName") or "").rstrip(".")
    peers = [{"name": p.get("HostName"), "os": p.get("OS"), "online": p.get("Online"),
              "dns": (p.get("DNSName") or "").rstrip(".")}
             for p in (data.get("Peer") or {}).values()]
    serve = None
    try:
        s = subprocess.run([exe, "serve", "status", "--json"], capture_output=True, text=True, timeout=8)
        if s.returncode == 0 and s.stdout.strip():
            serve = json.loads(s.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        serve = None
    funnel_on = bool(serve and serve.get("AllowFunnel"))
    return {
        "installed": True, "running": data.get("BackendState") == "Running",
        "backend_state": data.get("BackendState"), "dns_name": dns,
        "https_url": f"https://{dns}" if dns else "", "tailnet": (data.get("CurrentTailnet") or {}).get("Name"),
        "ips": self_node.get("TailscaleIPs", []), "peers": peers,
        "serve_configured": bool(serve and (serve.get("TCP") or serve.get("Web"))),
        "funnel_enabled": funnel_on,
        "warning": "Tailscale Funnel ist aktiv – Jarvis wäre öffentlich erreichbar! Bitte deaktivieren." if funnel_on else None,
    }
