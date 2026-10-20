"""Einstiegspunkt für den PyInstaller-Build (JARVIS.exe). Ohne Argumente: Start mit Infobereich-Symbol."""
import sys

from jarvis.__main__ import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["--tray"]))
