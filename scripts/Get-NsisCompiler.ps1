param()
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$toolsDirectory = [IO.Path]::GetFullPath((Join-Path $projectRoot '.build\tools'))
if (-not $toolsDirectory.StartsWith($projectRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Compiler location must stay within this workspace'
}
New-Item -ItemType Directory -Path $toolsDirectory -Force | Out-Null
$archivePath = Join-Path $toolsDirectory 'nsis-3.13.zip'
$archiveHash = 'BA63DFFC4410EE89193E1CB5A41989991BD77C61068DA17E3156D136B7B0B3D8'
if (-not (Test-Path -LiteralPath $archivePath)) {
    Invoke-WebRequest 'https://netix.dl.sourceforge.net/project/nsis/NSIS%203/3.13/nsis-3.13.zip' -OutFile $archivePath
}
if ((Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash -ne $archiveHash) {
    throw 'NSIS archive checksum mismatch; no compiler files were extracted'
}
Expand-Archive -LiteralPath $archivePath -DestinationPath $toolsDirectory -Force
$compilerPath = Join-Path $toolsDirectory 'nsis-3.13\makensis.exe'
if ((Get-FileHash -LiteralPath $compilerPath -Algorithm SHA256).Hash -ne '4EC390D0F96F9728507FBC2F4E91311DD90BFC6C8DDFE2159357B3651AE151C0') {
    throw 'NSIS compiler checksum mismatch'
}
Write-Output $compilerPath
