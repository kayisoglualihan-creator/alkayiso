# Führt alle Backend-Tests aus (inkl. Integrationstests mit echtem Serverprozess).
$Root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $Root "backend")
& (Join-Path $Root ".venv\Scripts\python.exe") -m pip install -q pytest
& (Join-Path $Root ".venv\Scripts\python.exe") -m pytest -o addopts="" -v @args
