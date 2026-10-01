param([string]$Root=(Split-Path -Parent $MyInvocation.MyCommand.Path),[string]$DatabaseRootPassword,[string]$OperatorPin='202610')
$ErrorActionPreference='Stop'; $app=Join-Path $Root 'windows_topup'; $pre=Join-Path $app 'installer\prerequisites'
if(-not $DatabaseRootPassword){$DatabaseRootPassword=Read-Host 'Password root MariaDB (Enter jika kosong)'}
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $app 'installer\install_prerequisites.ps1') -WebViewInstaller (Join-Path $pre 'MicrosoftEdgeWebView2RuntimeInstallerX64.exe') -DriverInf (Join-Path $pre 'ch340\CH341SER.INF') -SuccessMarker (Join-Path $env:TEMP 'sd-topup-ready.marker')
if(-not (Get-Service -Name SmartDispenserMariaDB,MariaDB,mysql -ErrorAction SilentlyContinue)) { $msi=Join-Path $pre 'mariadb-11.8.9-winx64.msi'; Start-Process msiexec.exe -ArgumentList "/i `"$msi`" /qn /norestart PASSWORD=`"$DatabaseRootPassword`" SERVICENAME=SmartDispenserMariaDB PORT=3306 ADDLOCAL=DBInstance,Client,MYSQLSERVER,SharedLibraries REMOVE=DEVEL,HeidiSQL" -Wait }
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $app 'installer\configure_database.ps1') -SchemaPath (Join-Path $app 'schema.sql') -AdminPassword $DatabaseRootPassword -OperatorPin $OperatorPin
& py -3.12 -m pip install -r (Join-Path $app 'requirements.txt')
Write-Host 'Topup selesai disiapkan. Jalankan: py -3.12 app_perso_style.py' -ForegroundColor Green
