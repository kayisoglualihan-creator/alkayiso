<#
  JARVIS – Installation aus dem Quellcode (Windows 10/11)
  Ausführen in PowerShell im Projektordner:
      powershell -ExecutionPolicy Bypass -File scripts\install.ps1
  Optional:  -Voice   (lokale Sprachdienste: faster-whisper, Piper, openWakeWord)
             -Autostart (Jarvis beim Windows-Login starten)
#>
param([switch]$Voice, [switch]$Autostart)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
Write-Host "=== J.A.R.V.I.S. Installation ===" -ForegroundColor Cyan

# 1. Python prüfen
$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) { $python = "py -3.12" } else { $python = "python" }
try { $ver = & cmd /c "$python --version" 2>&1 } catch { $ver = "" }
if ($ver -notmatch "Python 3\.(1[1-9])") {
  Write-Host "Python 3.11+ wurde nicht gefunden." -ForegroundColor Yellow
  Write-Host "Bitte installieren: winget install Python.Python.3.12  (oder https://www.python.org/downloads/)"
  exit 1
}
Write-Host "Gefunden: $ver"

# 2. Virtuelle Umgebung + Abhängigkeiten
if (-not (Test-Path ".venv")) { & cmd /c "$python -m venv .venv" }
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
& $venvPy -m pip install --upgrade pip | Out-Null
& $venvPy -m pip install -r backend\requirements-windows.txt
if ($Voice) { & $venvPy -m pip install -r backend\requirements-voice.txt }

# 3. Tailscale prüfen
$ts = Get-Command tailscale -ErrorAction SilentlyContinue
if (-not $ts -and -not (Test-Path "C:\Program Files\Tailscale\tailscale.exe")) {
  Write-Host "Hinweis: Tailscale ist nicht installiert (für den iPhone-Fernzugriff nötig)." -ForegroundColor Yellow
  Write-Host "         winget install Tailscale.Tailscale   – danach scripts\tailscale_serve.ps1 ausführen."
}

# 4. Startmenü-Verknüpfung
$lnk = Join-Path ([Environment]::GetFolderPath("Programs")) "JARVIS.lnk"
$wsh = New-Object -ComObject WScript.Shell
$s = $wsh.CreateShortcut($lnk)
$s.TargetPath = Join-Path $Root ".venv\Scripts\pythonw.exe"
$s.Arguments = "-m jarvis --tray"
$s.WorkingDirectory = Join-Path $Root "backend"
$s.IconLocation = Join-Path $Root "installers\jarvis.ico"
$s.Save()
Write-Host "Startmenü-Eintrag erstellt: JARVIS"

if ($Autostart) {
  Push-Location backend; & $venvPy -m jarvis --autostart on; Pop-Location
}
Write-Host "`nFertig. Starte Jarvis über das Startmenü oder: scripts\start.ps1" -ForegroundColor Green
