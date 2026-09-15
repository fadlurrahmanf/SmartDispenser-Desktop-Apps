[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$AdminPassword = "",

    [Parameter(Mandatory = $false)]
    [string]$HostName = "127.0.0.1",

    [Parameter(Mandatory = $false)]
    [int]$Port = 3306,

    [Parameter(Mandatory = $false)]
    [string]$SuccessMarker = "",

    [Parameter(Mandatory = $false)]
    [switch]$SkipEnvironmentWrite
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Security

if ($AdminPassword -eq "__SMARTDISPENSER_EMPTY_PASSWORD__") {
    $AdminPassword = ""
}

$diagnosticDirectory = Join-Path $env:ProgramData "SmartDispenser"
$diagnosticLog = Join-Path $diagnosticDirectory "perso-installer-database.log"
New-Item -ItemType Directory -Path $diagnosticDirectory -Force | Out-Null
"[$(Get-Date -Format o)] Perso database provisioning started." | Set-Content -LiteralPath $diagnosticLog -Encoding UTF8
trap {
    "[$(Get-Date -Format o)] $($_ | Out-String)" | Add-Content -LiteralPath $diagnosticLog -Encoding UTF8
    if ($_.ScriptStackTrace) {
        $_.ScriptStackTrace | Add-Content -LiteralPath $diagnosticLog -Encoding UTF8
    }
    exit 1
}

if ($SuccessMarker -and (Test-Path -LiteralPath $SuccessMarker)) {
    Remove-Item -LiteralPath $SuccessMarker -Force
}

foreach ($serviceName in @("SmartDispenserMariaDB", "MariaDB", "mysql")) {
    $service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
    if ($service) {
        if ($service.Status -ne "Running") {
            Start-Service -Name $serviceName
            $service.WaitForStatus("Running", [TimeSpan]::FromSeconds(30))
        }
        break
    }
}

function Find-MariaDbClient {
    $fixedCandidates = @(
        "C:\xampp\mysql\bin\mariadb.exe",
        "C:\xampp\mysql\bin\mysql.exe"
    )
    foreach ($candidate in $fixedCandidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    $programFiles = [Environment]::GetFolderPath("ProgramFiles")
    $patterns = @(
        (Join-Path $programFiles "MariaDB *\bin\mariadb.exe"),
        (Join-Path $programFiles "MariaDB *\bin\mysql.exe"),
        (Join-Path $programFiles "MySQL\MySQL Server *\bin\mysql.exe")
    )
    foreach ($pattern in $patterns) {
        $match = Get-Item -Path $pattern -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($match) {
            return $match.FullName
        }
    }
    throw "MariaDB/MySQL client was not found after Database installation."
}

function Wait-ForDatabase([string]$Client, [string]$DefaultsFile) {
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        & $Client "--defaults-extra-file=$DefaultsFile" "--connect-timeout=2" "--execute=SELECT 1" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            return
        }
        Start-Sleep -Seconds 1
    }
    throw "Database did not accept the administrator credentials within 30 seconds. Check the root password and Database service."
}

function New-SecureAppPassword {
    $bytes = New-Object byte[] 24
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    return [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "A").Replace("/", "B")
}

function Protect-ForMachine([string]$Value) {
    $plain = [Text.Encoding]::UTF8.GetBytes($Value)
    $protected = [Security.Cryptography.ProtectedData]::Protect(
        $plain,
        $null,
        [Security.Cryptography.DataProtectionScope]::LocalMachine
    )
    return [Convert]::ToBase64String($protected)
}

$client = Find-MariaDbClient
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("SmartDispenserDb_" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot | Out-Null
$defaultsFile = Join-Path $tempRoot "admin.cnf"
$appDefaultsFile = Join-Path $tempRoot "app.cnf"
$sqlFile = Join-Path $tempRoot "provision.sql"

try {
    $escapedAdminPassword = $AdminPassword.Replace("\", "\\").Replace('"', '\"')
    $defaults = @(
        "[client]",
        "host=$HostName",
        "port=$Port",
        "user=root",
        "password=`"$escapedAdminPassword`"",
        "protocol=tcp"
    )
    [IO.File]::WriteAllLines($defaultsFile, $defaults, [Text.UTF8Encoding]::new($false))
    Wait-ForDatabase $client $defaultsFile

    $appUser = "perso_console_app"
    $appPassword = New-SecureAppPassword
    $sql = @"
CREATE DATABASE IF NOT EXISTS Perso_database CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$appUser'@'127.0.0.1' IDENTIFIED BY '$appPassword';
ALTER USER '$appUser'@'127.0.0.1' IDENTIFIED BY '$appPassword';
CREATE USER IF NOT EXISTS '$appUser'@'localhost' IDENTIFIED BY '$appPassword';
ALTER USER '$appUser'@'localhost' IDENTIFIED BY '$appPassword';
GRANT ALL PRIVILEGES ON Perso_database.* TO '$appUser'@'127.0.0.1';
GRANT ALL PRIVILEGES ON Perso_database.* TO '$appUser'@'localhost';
FLUSH PRIVILEGES;
"@
    [IO.File]::WriteAllText($sqlFile, $sql, [Text.UTF8Encoding]::new($false))

    Get-Content -LiteralPath $sqlFile -Raw | & $client "--defaults-extra-file=$defaultsFile"
    if ($LASTEXITCODE -ne 0) {
        throw "Database provisioning failed with exit code $LASTEXITCODE."
    }

    $escapedAppPassword = $appPassword.Replace("\", "\\").Replace('"', '\"')
    $appDefaults = @(
        "[client]",
        "host=$HostName",
        "port=$Port",
        "user=$appUser",
        "password=`"$escapedAppPassword`"",
        "protocol=tcp"
    )
    [IO.File]::WriteAllLines($appDefaultsFile, $appDefaults, [Text.UTF8Encoding]::new($false))
    & $client "--defaults-extra-file=$appDefaultsFile" "--batch" "--skip-column-names" "--execute=SELECT 1" Perso_database | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Perso application account verification failed with exit code $LASTEXITCODE."
    }

    if (-not $SkipEnvironmentWrite) {
        $configDirectory = Join-Path $env:ProgramData "SmartDispenser\Perso"
        New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null
        $config = [ordered]@{
            host = $HostName
            port = $Port
            app_user = $appUser
            scope = "machine"
            app_secret = Protect-ForMachine $appPassword
        }
        $configPath = Join-Path $configDirectory "config.json"
        $configTempPath = Join-Path $configDirectory "config.json.new"
        [IO.File]::WriteAllText($configTempPath, ($config | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $configTempPath -Destination $configPath -Force
    }

    if ($SuccessMarker) {
        [IO.File]::WriteAllText($SuccessMarker, "database-ready", [Text.UTF8Encoding]::new($false))
        "[$(Get-Date -Format o)] Perso database provisioning verified." | Add-Content -LiteralPath $diagnosticLog -Encoding UTF8
    }
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
