"""Windows-Agent: läuft in der ANGEMELDETEN Benutzersitzung (nicht als Windows-Dienst!).

Warum kein Dienst? Windows-Dienste laufen in Session 0 und haben keinen Zugriff auf den Desktop
des Benutzers (Session 0 Isolation). Fenster, Tastatur, Screenshots und Programmstarts müssen
daher in der interaktiven Sitzung laufen. Autostart erfolgt über HKCU\\...\\Run beim Login.

Funktionen:
* Autostart beim Windows-Login ein-/ausschalten (Registry, nur aktueller Benutzer)
* Symbol im Infobereich (pystray, optional) mit Menü: Öffnen, Fernzugriff an/aus, Beenden
* Öffnen der Desktop-Oberfläche als App-Fenster (Edge/Chrome --app) mit lokalem Admin-Token
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "JARVIS"
IS_WINDOWS = sys.platform == "win32"


def launch_command() -> str:
    if getattr(sys, "frozen", False):  # PyInstaller-Build
        return f'"{sys.executable}" --tray'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{exe}" -m jarvis --tray'


def autostart_enabled() -> bool:
    if not IS_WINDOWS:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
            return True
    except FileNotFoundError:
        return False


def set_autostart(enabled: bool) -> bool:
    if not IS_WINDOWS:
        return False
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
    return autostart_enabled()


def desktop_url(port: int, admin_token: str) -> str:
    # Das Token steht im URL-Fragment (#) – es wird nie an den Server gesendet oder geloggt.
    return f"http://127.0.0.1:{port}/#admin={admin_token}"


def open_desktop_ui(port: int, admin_token: str) -> None:
    url = desktop_url(port, admin_token)
    candidates = []
    if IS_WINDOWS:
        candidates = [shutil.which("msedge"),
                      os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
                      os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
                      os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe")]
    else:
        candidates = [shutil.which("chromium"), shutil.which("google-chrome")]
    for exe in candidates:
        if exe and os.path.exists(exe):
            subprocess.Popen([exe, f"--app={url}", "--window-size=1400,900"], close_fds=True)
            return
    webbrowser.open(url)


def run_tray(port: int, admin_token: str, on_quit, toggle_remote) -> None:
    """Blockiert; muss im Hauptthread laufen. Benötigt ``pystray`` und ``Pillow``."""
    import pystray  # type: ignore
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), outline=(0, 229, 255, 255), width=5)
    d.ellipse((22, 22, 42, 42), fill=(0, 229, 255, 255))

    def _open(icon, item):
        open_desktop_ui(port, admin_token)

    def _remote(icon, item):
        toggle_remote()

    def _autostart(icon, item):
        set_autostart(not autostart_enabled())

    def _quit(icon, item):
        icon.stop()
        on_quit()

    menu = pystray.Menu(
        pystray.MenuItem("JARVIS öffnen", _open, default=True),
        pystray.MenuItem("Fernzugriff an/aus", _remote),
        pystray.MenuItem("Autostart beim Login", _autostart, checked=lambda item: autostart_enabled()),
        pystray.MenuItem("Beenden", _quit),
    )
    pystray.Icon("JARVIS", img, "J.A.R.V.I.S.", menu).run()
