[CmdletBinding()]
param([string]$PythonCommand = 'python', [string]$DownloadDir = (Join-Path $env:TEMP 'MemoryShare-Obsidian'))
$ErrorActionPreference = 'Stop'
if ((Test-Path (Join-Path $env:LOCALAPPDATA 'Obsidian\Obsidian.exe')) -or (Test-Path (Join-Path $env:LOCALAPPDATA 'Programs\Obsidian\Obsidian.exe')) -or (Test-Path (Join-Path $env:ProgramFiles 'Obsidian\Obsidian.exe'))) {
    Write-Host 'Existing Obsidian found. Keeping it; verify version in Settings -> About.'
    exit 0
}
$KitDir = Split-Path $PSScriptRoot -Parent
& $PythonCommand (Join-Path $KitDir 'tools\download_obsidian.py') windows --output $DownloadDir
if ($LASTEXITCODE -ne 0) { throw 'Verified download failed.' }
$Manifest = Get-Content -Raw (Join-Path $PSScriptRoot 'obsidian-assets.json') | ConvertFrom-Json
$Installer = Join-Path $DownloadDir $Manifest.assets.windows.filename
# Run the official GUI installer; no undocumented silent-install switch.
$Process = Start-Process -FilePath $Installer -Wait -PassThru
if ($Process.ExitCode -ne 0) { throw "Installer exited with $($Process.ExitCode)" }
Write-Host 'Open Obsidian and choose Open folder as vault. The installer does not authorize OneDrive.'
