param([Parameter(Mandatory=$true)][string]$FixtureArchive)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$downloader = Join-Path $projectRoot 'scripts\Get-NsisCompiler.ps1'
$global:nsisFixtureArchive = [IO.Path]::GetFullPath($FixtureArchive)
if ((Get-FileHash -LiteralPath $global:nsisFixtureArchive -Algorithm SHA256).Hash -ne 'BA63DFFC4410EE89193E1CB5A41989991BD77C61068DA17E3156D136B7B0B3D8') {
    throw 'Tests require the genuine pinned NSIS ZIP, not an executable mock.'
}
$testRoot = Join-Path $projectRoot ('.build\nsis-regression-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
function Assert([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function Invoke-WebRequest {
    param($Uri, $OutFile, $TimeoutSec, $UserAgent)
    $global:nsisFixtureCalls++
    $global:nsisFixtureLastUri = [string]$Uri
    switch ($global:nsisFixtureMode) {
        'offline' { throw 'Simulated network outage' }
        'invalid' { [IO.File]::WriteAllText($OutFile, '<html>Unexpected download page</html>'); return }
        'html-link' {
            if ($global:nsisFixtureCalls -eq 1) {
                [IO.File]::WriteAllText($OutFile, '<meta http-equiv="refresh" content="5; url=https://downloads.sourceforge.net/project/nsis/NSIS%203/3.13/nsis-3.13.zip?ts=fixture&amp;r=">')
                return
            }
        }
        'fallback' {
            if ($global:nsisFixtureCalls -eq 1) {
                [IO.File]::WriteAllBytes($OutFile, [byte[]](80,75,3,4,0,1,2,3))
                return
            }
        }
        'foreign-link' {
            [IO.File]::WriteAllText($OutFile, '<meta http-equiv="refresh" content="5; url=https://example.invalid/nsis-3.13.zip">')
            return
        }
    }
    Copy-Item -LiteralPath $global:nsisFixtureArchive -Destination $OutFile
}
function Start-Sleep { param($Seconds) } # No actual waiting in simulated failures.
function Run-Success([string]$Case, [string]$Mode, [int]$ExpectedCalls, [string]$Cached = '') {
    $directory = Join-Path $testRoot $Case
    New-Item -ItemType Directory -Path $directory | Out-Null
    if ($Cached -eq 'valid') { Copy-Item -LiteralPath $global:nsisFixtureArchive -Destination (Join-Path $directory 'nsis-3.13.zip') }
    if ($Cached -eq 'invalid') { [IO.File]::WriteAllText((Join-Path $directory 'nsis-3.13.zip'), '<html>Failed earlier download</html>') }
    $global:nsisFixtureCalls = 0; $global:nsisFixtureMode = $Mode
    $compiler = & $downloader -ToolsDirectory $directory -WarningAction SilentlyContinue
    Assert ($global:nsisFixtureCalls -eq $ExpectedCalls) "$Case made unexpected download requests"
    Assert (Test-Path -LiteralPath $compiler -PathType Leaf) "$Case did not extract the real compiler"
    Assert ((Get-FileHash -LiteralPath $compiler -Algorithm SHA256).Hash -eq '4EC390D0F96F9728507FBC2F4E91311DD90BFC6C8DDFE2159357B3651AE151C0') "$Case lost compiler verification"
    Assert (@(Get-ChildItem -LiteralPath $directory -Filter '*.download').Count -eq 0) "$Case left a partial download"
    Write-Host "PASS $Case"
}
Run-Success 'valid-cache' 'offline' 0 'valid'
Run-Success 'corrupt-cache-recovery' 'valid' 1 'invalid'
Run-Success 'html-refresh' 'html-link' 2
Assert ($global:nsisFixtureLastUri.Contains('&r=') -and -not $global:nsisFixtureLastUri.Contains('&amp;')) 'HTML entities were not decoded'
Run-Success 'bad-zip-mirror-fallback' 'fallback' 2
foreach ($mode in @('invalid', 'offline', 'foreign-link')) {
    $directory = Join-Path $testRoot $mode
    $global:nsisFixtureCalls = 0; $global:nsisFixtureMode = $mode
    $failed = $false
    try { & $downloader -ToolsDirectory $directory -WarningAction SilentlyContinue | Out-Null }
    catch { $failed = $_.Exception.Message -like 'No verified NSIS*' }
    Assert $failed "$mode must fail closed"
    Assert ($global:nsisFixtureCalls -eq 6) "$mode did not enforce bounded retries"
    Assert (-not (Test-Path -LiteralPath (Join-Path $directory 'nsis-3.13\makensis.exe'))) "$mode extracted unverified content"
    Assert (@(Get-ChildItem -LiteralPath $directory -Filter '*.download').Count -eq 0) "$mode left a partial download"
    Write-Host "PASS $mode refuses extraction"
}
Write-Host 'PASS 7 NSIS downloader regression cases'
