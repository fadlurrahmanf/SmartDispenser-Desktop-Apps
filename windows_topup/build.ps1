param(
    [string]$OutputDir = 'release'
)

$ErrorActionPreference = 'Stop'

$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = 'C:\Users\MSI\AppData\Local\Programs\Python\Python312\python.exe'

& $python (Join-Path $project 'tools\build_startup_html.py')
if ($LASTEXITCODE -ne 0) {
    throw "Pembuatan startup HTML gagal dengan exit code $LASTEXITCODE."
}
& $python -m py_compile `
    (Join-Path $project 'functional_web_startup.py') `
    (Join-Path $project 'app_perso_style.py') `
    (Join-Path $project 'topup_core.py')
& $python -m PyInstaller --noconfirm --clean `
    --distpath (Join-Path $project $OutputDir) `
    --workpath (Join-Path $project 'build_release') `
    (Join-Path $project 'SmartDispenserTopup.spec')
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller gagal dengan exit code $LASTEXITCODE."
}

$outputRoot = Join-Path $project $OutputDir
$output = Join-Path $outputRoot 'SmartDispenserTopup.exe'
if (-not (Test-Path -LiteralPath $output)) {
    throw "EXE tidak ditemukan setelah build: $output"
}
$provisioning = Join-Path $project 'topup.provisioning.json'
if (Test-Path -LiteralPath $provisioning) {
    Copy-Item -LiteralPath $provisioning -Destination (Join-Path $outputRoot 'topup.provisioning.json') -Force
}
Write-Host "Built: $output"
Get-Item -LiteralPath $output | Select-Object FullName,Length,LastWriteTime
