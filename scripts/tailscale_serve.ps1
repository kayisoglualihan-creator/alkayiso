<#
  Richtet Tailscale Serve ein: https://<pc-name>.<tailnet>.ts.net  ->  http://127.0.0.1:8765
  NUR im privaten Tailnet erreichbar. Funnel (öffentlich) wird ausdrücklich NICHT verwendet.
#>
param([int]$Port = 8765)
$ErrorActionPreference = "Stop"
$ts = (Get-Command tailscale -ErrorAction SilentlyContinue).Source
if (-not $ts) { $ts = "C:\Program Files\Tailscale\tailscale.exe" }
if (-not (Test-Path $ts)) { Write-Host "Tailscale nicht installiert: winget install Tailscale.Tailscale"; exit 1 }
& $ts status | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "Bitte zuerst in Tailscale anmelden (Infobereich -> Log in)."; exit 1 }
# Sicherheit: eventuell aktiven Funnel abschalten
& $ts funnel reset 2>$null | Out-Null
& $ts serve --bg --https=443 "http://127.0.0.1:$Port"
& $ts serve status
$dns = (& $ts status --json | ConvertFrom-Json).Self.DNSName.TrimEnd(".")
Write-Host "`nJarvis ist im Tailnet erreichbar unter: https://$dns" -ForegroundColor Green
Write-Host "Hinweis: HTTPS-Zertifikate müssen im Tailscale-Adminbereich aktiviert sein (DNS -> HTTPS Certificates)."
