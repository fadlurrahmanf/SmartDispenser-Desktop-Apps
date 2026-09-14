[CmdletBinding()]
param(
    [switch]$RefreshPrerequisites
)

$ErrorActionPreference = "Stop"
$installerDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = Split-Path -Parent $installerDir
$prereqDir = Join-Path $installerDir "prerequisites"
$outputDir = Join-Path $installerDir "output"
$webViewInstaller = Join-Path $prereqDir "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
$mariaDbInstaller = Join-Path $prereqDir "mariadb-11.8.9-winx64.msi"
$ch340Dir = Join-Path $prereqDir "ch340"

New-Item -ItemType Directory -Path $prereqDir -Force | Out-Null
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null

if ($RefreshPrerequisites -or -not (Test-Path -LiteralPath $webViewInstaller)) {
    Invoke-WebRequest "https://go.microsoft.com/fwlink/?LinkId=2124701" -OutFile $webViewInstaller
}

if ($RefreshPrerequisites -or -not (Test-Path -LiteralPath $mariaDbInstaller)) {
    Invoke-WebRequest "https://downloads.mariadb.org/rest-api/mariadb/11.8.9/mariadb-11.8.9-winx64.msi" -OutFile $mariaDbInstaller
}

$expectedMariaDbSha256 = "372822572baa7f429b9068d583336a9e46b109c12bb0b24eb66dbeb6ad0a563e"
$actualMariaDbSha256 = (Get-FileHash -LiteralPath $mariaDbInstaller -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualMariaDbSha256 -ne $expectedMariaDbSha256) {
    throw "MariaDB installer checksum mismatch. Expected $expectedMariaDbSha256, got $actualMariaDbSha256."
}

if ($RefreshPrerequisites -or -not (Test-Path -LiteralPath (Join-Path $ch340Dir "CH341SER.INF"))) {
    if (Test-Path -LiteralPath $ch340Dir) {
        Remove-Item -LiteralPath $ch340Dir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $ch340Dir | Out-Null
    & "$env:WINDIR\System32\pnputil.exe" /export-driver oem15.inf $ch340Dir | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Could not export the installed CH340 driver (oem15.inf)."
    }
}

$webViewSignature = Get-AuthenticodeSignature -LiteralPath $webViewInstaller
if ($webViewSignature.Status -ne "Valid") {
    throw "Microsoft WebView2 installer signature is not valid: $($webViewSignature.Status)."
}

$catalog = Get-ChildItem -LiteralPath $ch340Dir -Filter *.cat -Recurse | Select-Object -First 1
if (-not $catalog) {
    throw "CH340 driver catalog was not exported."
}
$driverSignature = Get-AuthenticodeSignature -LiteralPath $catalog.FullName
if ($driverSignature.Status -ne "Valid") {
    throw "CH340 driver catalog signature is not valid: $($driverSignature.Status)."
}

$appExe = Join-Path $projectDir "release\SmartDispenserPerso.exe"
if (-not (Test-Path -LiteralPath $appExe)) {
    throw "Application EXE is missing: $appExe. Run ..\build.ps1 first."
}

$compilerCandidates = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
)
$compiler = $compilerCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $compiler) {
    throw "Inno Setup compiler was not found. Install official Inno Setup 7, then run this script again."
}

& $compiler (Join-Path $installerDir "SmartDispenserPerso.iss")
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compiler failed with exit code $LASTEXITCODE."
}

$setup = Join-Path $outputDir "SmartDispenserPersoSetup.exe"
Write-Host "Built: $setup"
Get-FileHash -LiteralPath $setup -Algorithm SHA256
