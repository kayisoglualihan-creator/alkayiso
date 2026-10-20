"""Startpunkt: ``python -m jarvis`` (Server), ``--open`` (Desktop-Oberfläche öffnen), ``--tray`` (Infobereich)."""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time

import uvicorn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jarvis", description="J.A.R.V.I.S. – persönlicher KI-Assistent")
    parser.add_argument("--host", default=None, help="Standard 127.0.0.1 (Fernzugriff über Tailscale Serve)")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--open", action="store_true", help="Desktop-Oberfläche im App-Fenster öffnen")
    parser.add_argument("--tray", action="store_true", help="Mit Symbol im Infobereich starten (Windows)")
    parser.add_argument("--autostart", choices=["on", "off"], help="Autostart beim Windows-Login setzen und beenden")
    parser.add_argument("--print-admin-token", action="store_true", help="Lokales Admin-Token ausgeben (nach Start)")
    parser.add_argument("--diagnose", action="store_true", help="Umgebung prüfen und Hinweise ausgeben")
    args = parser.parse_args(argv)

    gui_mode = sys.stdout is None  # Fensteranwendung (PyInstaller, console=False)
    if gui_mode:
        from .config import load_settings as _ls
        name = "diagnose.txt" if args.diagnose else "jarvis.log"
        log_path = _ls().data_dir / name
        log_file = open(log_path, "w" if args.diagnose else "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stderr = log_file

    if args.diagnose:
        from .diagnose import main as diagnose
        code = diagnose()
        if gui_mode:  # Ergebnis im Editor anzeigen, da es kein Konsolenfenster gibt
            log_file.close()
            if hasattr(os, "startfile"):
                os.startfile(str(log_path))  # type: ignore[attr-defined]
        return code

    from .config import load_settings
    from .windows_agent import open_desktop_ui, run_tray, set_autostart

    if args.autostart:
        ok = set_autostart(args.autostart == "on")
        print("Autostart aktiv" if ok else "Autostart aus")
        return 0

    if args.data_dir:
        os.environ["JARVIS_DATA_DIR"] = args.data_dir
    settings = load_settings()
    if args.host:
        settings.host = args.host
    if args.port:
        settings.port = args.port
    if settings.host not in ("127.0.0.1", "localhost", "::1"):
        print("WARNUNG: Jarvis lauscht nicht nur lokal. Empfohlen ist 127.0.0.1 + Tailscale Serve.", file=sys.stderr)

    # Läuft Jarvis bereits? Dann nur die Oberfläche öffnen (eine Instanz pro Benutzer).
    try:
        import httpx
        if httpx.get(f"http://127.0.0.1:{settings.port}/api/health", timeout=1.5).status_code == 200:
            print("Jarvis läuft bereits – öffne die Oberfläche.")
            open_desktop_ui(settings.port, settings.admin_token_file.read_text().strip())
            return 0
    except Exception:
        pass

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from .api.app import create_app

    app = create_app(settings)
    config = uvicorn.Config(app, host=settings.host, port=settings.port, log_level="info", access_log=False)
    server = uvicorn.Server(config)

    def wait_and_open():
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.1)
        token = settings.admin_token_file.read_text().strip()
        if args.print_admin_token:
            print(f"Admin-Token: {token}")
        if args.open or args.tray:
            open_desktop_ui(settings.port, token)

    if args.tray:
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        wait_and_open()

        def toggle_remote():
            j = app.state.jarvis
            j.db.set_setting("remote_access_enabled", not j.db.get_setting("remote_access_enabled", True))

        def quit_():
            server.should_exit = True

        try:
            run_tray(settings.port, settings.admin_token_file.read_text().strip(), quit_, toggle_remote)
        except ImportError:
            print("pystray nicht installiert – laufe ohne Infobereich-Symbol weiter.")
            thread.join()
        thread.join(timeout=10)
        return 0

    threading.Thread(target=wait_and_open, daemon=True).start()
    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
