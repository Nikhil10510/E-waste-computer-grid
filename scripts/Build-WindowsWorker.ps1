param(
    [Parameter(Mandatory=$true)][string]$NsisCompiler,
    [string]$Python = 'python',
    [string]$OutputDirectory = ''
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$buildPython = Join-Path $projectRoot '.build\package-venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $buildPython)) {
    & $Python -m venv (Join-Path $projectRoot '.build\package-venv')
    if ($LASTEXITCODE -ne 0) { throw 'Build environment creation failed' }
}
& $buildPython -m pip install -r (Join-Path $projectRoot 'packaging\windows\build-requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed' }
$buildArgs = @((Join-Path $projectRoot 'scripts\build_windows_worker.py'), '--nsis', $NsisCompiler)
if ($OutputDirectory) { $buildArgs += @('--output', $OutputDirectory) }
& $buildPython @buildArgs
if ($LASTEXITCODE -ne 0) { throw 'Windows worker build failed' }
