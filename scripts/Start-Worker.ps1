[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ControlPlaneUrl,
    [ValidateSet('docker','native')][string]$ExecutionMode = 'docker',
    [string]$WorkerName = $env:COMPUTERNAME,
    [string]$PythonPath,
    [string]$StateDirectory,
    [switch]$Once
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $PythonPath) { $PythonPath = Join-Path $projectRoot '.venv-local\Scripts\python.exe' }
if (-not $StateDirectory) { $StateDirectory = Join-Path $projectRoot 'worker\.worker_data' }
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw 'Create a fresh Python 3.12 .venv-local first; see README.md. A copied virtual environment is not portable.'
}
$api = $null
if (-not [Uri]::TryCreate($ControlPlaneUrl, [UriKind]::Absolute, [ref]$api) -or
    $api.Scheme -notin @('http','https') -or $api.AbsolutePath.TrimEnd('/') -ne '/api' -or
    $api.Query -or $api.Fragment -or $api.UserInfo) {
    throw 'ControlPlaneUrl must be an absolute HTTP(S) URL ending in /api, without credentials, query or fragment.'
}
$apiBase = $ControlPlaneUrl.TrimEnd('/')
$health = Invoke-RestMethod -Uri "$apiBase/health" -TimeoutSec 10
if ($health.status -ne 'ok') { throw 'The selected API is not healthy; check backend/database connectivity.' }

# Set explicit per-process configuration instead of inheriting stale worker/.env
# paths or localhost from another machine. Never print enrollment credentials.
$values = @{
    CONTROL_PLANE_URL = $apiBase
    EXECUTION_MODE = $ExecutionMode
    WORKER_NAME = $WorkerName
    DATA_DIR = [IO.Path]::GetFullPath($StateDirectory)
    TEMP_EXEC_DIR = [IO.Path]::GetFullPath("$StateDirectory-tasks")
}
$previous = @{}
foreach ($name in $values.Keys) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    [Environment]::SetEnvironmentVariable($name, $values[$name], 'Process')
}
try {
    & $PythonPath (Join-Path $projectRoot 'worker\agent.py') --preflight
    if ($LASTEXITCODE -ne 0) { throw 'Runtime preflight failed; fix the reported error before enrollment.' }
    $arguments = @((Join-Path $projectRoot 'worker\agent.py'))
    if ($Once) { $arguments += '--once' }
    & $PythonPath @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Worker stopped with an error; inspect the worker log.' }
} finally {
    foreach ($name in $values.Keys) { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
}
