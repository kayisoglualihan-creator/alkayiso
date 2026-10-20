# PyInstaller-Spezifikation für JARVIS.exe (Backend + Weboberfläche + Infobereich).
# Bauen (unter Windows):  pyinstaller installers\jarvis.spec --noconfirm
import os
from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
BACKEND = os.path.join(ROOT, "backend")

a = Analysis(
    [os.path.join(ROOT, "installers", "jarvis_launcher.py")],
    pathex=[BACKEND],
    datas=[(os.path.join(BACKEND, "jarvis", "web"), os.path.join("jarvis", "web"))],
    hiddenimports=collect_submodules("uvicorn") + collect_submodules("jarvis") + ["pystray._win32", "keyring.backends.Windows", "playwright.async_api"],
    excludes=["tkinter", "matplotlib", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="JARVIS", console=False,
          icon=os.path.join(ROOT, "installers", "jarvis.ico"))
coll = COLLECT(exe, a.binaries, a.datas, name="JARVIS")
