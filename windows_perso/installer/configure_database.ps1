[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$AdminPassword = "",

    [Parameter(Mandatory = $false)]
    [string]$HostName = "127.0.0.1",

    [Parameter(Mandatory = $false)]
    [int]$Port = 3306,

    [Parameter(Mandatory = $false)]
    [switch]$SkipEnvironmentWrite
)

$ErrorActionPreference = "Stop"

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

$client = Find-MariaDbClient
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("SmartDispenserDb_" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot | Out-Null
$defaultsFile = Join-Path $tempRoot "admin.cnf"
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

    if (-not $SkipEnvironmentWrite) {
        $environmentKey = "HKCU:\Environment"
        New-Item -Path $environmentKey -Force | Out-Null
        New-ItemProperty -Path $environmentKey -Name "SMARTDISPENSER_MYSQL_USER" -Value $appUser -PropertyType String -Force | Out-Null
        New-ItemProperty -Path $environmentKey -Name "SMARTDISPENSER_MYSQL_PASSWORD" -Value $appPassword -PropertyType String -Force | Out-Null

        Add-Type -Namespace Win32 -Name NativeMethods -MemberDefinition @"
[DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Auto)]
public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint Msg, UIntPtr wParam, string lParam, uint flags, uint timeout, out UIntPtr result);
"@
        $broadcastResult = [UIntPtr]::Zero
        [void][Win32.NativeMethods]::SendMessageTimeout([IntPtr]0xffff, 0x001A, [UIntPtr]::Zero, "Environment", 2, 5000, [ref]$broadcastResult)
    }
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
