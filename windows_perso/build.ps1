$ErrorActionPreference = 'Stop'

$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = 'C:\Users\MSI\AppData\Local\Programs\Python\Python312\python.exe'

& $python (Join-Path $project 'tools\build_functional_html.py')
& $python -m PyInstaller --noconfirm --clean `
    --distpath (Join-Path $project 'release_v105') `
    --workpath (Join-Path $project 'build_v105') `
    (Join-Path $project 'SmartDispenserPerso.spec')

Write-Host "Built: $(Join-Path $project 'release_v105\SmartDispenserPerso\SmartDispenserPerso.exe')"
