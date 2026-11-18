# One-time: submits Shift to winget (the Windows Package Manager).
# Run in PowerShell from this folder:
#   powershell -ExecutionPolicy Bypass -File .\submit-first-version.ps1 -Version 1.4.0
# Later versions are submitted automatically by the release workflow (WINGET_TOKEN secret).
param([string]$Version = "1.4.0")
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$url = "https://github.com/Ambulant-biv/Shift/releases/download/v$Version/ShiftSetup.exe"
$setup = Join-Path $env:TEMP "ShiftSetup-$Version.exe"
Write-Host "Downloading $url ..."
Invoke-WebRequest $url -OutFile $setup
$hash = (Get-FileHash $setup -Algorithm SHA256).Hash

$out = Join-Path $PSScriptRoot "manifests\$Version"
New-Item -ItemType Directory -Force $out | Out-Null
foreach ($template in Get-ChildItem (Join-Path $PSScriptRoot 'templates') -Filter *.yaml) {
    $text = (Get-Content $template.FullName -Raw).Replace('{{VERSION}}', $Version).Replace('{{URL}}', $url).Replace('{{SHA256}}', $hash)
    [IO.File]::WriteAllText((Join-Path $out $template.Name), $text)   # UTF-8 without BOM
}
Write-Host "Manifests written to $out"

winget validate --manifest $out
if ($LASTEXITCODE -ne 0) { throw "The winget manifest is not valid." }

if (-not (Get-Command wingetcreate -ErrorAction SilentlyContinue)) {
    winget install --id Microsoft.WingetCreate -e --accept-source-agreements --accept-package-agreements
    Write-Host "wingetcreate was installed. Close PowerShell, open it again and run this script once more."
    exit 0
}
wingetcreate submit $out
