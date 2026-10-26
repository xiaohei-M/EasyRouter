# Build EasyRouter application update package (application only)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$out = Join-Path $root "EasyRouter-update.zip"
if (Test-Path $out) { Remove-Item $out -Force }
Compress-Archive -Path @("easyrouter", "VERSION") -DestinationPath $out -Force
Write-Host "Created: $out"
Write-Host "Upload this ZIP in System -> Upgrade."
