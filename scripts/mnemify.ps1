<#
.SYNOPSIS
    Mnemify - start the app (Windows). This is what the shortcut runs.

.DESCRIPTION
    Deliberately dumb: no git, no network, no updates. It resolves a usable
    PATH, checks that setup has been run, and hands over to the server. The
    server owns everything else - picking a port, noticing it is already
    running, opening the browser, and shutting itself down when idle.

    Anything you pass that is not -Gui goes straight to `mnemify up`, e.g.
        powershell -File scripts\mnemify.ps1 --no-browser --port 8793
        mnemify.bat --no-browser --port 8793

    Pass the server's flags directly - do NOT put a `--` in front of them.
    PowerShell's `-File` hands `--` to the script as a parameter token with an
    empty name, and the binder rejects it ("the parameter name '' is
    ambiguous") before this script's body ever runs. `--no-browser` and
    `--port` bind cleanly on their own: a token starting with `--` is not a
    parameter name, so $ServerArgs collects them. mnemify.bat therefore
    forwards %* verbatim, with nothing inserted.

.PARAMETER Gui
    Log everything to a file and report failures in a message box instead of
    on a console nobody is looking at. The shortcut uses this together with
    -WindowStyle Hidden.

.NOTES
    Windows PowerShell 5.1 compatible. Must work with -WindowStyle Hidden,
    where there is no console to write to at all.
#>
[CmdletBinding()]
param(
    [switch]$Gui,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ServerArgs
)

$ErrorActionPreference = 'Stop'

$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

# ------------------------------------------------------------------- PATH
# A process started from a shortcut inherits a minimal environment - none of
# the places uv, node or the `claude` CLI actually live. Put them back.
$extraPaths = @(
    (Join-Path $env:USERPROFILE '.local\bin'),
    (Join-Path $env:USERPROFILE '.cargo\bin'),
    (Join-Path $env:LOCALAPPDATA 'Programs\uv'),
    (Join-Path $env:APPDATA 'npm'),
    (Join-Path $env:LOCALAPPDATA 'Programs\nodejs'),
    (Join-Path $env:ProgramFiles 'nodejs'),
    (Join-Path $env:USERPROFILE '.volta\bin'),
    (Join-Path $env:APPDATA 'fnm'),
    (Join-Path $env:LOCALAPPDATA 'fnm_multishells')
)
$prefix = @()
foreach ($p in $extraPaths) {
    if ($p -and (Test-Path $p)) { $prefix += $p }
}
if ($prefix.Count -gt 0) {
    $env:Path = ($prefix -join ';') + ';' + $env:Path
}

# ------------------------------------------------------------------ logging
$logFile = $null
if ($Gui) {
    $logDir = $env:MNEMIFY_LOG_DIR
    if (-not $logDir) { $logDir = Join-Path $env:LOCALAPPDATA 'Mnemify\logs' }
    try {
        if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
        $logFile = Join-Path $logDir 'launcher.log'
        # Keep one generation, so the log cannot grow without bound.
        if ((Test-Path $logFile) -and ((Get-Item $logFile).Length -gt 1MB)) {
            Move-Item -Force $logFile ($logFile + '.1')
        }
        $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        Add-Content -Path $logFile -Value ''
        Add-Content -Path $logFile -Value ("===== " + $stamp + " : starting Mnemify from " + $Repo + " =====")
    } catch {
        $logFile = $null
    }
}

function Write-LauncherLog {
    param([string]$Message)
    if ($logFile) {
        # Logging must never be the thing that kills the launcher.
        try { Add-Content -Path $logFile -Value $Message } catch { $null = $_ }
    } else {
        Write-Host $Message
    }
}

# ------------------------------------------------------------------ errors
# Set MNEMIFY_DIALOG_DRYRUN=1 to log the message box instead of showing it.
function Show-Failure {
    param([string]$Message)
    Write-LauncherLog $Message
    if (-not $Gui) {
        Write-Host $Message -ForegroundColor Red
        return
    }
    if ($env:MNEMIFY_DIALOG_DRYRUN) {
        Write-LauncherLog ("[dialog dry-run] MessageBox: " + $Message)
        return
    }
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show(
            $Message, 'Mnemify',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
    } catch {
        Write-LauncherLog ("Could not show a dialog: " + $_.Exception.Message)
    }
}

function Get-WhereToLook {
    if ($logFile) { return "See $logFile" }
    return "Run mnemify.bat from a terminal to see why."
}

# ------------------------------------------------------------ sanity checks
if (-not (Test-Path (Join-Path $Repo 'backend\.venv'))) {
    Show-Failure ("Mnemify is not installed yet. Run setup.bat in " + $Repo + " first.")
    exit 1
}
if ((-not $env:MNEMIFY_WEB_DIST) -and (-not (Test-Path (Join-Path $Repo 'frontend\web\dist')))) {
    Show-Failure ("The Mnemify web app has not been built. Run setup.bat in " + $Repo + " first.")
    exit 1
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Show-Failure ("Could not find uv. Run setup.bat in " + $Repo + " first. " + (Get-WhereToLook))
    exit 1
}

# ------------------------------------------------------------------- start
Set-Location (Join-Path $Repo 'backend')

$upArgs = @('run', '--no-sync', 'mnemify', 'up')
if ($ServerArgs) {
    # Belt and braces: a caller (or a host that passes `--` through instead of
    # rejecting it) must not turn into `mnemify up -- --no-browser`.
    $upArgs += @($ServerArgs | Where-Object { $_ -ne '--' })
}

if ($Gui -and $logFile) {
    & uv @upArgs 2>&1 | Out-File -FilePath $logFile -Append -Encoding utf8
} else {
    & uv @upArgs
}
$status = $LASTEXITCODE
if ($null -eq $status) { $status = 0 }

# 130 = SIGINT, 143 = SIGTERM: somebody stopped the server on purpose. That is
# not a failure worth a dialog.
if (($status -ne 0) -and ($status -ne 130) -and ($status -ne 143)) {
    Show-Failure ("Mnemify failed to start. " + (Get-WhereToLook))
}
exit $status
