[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SchemaPath,

    [Parameter(Mandatory = $false)]
    [string]$AdminPassword = "",

    [Parameter(Mandatory = $false)]
    [string]$HostName = "127.0.0.1",

    [Parameter(Mandatory = $false)]
    [int]$Port = 3306,

    [Parameter(Mandatory = $false)]
    [string]$OperatorPin = "202610",

    [Parameter(Mandatory = $false)]
    [string]$SuccessMarker = "",

    [Parameter(Mandatory = $false)]
    [switch]$SkipConfigWrite
)

$ErrorActionPreference = "Stop"

if ($SuccessMarker -and (Test-Path -LiteralPath $SuccessMarker)) {
    Remove-Item -LiteralPath $SuccessMarker -Force
}

if (-not (Test-Path -LiteralPath $SchemaPath)) {
    throw "Topup Database schema was not found: $SchemaPath"
}
if ($OperatorPin -notmatch '^\d{6,}$') {
    throw "Operator PIN must contain at least 6 digits."
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

function Find-DatabaseClient {
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

function New-RandomSecret {
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

function ConvertTo-Hex([byte[]]$Bytes) {
    return -join ($Bytes | ForEach-Object { $_.ToString("x2") })
}

function Protect-ForCurrentUser([string]$Value) {
    $plain = [Text.Encoding]::UTF8.GetBytes($Value)
    $protected = [Security.Cryptography.ProtectedData]::Protect(
        $plain,
        $null,
        [Security.Cryptography.DataProtectionScope]::CurrentUser
    )
    return [Convert]::ToBase64String($protected)
}

$client = Find-DatabaseClient
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("SmartDispenserTopupDb_" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot | Out-Null
$defaultsFile = Join-Path $tempRoot "admin.cnf"
$appDefaultsFile = Join-Path $tempRoot "app.cnf"
$provisionSql = Join-Path $tempRoot "provision.sql"

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

    $appUser = "sd_topup_app"
    $appPassword = New-RandomSecret
    $salt = New-Object byte[] 16
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($salt)
    }
    finally {
        $generator.Dispose()
    }
    $derive = [Security.Cryptography.Rfc2898DeriveBytes]::new(
        $OperatorPin,
        $salt,
        250000,
        [Security.Cryptography.HashAlgorithmName]::SHA256
    )
    try {
        $pinHash = $derive.GetBytes(32)
    }
    finally {
        $derive.Dispose()
    }
    $saltHex = ConvertTo-Hex $salt
    $hashHex = ConvertTo-Hex $pinHash

    $bootstrap = "CREATE DATABASE IF NOT EXISTS smartdispenser_topup CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    & $client "--defaults-extra-file=$defaultsFile" "--execute=$bootstrap"
    if ($LASTEXITCODE -ne 0) {
        throw "Topup Database creation failed with exit code $LASTEXITCODE."
    }

    Get-Content -LiteralPath $SchemaPath -Raw | & $client "--defaults-extra-file=$defaultsFile" smartdispenser_topup
    if ($LASTEXITCODE -ne 0) {
        throw "Topup schema installation failed with exit code $LASTEXITCODE."
    }

    $sql = @"
CREATE USER IF NOT EXISTS '$appUser'@'127.0.0.1' IDENTIFIED BY '$appPassword';
ALTER USER '$appUser'@'127.0.0.1' IDENTIFIED BY '$appPassword';
CREATE USER IF NOT EXISTS '$appUser'@'localhost' IDENTIFIED BY '$appPassword';
ALTER USER '$appUser'@'localhost' IDENTIFIED BY '$appPassword';
GRANT SELECT, INSERT, UPDATE, DELETE ON smartdispenser_topup.* TO '$appUser'@'127.0.0.1';
GRANT SELECT, INSERT, UPDATE, DELETE ON smartdispenser_topup.* TO '$appUser'@'localhost';
INSERT INTO smartdispenser_topup.operators(username,pin_salt,pin_hash,enabled)
VALUES('admin',UNHEX('$saltHex'),UNHEX('$hashHex'),1)
ON DUPLICATE KEY UPDATE pin_salt=VALUES(pin_salt),pin_hash=VALUES(pin_hash),enabled=1;
FLUSH PRIVILEGES;
"@
    [IO.File]::WriteAllText($provisionSql, $sql, [Text.UTF8Encoding]::new($false))
    Get-Content -LiteralPath $provisionSql -Raw | & $client "--defaults-extra-file=$defaultsFile"
    if ($LASTEXITCODE -ne 0) {
        throw "Topup account provisioning failed with exit code $LASTEXITCODE."
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
    $verification = "SELECT COUNT(*) FROM operators WHERE username='admin' AND enabled=1;"
    & $client "--defaults-extra-file=$appDefaultsFile" "--batch" "--skip-column-names" "--execute=$verification" smartdispenser_topup | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Topup application account verification failed with exit code $LASTEXITCODE."
    }

    if (-not $SkipConfigWrite) {
        $configDirectory = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "SmartDispenserTopup"
        New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null
        $config = [ordered]@{
            host = $HostName
            port = $Port
            admin_user = "root"
            app_user = $appUser
            app_secret = Protect-ForCurrentUser $appPassword
            operator_pin_secret = Protect-ForCurrentUser $OperatorPin
        }
        $configPath = Join-Path $configDirectory "config.json"
        $configTempPath = Join-Path $configDirectory "config.json.new"
        [IO.File]::WriteAllText($configTempPath, ($config | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $configTempPath -Destination $configPath -Force
    }

    if ($SuccessMarker) {
        [IO.File]::WriteAllText($SuccessMarker, "database-ready", [Text.UTF8Encoding]::new($false))
    }
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
