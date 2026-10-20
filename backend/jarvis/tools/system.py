"""Systeminformationen, Programme und Fenster (Windows-spezifisch mit Fallbacks)."""
from __future__ import annotations

import datetime as dt
import os
import platform
import shutil
import subprocess
import sys
import time

import psutil

from ..security.permissions import LEVEL_CHANGE, LEVEL_CRITICAL, LEVEL_READ
from .registry import ToolContext, ToolRegistry, ToolResult, params

IS_WINDOWS = sys.platform == "win32"

# Freigegebene Programme: Alias -> Kandidaten (Befehl bzw. Pfade). Erweiterbar über Einstellung "app_aliases".
DEFAULT_APPS: dict[str, list[str]] = {
    "vscode": ["code", r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"],
    "visual studio code": ["code", r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"],
    "notepad": ["notepad.exe", "gedit", "mousepad"],
    "editor": ["notepad.exe", "gedit", "mousepad"],
    "rechner": ["calc.exe", "gnome-calculator"],
    "calculator": ["calc.exe", "gnome-calculator"],
    "explorer": ["explorer.exe", "nautilus", "xdg-open ."],
    "chrome": ["chrome", r"%ProgramFiles%\Google\Chrome\Application\chrome.exe", "google-chrome", "chromium"],
    "edge": ["msedge", r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"],
    "firefox": ["firefox", r"%ProgramFiles%\Mozilla Firefox\firefox.exe"],
    "terminal": ["wt.exe", "gnome-terminal", "xterm"],
    "word": ["winword", r"%ProgramFiles%\Microsoft Office\root\Office16\WINWORD.EXE"],
    "excel": ["excel", r"%ProgramFiles%\Microsoft Office\root\Office16\EXCEL.EXE"],
    "outlook": ["outlook", r"%ProgramFiles%\Microsoft Office\root\Office16\OUTLOOK.EXE"],
    "spotify": ["spotify", r"%APPDATA%\Spotify\Spotify.exe"],
    "discord": [r"%LOCALAPPDATA%\Discord\Update.exe --processStart Discord.exe", "discord"],
    "taskmanager": ["taskmgr.exe"],
    "einstellungen": ["ms-settings:"],
    "settings": ["ms-settings:"],
}

# Prozesse, die Jarvis niemals beendet
PROTECTED_PROCESSES = {"system", "csrss.exe", "wininit.exe", "winlogon.exe", "lsass.exe", "services.exe",
                       "smss.exe", "svchost.exe", "explorer.exe", "dwm.exe", "systemd", "init", "python.exe",
                       "python", "jarvis.exe", "tailscaled.exe", "tailscale-ipn.exe"}


def system_snapshot() -> dict:
    vm = psutil.virtual_memory()
    disks = []
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.fstype or part.fstype.startswith("fuse") \
                or part.fstype in {"squashfs", "tmpfs", "overlay", "devtmpfs"}:
            continue
        try:
            u = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        if u.total < 1e9:
            continue
        disks.append({"mount": part.mountpoint, "total_gb": round(u.total / 1e9, 1),
                      "free_gb": round(u.free / 1e9, 1), "percent": u.percent})
    battery = None
    try:
        b = psutil.sensors_battery()
        if b:
            battery = {"percent": b.percent, "plugged": b.power_plugged}
    except Exception:
        pass
    net = psutil.net_io_counters()
    return {
        "hostname": platform.node(), "os": f"{platform.system()} {platform.release()}",
        "cpu_percent": psutil.cpu_percent(interval=0.3), "cpu_count": psutil.cpu_count(),
        "ram_percent": vm.percent, "ram_used_gb": round(vm.used / 1e9, 1), "ram_total_gb": round(vm.total / 1e9, 1),
        "disks": disks, "battery": battery, "uptime_h": round((time.time() - psutil.boot_time()) / 3600, 1),
        "net_sent_mb": round(net.bytes_sent / 1e6, 1), "net_recv_mb": round(net.bytes_recv / 1e6, 1),
    }


def _resolve_app(name: str, aliases: dict[str, list[str]]) -> str | None:
    for cand in aliases.get(name.strip().lower(), []):
        expanded = os.path.expandvars(cand)
        exe = expanded.split(" --")[0]
        if cand.endswith(":") or os.path.isfile(exe) or shutil.which(exe.split()[0]):
            return expanded
    return None


def _launch(command: str) -> None:
    if IS_WINDOWS:
        if command.endswith(":"):
            os.startfile(command)  # type: ignore[attr-defined]
            return
        exe, _, rest = command.partition(" --")
        args = [exe] + (["--" + rest] if rest else [])
        resolved = shutil.which(exe) or exe
        subprocess.Popen([resolved] + args[1:], creationflags=0x00000008 | 0x00000200,  # DETACHED | NEW_GROUP
                         close_fds=True)
    else:
        subprocess.Popen(command.split(), start_new_session=True, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------------------
# Fenster (nur Windows, über ctypes / user32 – läuft in der angemeldeten Benutzersitzung)
# ---------------------------------------------------------------------------
def list_windows() -> list[dict]:
    if not IS_WINDOWS:
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    result: list[dict] = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                try:
                    pname = psutil.Process(pid.value).name()
                except Exception:
                    pname = "?"
                result.append({"hwnd": int(hwnd), "title": buf.value, "pid": pid.value, "process": pname})
        return True

    user32.EnumWindows(proto(cb), 0)
    return result


def focus_window(hwnd: int) -> bool:
    if not IS_WINDOWS:
        return False
    import ctypes
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    return bool(user32.SetForegroundWindow(hwnd))


def register(reg: ToolRegistry) -> None:
    @reg.tool("get_time", "Aktuelle Uhrzeit und Datum des PCs.", params(), LEVEL_READ)
    def get_time(ctx: ToolContext) -> ToolResult:
        now = dt.datetime.now()
        days = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
        return ToolResult(f"{days[now.weekday()]}, {now.strftime('%d.%m.%Y, %H:%M')} Uhr",
                          {"iso": now.isoformat()})

    @reg.tool("system_status", "CPU-, RAM-, Speicher-, Akku- und Laufzeitstatus des PCs abrufen.",
              params(), LEVEL_READ, module="system")
    def system_status(ctx: ToolContext) -> ToolResult:
        s = system_snapshot()
        disks = "; ".join(f"{d['mount']} {d['free_gb']} GB frei ({d['percent']}% belegt)" for d in s["disks"][:4])
        text = (f"CPU {s['cpu_percent']}% ({s['cpu_count']} Kerne), RAM {s['ram_percent']}% "
                f"({s['ram_used_gb']}/{s['ram_total_gb']} GB). Speicher: {disks}. Laufzeit {s['uptime_h']} h.")
        if s["battery"]:
            text += f" Akku {s['battery']['percent']}%."
        return ToolResult(text, s)

    @reg.tool("list_processes", "Laufende Prozesse nach CPU- oder RAM-Verbrauch auflisten.",
              params({"sort": {"type": "string", "enum": ["cpu", "memory"]},
                      "limit": {"type": "integer", "minimum": 1, "maximum": 50}}), LEVEL_READ, module="system")
    def list_processes(ctx: ToolContext, sort: str = "memory", limit: int = 10) -> ToolResult:
        procs = []
        for p in psutil.process_iter(["pid", "name", "memory_info", "cpu_percent"]):
            try:
                procs.append({"pid": p.info["pid"], "name": p.info["name"],
                              "memory_mb": round((p.info["memory_info"].rss if p.info["memory_info"] else 0) / 1e6, 1),
                              "cpu": p.info["cpu_percent"] or 0.0})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        key = "cpu" if sort == "cpu" else "memory_mb"
        procs.sort(key=lambda x: x[key], reverse=True)
        top = procs[:limit]
        return ToolResult("\n".join(f"{p['name']} (PID {p['pid']}): {p['memory_mb']} MB, CPU {p['cpu']}%" for p in top),
                          top)

    @reg.tool("open_app", "Ein freigegebenes Programm auf dem PC starten (z. B. vscode, chrome, notepad, excel). "
              "Nur Programme aus der Freigabeliste.",
              params({"name": {"type": "string", "description": "Programmname/Alias"}}, ["name"]), LEVEL_READ,
              module="apps", summarize=lambda a: f"Programm starten: {a.get('name')}")
    def open_app(ctx: ToolContext, name: str) -> ToolResult:
        aliases = {**DEFAULT_APPS, **(ctx.app.db.get_setting("app_aliases", {}) or {})}
        cmd = _resolve_app(name, aliases)
        if not cmd:
            known = ", ".join(sorted(aliases))
            return ToolResult(f"'{name}' ist nicht freigegeben oder nicht installiert. Freigegeben: {known}", ok=False)
        if ctx.app.dry_run:
            return ToolResult(f"[Testmodus] Würde starten: {cmd}", {"command": cmd})
        _launch(cmd)
        return ToolResult(f"{name} wurde gestartet.", {"command": cmd})

    @reg.tool("list_apps", "Liste der freigegebenen Programme, die Jarvis starten darf.", params(), LEVEL_READ,
              module="apps")
    def list_apps(ctx: ToolContext) -> ToolResult:
        aliases = {**DEFAULT_APPS, **(ctx.app.db.get_setting("app_aliases", {}) or {})}
        avail = [a for a in sorted(aliases) if _resolve_app(a, aliases)]
        return ToolResult("Verfügbar: " + (", ".join(avail) or "keine gefunden"), avail)

    @reg.tool("list_windows", "Geöffnete Fenster auflisten (Windows).", params(), LEVEL_READ, module="apps")
    def list_windows_tool(ctx: ToolContext) -> ToolResult:
        if not IS_WINDOWS:
            return ToolResult("Fensterliste ist nur unter Windows verfügbar.", [], ok=False)
        wins = list_windows()
        return ToolResult("\n".join(f"[{w['hwnd']}] {w['title']} ({w['process']})" for w in wins[:40]), wins)

    @reg.tool("focus_window", "Zu einem geöffneten Fenster wechseln (Titel-Teilstring).",
              params({"title": {"type": "string"}}, ["title"]), LEVEL_READ, module="apps")
    def focus_window_tool(ctx: ToolContext, title: str) -> ToolResult:
        if not IS_WINDOWS:
            return ToolResult("Fensterwechsel ist nur unter Windows verfügbar.", ok=False)
        for w in list_windows():
            if title.lower() in w["title"].lower():
                focus_window(w["hwnd"])
                return ToolResult(f"Gewechselt zu: {w['title']}", w)
        return ToolResult(f"Kein Fenster mit '{title}' gefunden.", ok=False)

    @reg.tool("close_app", "Ein laufendes Programm kontrolliert beenden (nach Prozessname). Systemprozesse sind geschützt.",
              params({"process_name": {"type": "string"}}, ["process_name"]), LEVEL_CHANGE, module="apps",
              summarize=lambda a: f"Programm beenden: {a.get('process_name')}")
    def close_app(ctx: ToolContext, process_name: str) -> ToolResult:
        target = process_name.lower()
        if not target.endswith(".exe") and IS_WINDOWS:
            target_names = {target, target + ".exe"}
        else:
            target_names = {target}
        if target_names & PROTECTED_PROCESSES:
            return ToolResult("Dieser Prozess ist geschützt und wird nicht beendet.", ok=False)
        closed = []
        for p in psutil.process_iter(["pid", "name"]):
            if (p.info["name"] or "").lower() in target_names and p.pid != os.getpid():
                try:
                    p.terminate()  # sanftes Beenden, kein kill
                    closed.append(p.pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        if not closed:
            return ToolResult(f"Kein laufender Prozess '{process_name}' gefunden.", ok=False)
        return ToolResult(f"{process_name} beendet ({len(closed)} Prozess(e)).", {"pids": closed})

    @reg.tool("lock_screen", "Den PC sperren (Windows).", params(), LEVEL_CHANGE, module="system",
              summarize=lambda a: "PC sperren")
    def lock_screen(ctx: ToolContext) -> ToolResult:
        if not IS_WINDOWS:
            return ToolResult("Nur unter Windows verfügbar.", ok=False)
        import ctypes
        ctypes.windll.user32.LockWorkStation()  # type: ignore[attr-defined]
        return ToolResult("PC wurde gesperrt.")

    @reg.tool("shutdown_pc", "PC herunterfahren oder neu starten (kritisch).",
              params({"action": {"type": "string", "enum": ["shutdown", "restart"]}}, ["action"]), LEVEL_CRITICAL,
              module="system", summarize=lambda a: f"PC {'neu starten' if a.get('action') == 'restart' else 'herunterfahren'}")
    def shutdown_pc(ctx: ToolContext, action: str) -> ToolResult:
        if not IS_WINDOWS:
            return ToolResult("Nur unter Windows verfügbar.", ok=False)
        if ctx.app.dry_run:
            return ToolResult(f"[Testmodus] {action}")
        flag = "/r" if action == "restart" else "/s"
        subprocess.Popen(["shutdown", flag, "/t", "60", "/c", "JARVIS: Ausgelöst per Befehl"])
        return ToolResult(f"{'Neustart' if action == 'restart' else 'Herunterfahren'} in 60 Sekunden "
                          f"(abbrechen mit 'shutdown /a').")

    @reg.tool("take_screenshot", "Einen Screenshot des Bildschirms erstellen und speichern (nur auf ausdrücklichen Wunsch).",
              params(), LEVEL_CHANGE, module="screen", summarize=lambda a: "Screenshot erstellen")
    def take_screenshot(ctx: ToolContext) -> ToolResult:
        try:
            from PIL import ImageGrab
        except ImportError:
            return ToolResult("Pillow ist nicht installiert.", ok=False)
        try:
            img = ImageGrab.grab()
        except Exception as exc:
            return ToolResult(f"Screenshot nicht möglich: {exc}", ok=False)
        path = ctx.app.settings.output_dir / f"screenshot_{dt.datetime.now():%Y%m%d_%H%M%S}.png"
        img.save(path)
        return ToolResult(f"Screenshot gespeichert: {path}", {"path": str(path)})

    @reg.tool("type_text", "Text in das aktive Fenster tippen (Tastatur-Automatisierung).",
              params({"text": {"type": "string"}}, ["text"]), LEVEL_CHANGE, module="screen",
              summarize=lambda a: f"Text tippen: {str(a.get('text'))[:60]}",
              available=lambda: IS_WINDOWS)
    def type_text(ctx: ToolContext, text: str) -> ToolResult:
        try:
            import pyautogui  # type: ignore
        except ImportError:
            return ToolResult("pyautogui ist nicht installiert (optionale Abhängigkeit).", ok=False)
        pyautogui.write(text, interval=0.01)
        return ToolResult("Text eingegeben.")
