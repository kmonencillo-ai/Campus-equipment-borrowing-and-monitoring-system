param(
    [Parameter(Mandatory = $true)]
    [string]$DatabaseUrl,

    [switch]$ImportCurrentData,

    [switch]$SkipMigrate
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvPath = Join-Path $ProjectRoot ".env"
$PythonPath = Join-Path $ProjectRoot "..\..\venv\Scripts\python.exe"

if ($DatabaseUrl -notmatch "^postgres(ql)?://") {
    throw "Use the database URI copied from your Supabase project settings."
}

if ($DatabaseUrl -notmatch "(\?|&)sslmode=") {
    if ($DatabaseUrl.Contains("?")) {
        $DatabaseUrl = "${DatabaseUrl}&sslmode=require"
    } else {
        $DatabaseUrl = "${DatabaseUrl}?sslmode=require"
    }
}

if (-not (Test-Path $PythonPath)) {
    $PythonPath = "python"
}

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

function Invoke-Django {
    param(
        [string[]]$Arguments
    )

    & $PythonPath manage.py @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Django command failed: manage.py $($Arguments -join ' ')"
    }
}

$TransferPath = Join-Path $ProjectRoot "supabase-transfer.json"
if ($ImportCurrentData) {
    Push-Location $ProjectRoot
    try {
        Invoke-Django @('dumpdata', '--exclude', 'auth.permission', '--exclude', 'contenttypes', '--natural-foreign', '--natural-primary', '--indent', '2', '-o', $TransferPath)
    } finally {
        Pop-Location
    }
    Write-Host "Current database exported for Supabase import."
}

$lines = @()
if (Test-Path $EnvPath) {
    $lines = Get-Content -Path $EnvPath
}

$escapedDatabaseUrl = $DatabaseUrl.Replace('"', '\"')
$updated = $false
$lines = foreach ($line in $lines) {
    if ($line -match "^SUPABASE_DATABASE_URL=") {
        $updated = $true
        "SUPABASE_DATABASE_URL=""$escapedDatabaseUrl"""
    } elseif ($line -match "^DATABASE_URL=") {
        $null
    } elseif ($line -match "^DJANGO_DB_SSLMODE=") {
        $null
    } elseif ($line -match "^DJANGO_DB_ENGINE=" -or $line -match "^DJANGO_DB_NAME=" -or $line -match "^DJANGO_DB_USER=" -or $line -match "^DJANGO_DB_PASSWORD=" -or $line -match "^DJANGO_DB_HOST=" -or $line -match "^DJANGO_DB_PORT=") {
        $null
    } else {
        $line
    }
}

if (-not $updated) {
    $lines += "SUPABASE_DATABASE_URL=""$escapedDatabaseUrl"""
}

Set-Content -Path $EnvPath -Value $lines -Encoding UTF8
Write-Host "Supabase database URL saved to .env."

if (-not $SkipMigrate) {
    Push-Location $ProjectRoot
    try {
        Invoke-Django @('migrate')
        if ($ImportCurrentData) {
            Invoke-Django @('loaddata', $TransferPath)
        }
        Invoke-Django @('check')
        Invoke-Django @('shell', '-c', "from django.db import connection; cursor = connection.cursor(); cursor.execute('SELECT 1'); print('Supabase database connection OK')")
    } finally {
        Pop-Location
    }
}
