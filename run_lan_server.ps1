param(
    [int]$Port = 8000,
    [int]$MaxPort = 8010,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'

function Test-PortInUse {
    param([int]$PortNumber)
    return [bool](Get-NetTCPConnection -LocalPort $PortNumber -State Listen -ErrorAction SilentlyContinue)
}

function Get-LanAddresses {
    $addresses = @()

    try {
        $addresses = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object {
                $_.IPAddress -notlike '127.*' -and
                $_.IPAddress -notlike '169.254.*' -and
                $_.PrefixOrigin -ne 'WellKnown'
            } |
            Select-Object -ExpandProperty IPAddress
    } catch {
        foreach ($line in (ipconfig)) {
            if ($line -match 'IPv4.*?:\s*([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)') {
                $address = $Matches[1]
                if ($address -notlike '127.*' -and $address -notlike '169.254.*') {
                    $addresses += $address
                }
            }
        }
    }

    return @($addresses | Select-Object -Unique)
}

function Open-LocalBrowser {
    param([string]$Url)

    $browserCommands = @('msedge.exe', 'chrome.exe')
    foreach ($browser in $browserCommands) {
        try {
            Start-Process -FilePath $browser -ArgumentList $Url -ErrorAction Stop
            return
        } catch {
            continue
        }
    }

    Start-Process $Url
}

function Test-DjangoDatabase {
    param([string]$PythonExecutable)

    $checkCode = "from django.db import connection; cursor = connection.cursor(); cursor.execute('select 1')"
    $output = & $PythonExecutable manage.py shell -c $checkCode 2>&1

    if ($LASTEXITCODE -ne 0) {
        Write-Host ''
        Write-Host 'The system could not connect to Supabase yet.' -ForegroundColor Red
        Write-Host 'Check your internet connection, Supabase project status, and Windows Firewall/network rules.' -ForegroundColor Yellow
        Write-Host 'If you are using a school or public network, it may block database traffic.' -ForegroundColor Yellow
        Write-Host ''
        Write-Host 'Technical details:' -ForegroundColor White
        $output | Select-Object -Last 18 | ForEach-Object { Write-Host "  $_" }
        Write-Host ''
        return $false
    }

    return $true
}

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = Join-Path $projectRoot '..\..\venv\Scripts\python.exe'
$computerName = $env:COMPUTERNAME

if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonPath = 'python'
}

$selectedPort = $null
foreach ($candidatePort in $Port..$MaxPort) {
    if (-not (Test-PortInUse -PortNumber $candidatePort)) {
        $selectedPort = $candidatePort
        break
    }
}

if (-not $selectedPort) {
    Write-Host ''
    Write-Host "No free port was found from $Port to $MaxPort." -ForegroundColor Yellow
    Write-Host 'Close another running server, then start this script again.'
    Write-Host ''
    exit 1
}

$addresses = Get-LanAddresses
$localUrl = "http://127.0.0.1:$selectedPort/"
$hostNameUrl = if ($computerName) { "http://$computerName`:$selectedPort/" } else { $null }

$env:DJANGO_ALLOW_LAN_HOSTS = 'True'

Set-Location -LiteralPath $projectRoot

Write-Host ''
Write-Host 'Checking Supabase connection...' -ForegroundColor Cyan
if (-not (Test-DjangoDatabase -PythonExecutable $pythonPath)) {
    exit 1
}

Write-Host ''
Write-Host 'Campus Equipment Hub - Shared Start' -ForegroundColor Cyan
Write-Host '====================================' -ForegroundColor Cyan
if ($selectedPort -ne $Port) {
    Write-Host "Port $Port was busy, so the system will use port $selectedPort." -ForegroundColor Yellow
}
Write-Host ''
Write-Host 'Use this link on this computer:' -ForegroundColor White
Write-Host "  $localUrl" -ForegroundColor Green
Write-Host ''
Write-Host 'Try this link on other devices on the same Wi-Fi:' -ForegroundColor White
if ($hostNameUrl) {
    Write-Host "  $hostNameUrl" -ForegroundColor Green
} else {
    Write-Host '  Computer name was not detected. Use one of the IP links below.' -ForegroundColor Yellow
}
Write-Host ''
Write-Host 'Backup phone/tablet links:' -ForegroundColor White
if ($addresses.Count -eq 0) {
    Write-Host '  No LAN IP address was detected. Check your Wi-Fi/network connection.' -ForegroundColor Yellow
} else {
    foreach ($address in $addresses) {
        Write-Host "  http://$address`:$selectedPort/" -ForegroundColor Green
    }
}
Write-Host ''
Write-Host "Do not open http://0.0.0.0:$selectedPort/ in a browser. That is only the server bind address." -ForegroundColor Yellow
Write-Host 'Keep this window open while using the system.'
Write-Host 'Other devices must be on the same Wi-Fi/network.'
Write-Host 'Allow Python/Django through Windows Firewall if prompted.'
Write-Host ''

if (-not $NoBrowser) {
    Write-Host "Opening $localUrl ..." -ForegroundColor Cyan
    Open-LocalBrowser -Url $localUrl
    Write-Host ''
}

& $pythonPath manage.py runserver "0.0.0.0:$selectedPort"
