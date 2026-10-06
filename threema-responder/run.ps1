<#
  run.ps1 — start the Threema Gateway auto-responder on Windows + expose its
  callback over ngrok. This is the SANCTIONED route: a dedicated Gateway ID
  (*BOT). Contacts see the asterisk — they know it's an automated service.
  It does not, and cannot, appear to be you.

  Prereqs:
    - Python 3.11+ on PATH            (python --version)
    - ngrok on PATH + authtoken set   (ngrok config add-authtoken <token>)
    - .env filled in (copy config.example.env -> .env); needs a real
      GATEWAY_ID / GATEWAY_SECRET / PRIVATE_KEY_HEX from the Threema Gateway
      console. Without those the backend starts but Threema won't talk to it.

  Usage:
    .\run.ps1                 # port 8080
    .\run.ps1 -Port 9000
#>
param([int]$Port = 8080)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".env")) { throw "No .env — copy config.example.env to .env and fill it in first." }

# --- one-time deps into a local venv ---------------------------------------
if (-not (Test-Path ".venv")) {
    Write-Host "creating venv + installing requirements..." -ForegroundColor Cyan
    python -m venv .venv
    & .\.venv\Scripts\python.exe -m pip install -q -r requirements.txt
}
$py = ".\.venv\Scripts\python.exe"

# --- start the backend ------------------------------------------------------
Write-Host "starting backend on http://127.0.0.1:$Port ..." -ForegroundColor Cyan
$backend = Start-Process $py -ArgumentList "-m","uvicorn","app:app","--host","127.0.0.1","--port","$Port" -PassThru -NoNewWindow

# --- start ngrok, then read the public URL from its local API ---------------
Write-Host "starting ngrok tunnel ..." -ForegroundColor Cyan
$ngrok = Start-Process "ngrok" -ArgumentList "http","$Port","--log=stdout" -PassThru -WindowStyle Hidden

$public = $null
foreach ($i in 1..20) {
    Start-Sleep -Milliseconds 700
    try {
        $t = Invoke-RestMethod "http://127.0.0.1:4040/api/tunnels" -ErrorAction Stop
        $public = ($t.tunnels | Where-Object { $_.proto -eq "https" } | Select-Object -First 1).public_url
        if ($public) { break }
    } catch { }
}
if (-not $public) {
    Stop-Process $backend,$ngrok -ErrorAction SilentlyContinue
    throw "ngrok did not report a public URL — is it installed and the authtoken set? (http://127.0.0.1:4040)"
}

Write-Host ""
Write-Host "=============================================================" -ForegroundColor Green
Write-Host " Backend : http://127.0.0.1:$Port"
Write-Host " Public  : $public"
Write-Host ""
Write-Host " Register this in the Threema Gateway console as the callback:" -ForegroundColor Yellow
Write-Host "   $public/callback"
Write-Host ""
Write-Host " Phone Focus / Tasker webhook (presence):"
Write-Host "   $public/presence   (POST token=<PRESENCE_TOKEN>&focus=on|off|clear)"
Write-Host ""
Write-Host " ngrok inspector: http://127.0.0.1:4040    Ctrl+C to stop both."
Write-Host "=============================================================" -ForegroundColor Green

# --- wait, then clean up both children on Ctrl+C ----------------------------
try   { Wait-Process -Id $backend.Id }
finally {
    Write-Host "`nstopping ..." -ForegroundColor Cyan
    Stop-Process $backend,$ngrok -ErrorAction SilentlyContinue
}
