[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$WebViewInstaller,

    [Parameter(Mandatory = $true)]
    [string]$DriverInf,

    [Parameter(Mandatory = $true)]
    [string]$SuccessMarker
)

$ErrorActionPreference = "Stop"

if (Test-Path -LiteralPath $SuccessMarker) {
    Remove-Item -LiteralPath $SuccessMarker -Force
}

if (-not (Test-Path -LiteralPath $WebViewInstaller)) {
    throw "WebView2 installer was not found."
}
if (-not (Test-Path -LiteralPath $DriverInf)) {
    throw "CH340 driver INF was not found."
}

$webViewRoots = @(
    (Join-Path ${env:ProgramFiles(x86)} "Microsoft\EdgeWebView\Application"),
    (Join-Path ${env:ProgramFiles} "Microsoft\EdgeWebView\Application")
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
function Find-WebViewRuntime {
    return $(foreach ($root in $webViewRoots) {
        Get-ChildItem -LiteralPath $root -Filter "msedgewebview2.exe" -Recurse -ErrorAction SilentlyContinue
    }) | Select-Object -First 1
}

$webViewReady = Find-WebViewRuntime
if (-not $webViewReady) {
    $webViewProcess = Start-Process -FilePath $WebViewInstaller -ArgumentList "/silent", "/install" -PassThru -WindowStyle Hidden
    if (-not $webViewProcess.WaitForExit(120000)) {
        $webViewProcess.Kill()
        throw "Microsoft Edge WebView2 Runtime installation timed out."
    }
    $webViewReady = Find-WebViewRuntime
}
if (-not $webViewReady) {
    throw "Microsoft Edge WebView2 Runtime verification failed."
}

$driverProcess = Start-Process -FilePath "$env:WINDIR\System32\pnputil.exe" -ArgumentList "/add-driver", "`"$DriverInf`"", "/install" -Wait -PassThru -WindowStyle Hidden
$driverInventory = (& "$env:WINDIR\System32\pnputil.exe" /enum-drivers 2>&1) -join "`n"
if ($driverInventory -notmatch "(?im)^Original Name:\s*ch341ser\.inf\s*$") {
    throw "CH340 driver verification failed (pnputil exit code $($driverProcess.ExitCode))."
}

[IO.File]::WriteAllText($SuccessMarker, "prerequisites-ready", [Text.UTF8Encoding]::new($false))
