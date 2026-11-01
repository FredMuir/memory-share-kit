[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$')][string]$Device,
    [Parameter(Mandatory=$true)][string]$Vault,
    [string]$PythonCommand = 'python',
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'MemoryShare')
)
$ErrorActionPreference = 'Stop'
$KitDir = Split-Path $PSScriptRoot -Parent
if (-not [IO.Path]::IsPathRooted($Vault)) { throw 'Vault must be an absolute path.' }
& $PythonCommand -c 'import sys; assert sys.version_info >= (3,11)'
if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11+ first.' }
$Venv = Join-Path $InstallRoot 'venv'
if (Test-Path $Venv) { throw 'Existing installation found; use the documented upgrade procedure.' }
New-Item -ItemType Directory -Force $InstallRoot | Out-Null
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls.exe $InstallRoot /inheritance:r /grant:r "${Identity}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not restrict private state ACL.' }
& $PythonCommand -m venv $Venv
if ($LASTEXITCODE -ne 0) { throw 'venv failed' }
$Python = Join-Path $Venv 'Scripts\python.exe'
& $Python -m pip install -r (Join-Path $KitDir 'requirements.lock')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& $Python -m pip install --no-deps (Join-Path $KitDir 'dist\memory_share_kit-0.1.2-py3-none-any.whl')
if ($LASTEXITCODE -ne 0) { throw 'Package installation failed' }
if (-not (Test-Path (Join-Path $InstallRoot 'client.json'))) {
    & $Python -m memory_share --state $InstallRoot init --device $Device --vault $Vault
    if ($LASTEXITCODE -ne 0) { throw 'Initialization failed' }
}
& $Python -m memory_share --state $InstallRoot snippets
if ($LASTEXITCODE -ne 0) { throw 'Configuration generation failed' }
& $Python (Join-Path $KitDir 'tools\autostart.py') --state $InstallRoot --output (Join-Path $InstallRoot 'autostart')
if ($LASTEXITCODE -ne 0) { throw 'Autostart template generation failed' }
Write-Host "Installed. Python executable: $Python"
Write-Host "Private state: $InstallRoot"
Write-Host 'Next: configure token, merge MCP snippets, exclude generated folder in Remotely Save.'
