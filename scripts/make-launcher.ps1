<#
.SYNOPSIS
    Create the Mnemify shortcuts (Windows).

.DESCRIPTION
    Writes Mnemify.lnk to the Desktop and to the Start Menu's Programs folder.
    Set MNEMIFY_LAUNCHER_DIR to write a single shortcut somewhere else instead.

    The shortcut hardcodes the absolute path of this checkout. If you move or
    rename the folder, run setup.bat again from the new location to rewrite it.

    Safe to run repeatedly: it overwrites what is already there.

.NOTES
    Windows PowerShell 5.1 compatible.
#>
[CmdletBinding()]
param(
    [string]$RepoRoot
)

$ErrorActionPreference = 'Stop'

if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
$RepoRoot = (Resolve-Path $RepoRoot).Path

if (-not (Test-Path (Join-Path $RepoRoot 'scripts\mnemify.ps1'))) {
    throw "$RepoRoot does not look like a Mnemify checkout."
}

$target = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$launch = Join-Path $RepoRoot 'scripts\mnemify.ps1'
$icon = Join-Path $RepoRoot 'assets\icons\mnemify.ico'

$destDirs = @()
if ($env:MNEMIFY_LAUNCHER_DIR) {
    $destDirs += $env:MNEMIFY_LAUNCHER_DIR
} else {
    $destDirs += [Environment]::GetFolderPath('Desktop')
    $destDirs += [Environment]::GetFolderPath('Programs')
}

$shell = New-Object -ComObject WScript.Shell
foreach ($dir in $destDirs) {
    if (-not $dir) { continue }
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $lnk = Join-Path $dir 'Mnemify.lnk'
    $sc = $shell.CreateShortcut($lnk)
    $sc.TargetPath = $target
    $sc.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $launch + '" -Gui'
    $sc.WorkingDirectory = $RepoRoot
    $sc.Description = 'Mnemify - your knowledge, as a world you can explore'
    $sc.WindowStyle = 7
    if (Test-Path $icon) { $sc.IconLocation = $icon + ',0' }
    $sc.Save()
    Write-Host ("Shortcut: " + $lnk)
}
Write-Host 'Start Mnemify from the Desktop icon or the Start Menu.'
