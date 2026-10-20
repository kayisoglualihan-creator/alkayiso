# Startet Jarvis mit Symbol im Infobereich und öffnet die Desktop-Oberfläche.
$Root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $Root "backend")
& (Join-Path $Root ".venv\Scripts\python.exe") -m jarvis --tray @args
