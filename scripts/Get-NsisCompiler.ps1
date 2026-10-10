param([string]$ToolsDirectory = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $ToolsDirectory) { $ToolsDirectory = Join-Path $projectRoot '.build\tools' }
$toolsDirectory = [IO.Path]::GetFullPath($ToolsDirectory)
if (-not $toolsDirectory.StartsWith($projectRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Compiler location must stay within this workspace'
}
New-Item -ItemType Directory -Path $toolsDirectory -Force | Out-Null
$archivePath = Join-Path $toolsDirectory 'nsis-3.13.zip'
$archiveHash = 'BA63DFFC4410EE89193E1CB5A41989991BD77C61068DA17E3156D136B7B0B3D8'
function Test-NsisArchive([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    $stream = [IO.File]::OpenRead($Path)
    try {
        # Reject a successful HTTP response containing an HTML download page.
        if ($stream.Length -lt 4 -or $stream.ReadByte() -ne 80 -or $stream.ReadByte() -ne 75 -or
            $stream.ReadByte() -ne 3 -or $stream.ReadByte() -ne 4) { return $false }
    } finally { $stream.Dispose() }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -eq $archiveHash
}
if (-not (Test-NsisArchive $archivePath)) {
    $sources = @(
        'https://netix.dl.sourceforge.net/project/nsis/NSIS%203/3.13/nsis-3.13.zip?download=1',
        'https://downloads.sourceforge.net/project/nsis/NSIS%203/3.13/nsis-3.13.zip?download=1',
        'https://phoenixnap.dl.sourceforge.net/project/nsis/NSIS%203/3.13/nsis-3.13.zip?download=1'
    )
    $downloadPath = Join-Path $toolsDirectory ('nsis-3.13-' + [guid]::NewGuid().ToString('N') + '.download')
    try {
        :attempts for ($attempt = 1; $attempt -le 2; $attempt++) {
            foreach ($source in $sources) {
                try {
                    $request = @{OutFile=$downloadPath; TimeoutSec=30; UserAgent='E-Waste-Grid-Build/1.0'}
                    Invoke-WebRequest -Uri $source @request
                    if (-not (Test-NsisArchive $downloadPath) -and (Get-Item -LiteralPath $downloadPath).Length -lt 1048576) {
                        # SourceForge may return HTTP 200 with a meta-refresh page.
                        # Follow only its official link for this exact pinned file.
                        $html = [IO.File]::ReadAllText($downloadPath)
                        $link = [regex]::Match($html, 'https://downloads\.sourceforge\.net/project/nsis/NSIS%203/3\.13/nsis-3\.13\.zip\?[^"<>\s]+')
                        if ($link.Success) {
                            $next = [uri][Net.WebUtility]::HtmlDecode($link.Value)
                            if ($next.Scheme -eq 'https' -and $next.Host -eq 'downloads.sourceforge.net' -and
                                $next.AbsolutePath -eq '/project/nsis/NSIS%203/3.13/nsis-3.13.zip') {
                                Invoke-WebRequest -Uri $next @request
                            }
                        }
                    }
                    if (Test-NsisArchive $downloadPath) {
                        Move-Item -LiteralPath $downloadPath -Destination $archivePath -Force
                        break attempts
                    }
                    Write-Warning "NSIS mirror $(([uri]$source).Host) returned an invalid archive (attempt $attempt); trying another source."
                } catch {
                    Write-Warning "NSIS mirror $(([uri]$source).Host) could not supply the archive (attempt $attempt); trying another source."
                }
            }
            if ($attempt -lt 2) { Start-Sleep -Seconds 1 }
        }
    } finally {
        if (Test-Path -LiteralPath $downloadPath) { Remove-Item -LiteralPath $downloadPath -Force }
    }
    if (-not (Test-NsisArchive $archivePath)) {
        throw 'No verified NSIS 3.13 ZIP was available after bounded retries; no compiler files were extracted.'
    }
}
Expand-Archive -LiteralPath $archivePath -DestinationPath $toolsDirectory -Force
$compilerPath = Join-Path $toolsDirectory 'nsis-3.13\makensis.exe'
if ((Get-FileHash -LiteralPath $compilerPath -Algorithm SHA256).Hash -ne '4EC390D0F96F9728507FBC2F4E91311DD90BFC6C8DDFE2159357B3651AE151C0') {
    throw 'NSIS compiler checksum mismatch'
}
Write-Output $compilerPath
