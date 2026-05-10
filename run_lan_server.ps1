$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = Join-Path $projectRoot '..\..\venv\Scripts\python.exe'
$port = 8000
$computerName = $env:COMPUTERNAME

if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonPath = 'python'
}

$portInUse = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($portInUse) {
    Write-Host ''
    Write-Host "Port $port is already in use. Close the running server first, or change `$port in run_lan_server.ps1." -ForegroundColor Yellow
    Write-Host ''
    exit 1
}

$addresses = @()
foreach ($line in (ipconfig)) {
    if ($line -match 'IPv4.*?:\s*([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)') {
        $address = $Matches[1]
        if ($address -notlike '127.*' -and $address -notlike '169.254.*') {
            $addresses += $address
        }
    }
}
$addresses = $addresses | Select-Object -Unique

Write-Host ''
Write-Host 'Campus Equipment System URLs:'
Write-Host "  This computer: http://127.0.0.1:$port/"
Write-Host "  This computer: http://localhost:$port/"
Write-Host ''
Write-Host 'Preferred same-Wi-Fi URL:'
if ($computerName) {
    Write-Host "  http://$computerName`:$port/" -ForegroundColor Green
} else {
    Write-Host '  Computer name was not detected. Use one of the IP links below.'
}
Write-Host ''
Write-Host 'Backup phone/tablet URLs:'
if ($addresses.Count -eq 0) {
    Write-Host '  No LAN IP address was detected. Check your Wi-Fi/network connection.'
} else {
    foreach ($address in $addresses) {
        Write-Host "  http://$address`:$port/"
    }
}
Write-Host ''
Write-Host "Do not open http://0.0.0.0:$port/ in a browser. That is only the server bind address."
Write-Host 'Keep this window open while using the system on your phone/tablet.'
Write-Host 'Your device must be on the same Wi-Fi/network. If the preferred URL does not load, use a backup IP URL.'
Write-Host 'Allow Python/Django through Windows Firewall if prompted.'
Write-Host ''

Set-Location -LiteralPath $projectRoot
& $pythonPath manage.py runserver "0.0.0.0:$port"
