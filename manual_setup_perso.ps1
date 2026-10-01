param([string]$Root=(Split-Path -Parent $MyInvocation.MyCommand.Path),[string]$DatabaseRootPassword)
$ErrorActionPreference='Stop'; $app=Join-Path $Root 'windows_perso'; $pre=Join-Path $app 'installer\prerequisites'
if(-not $DatabaseRootPassword){$DatabaseRootPassword=Read-Host 'Password root MariaDB (Enter jika kosong)'}
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $app 'installer\install_prerequisites.ps1') -WebViewInstaller (Join-Path $pre 'MicrosoftEdgeWebView2RuntimeInstallerX64.exe') -DriverInf (Join-Path $pre 'ch340\CH341SER.INF') -SuccessMarker (Join-Path $env:TEMP 'sd-perso-ready.marker')
if(-not (Get-Service -Name SmartDispenserMariaDB,MariaDB,mysql -ErrorAction SilentlyContinue)) { $msi=Join-Path $pre 'mariadb-11.8.9-winx64.msi'; Start-Process msiexec.exe -ArgumentList "/i `"$msi`" /qn /norestart PASSWORD=`"$DatabaseRootPassword`" SERVICENAME=SmartDispenserMariaDB PORT=3306 ADDLOCAL=DBInstance,Client,MYSQLSERVER,SharedLibraries REMOVE=DEVEL,HeidiSQL" -Wait }
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $app 'installer\configure_database.ps1') -AdminPassword $DatabaseRootPassword
& py -3.12 -m pip install -r (Join-Path $app 'requirements.txt')
Write-Host 'Perso selesai disiapkan. Jalankan: py -3.12 functional_web_app.py' -ForegroundColor Green
