# Downloads GNU LibreDWG (GPLv3) and puts dxf2dwg.exe in tools\libredwg,
# so Shift can save DWG files without users installing anything.
# Used by build_and_install.bat and by the GitHub release workflow.
$ErrorActionPreference = 'Stop'
$version = '0.13.3'
$sha256  = 'b5133f8b6bd71b7e682a06ef5f99c93b40d628a791c30a31924a80d258c87173'
$url     = "https://github.com/LibreDWG/libredwg/releases/download/$version/libredwg-$version-win64.zip"

$root   = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Join-Path $root 'tools\libredwg'
if (Test-Path (Join-Path $target 'dxf2dwg.exe')) {
    Write-Host "LibreDWG is already present."
    exit 0
}

$ProgressPreference = 'SilentlyContinue'
$zip = Join-Path $env:TEMP "libredwg-$version-win64.zip"
Invoke-WebRequest $url -OutFile $zip
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
if ($hash -ne $sha256) { throw "Checksum mismatch for the LibreDWG download ($hash)" }

$unpacked = Join-Path $env:TEMP "libredwg-$version"
if (Test-Path $unpacked) { Remove-Item $unpacked -Recurse -Force }
Expand-Archive $zip -DestinationPath $unpacked
New-Item -ItemType Directory -Force $target | Out-Null
foreach ($name in 'dxf2dwg.exe', 'libredwg-0.dll', 'README.txt') {
    $file = Get-ChildItem $unpacked -Recurse -Filter $name | Select-Object -First 1
    if (-not $file) { throw "$name not found in the LibreDWG package" }
    Copy-Item $file.FullName $target
}
Copy-Item (Join-Path $root 'licenses\LibreDWG-COPYING.txt') $target
Write-Host "LibreDWG $version is ready in $target"
