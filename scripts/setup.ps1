<#
.SYNOPSIS
    Mnemify - one-time setup (Windows). The PowerShell mirror of setup.sh.

.DESCRIPTION
    Installs uv if missing, checks for Node.js 18+, installs the backend,
    builds the web app, creates Desktop and Start Menu shortcuts, and starts
    Mnemify.

    Re-running this script is also how you update: get the new code
    (git pull, or unzip a fresh download over the folder) and run it again.
    Every step is safe to repeat. Your data lives outside this folder.

    Normally you do not run this file directly - double-click setup.bat, which
    calls it with -ExecutionPolicy Bypass for that one process only.

.PARAMETER NoLaunch
    Install, but do not start Mnemify afterwards.

.PARAMETER SkipFrontend
    Skip the web build (developers; needs a frontend\web\dist already).

.PARAMETER RebuildFrontend
    Build the web app even in a release download. Release ZIPs from GitHub
    Releases ship frontend\web\dist already built, marked by
    frontend\web\dist\.mnemify-prebuilt; then Node.js is not needed and
    the npm steps are skipped. A git checkout never has the marker.

.NOTES
    Windows PowerShell 5.1 compatible: no ternaries, no null-coalescing,
    no ForEach-Object -Parallel.
#>
[CmdletBinding()]
param(
    [switch]$NoLaunch,
    [switch]$SkipFrontend,
    [switch]$RebuildFrontend
)

$ErrorActionPreference = 'Stop'
$script:Step = 'startup'

function Write-Step {
    param([string]$Name)
    $script:Step = $Name
    Write-Host ''
    Write-Host ("==> " + $Name)
}

function Stop-Setup {
    param([string]$Message, [string]$Hint)
    Write-Host ''
    Write-Host '---------------------------------------------------------------' -ForegroundColor Red
    Write-Host ("Setup failed during: " + $script:Step) -ForegroundColor Red
    if ($Message) { Write-Host $Message -ForegroundColor Red }
    if ($Hint) { Write-Host ("What to do: " + $Hint) -ForegroundColor Yellow }
    Write-Host '---------------------------------------------------------------' -ForegroundColor Red
    exit 1
}

function Invoke-Step {
    # Run a native command in a directory and fail loudly on a non-zero exit.
    param(
        [string]$Command,
        [string[]]$CmdArgs,
        [string]$WorkDir,
        [string]$Hint
    )
    Push-Location $WorkDir
    try {
        & $Command @CmdArgs
        if ($LASTEXITCODE -ne 0) {
            Stop-Setup ("`"$Command $($CmdArgs -join ' ')`" exited with code $LASTEXITCODE.") $Hint
        }
    } finally {
        Pop-Location
    }
}

function Update-SessionPath {
    # Pick up PATH changes a just-finished installer made, without a new shell.
    # Appended, never replaced: what this process already has on PATH keeps
    # priority (fnm/nvm/Volta node, CI setup-node, ...), and the registry only
    # fills in what is missing. Reading the registry must not be able to stop
    # setup, so it is wrapped.
    $suffix = @()
    foreach ($scope in 'Machine', 'User') {
        try {
            $v = [Environment]::GetEnvironmentVariable('Path', $scope)
        } catch {
            $v = $null
        }
        if ($v) { $suffix += ($v -split ';') }
    }
    $suffix += (Join-Path $env:USERPROFILE '.local\bin')
    $suffix += (Join-Path $env:USERPROFILE '.cargo\bin')
    $suffix += (Join-Path $env:LOCALAPPDATA 'Programs\uv')
    $env:Path = (@($env:Path -split ';') + @($suffix) |
        Where-Object { $_ } |
        Select-Object -Unique) -join ';'
}

if ($PSVersionTable.PSVersion.Major -lt 5) {
    Stop-Setup 'This script needs Windows PowerShell 5.1 or newer.' `
        'Update PowerShell (Windows 10 and 11 ship with 5.1 already), then run setup.bat again.'
}

$NonInteractive = [bool]$env:MNEMIFY_NONINTERACTIVE
if ($NonInteractive) { $NoLaunch = $true }

# ------------------------------------------- 1. work from the repo root always
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

Write-Host 'Mnemify setup'
Write-Host '-------------'
Write-Host ("Folder: " + $Repo)

if (-not (Test-Path (Join-Path $Repo 'backend\pyproject.toml'))) {
    Stop-Setup 'This does not look like a Mnemify checkout.' `
        'Unzip the download first, then run setup.bat from inside the mnemify folder.'
}

# --------------------------------------------------------------------- 2. uv
Write-Step 'installing uv'
if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host ("uv already installed: " + (& uv --version))
} else {
    Write-Host 'uv is not installed. Mnemify uses it to manage Python.'
    Write-Host 'It installs into your user profile - no admin rights, nothing system-wide.'
    if (-not $NonInteractive) {
        Read-Host 'Press Enter to continue, or Ctrl-C to stop and install uv yourself'
    }
    # Two installers, tried in order, because "winget exists" does not mean
    # "winget works": on CI runners and locked-down machines it is present but
    # fails non-interactively (no source agreement, a machine policy, a
    # transient source error). So never branch on winget's *presence* alone -
    # branch on whether uv is on PATH afterwards.
    $uvTried = @()
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host 'Installing with: winget install --id astral-sh.uv -e'
        try {
            & winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements
            if ($LASTEXITCODE -ne 0) {
                $uvTried += ('winget exited with ' + $LASTEXITCODE)
            }
        } catch {
            $uvTried += ('winget failed: ' + $_.Exception.Message)
        }
        Update-SessionPath
    } else {
        $uvTried += 'winget not found'
    }

    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Host ('winget did not give us uv (' + ($uvTried -join '; ') + ').')
        Write-Host 'Falling back to the official installer: https://astral.sh/uv/install.ps1'
        try {
            Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
        } catch {
            $uvTried += ('official installer failed: ' + $_.Exception.Message)
        }
        Update-SessionPath
    }

    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Stop-Setup ('Could not install uv. Tried: ' + ($uvTried -join '; ') + '.') `
            'Install uv yourself (https://docs.astral.sh/uv/getting-started/installation/), then run setup.bat again. If uv IS installed, close this window and open a new terminal so PATH refreshes.'
    }
    Write-Host ("Installed: " + (& uv --version))
}

# A release ZIP ships frontend\web\dist already built, plus a marker file
# naming the version it was built from. Then Node.js is not needed at all.
$prebuilt = ''
$prebuiltMarker = Join-Path $Repo 'frontend\web\dist\.mnemify-prebuilt'
if ((-not $SkipFrontend) -and (-not $RebuildFrontend) -and
    (Test-Path $prebuiltMarker) -and (Test-Path (Join-Path $Repo 'frontend\web\dist\index.html'))) {
    try { $prebuilt = (Get-Content $prebuiltMarker -TotalCount 1).Trim() } catch { $prebuilt = 'unknown' }
    if (-not $prebuilt) { $prebuilt = 'unknown' }
    Write-Host ("Web app: prebuilt (" + $prebuilt + ") - Node.js is not required.")
}

# ------------------------------------------------------------------- 3. Node
Write-Step 'checking Node.js'
if ($prebuilt) {
    Write-Host 'Skipped - the web app is already built.'
} else {
$nodeMajor = 0
$nodeRaw = ''
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if ($nodeCmd) {
    $nodeRaw = & node --version 2>$null
    if ($nodeRaw -match '^v?(\d+)\.') { $nodeMajor = [int]$Matches[1] }
}
if ($nodeMajor -lt 18) {
    if ($nodeMajor -eq 0) {
        Write-Host 'Node.js was not found.' -ForegroundColor Red
    } else {
        Write-Host ("Node.js " + $nodeRaw + " is too old - Mnemify needs 18 or newer.") -ForegroundColor Red
    }
    Write-Host ''
    Write-Host 'Install it, then run setup.bat again:'
    Write-Host '  winget install OpenJS.NodeJS.LTS'
    Write-Host '  or download the LTS installer from https://nodejs.org'
    Write-Host ''
    Write-Host 'We do not install it for you on purpose - system packages are your call.'
    Stop-Setup '' 'Install Node.js 18+ and run setup.bat again.'
}
Write-Host ("Node.js " + $nodeRaw + " - ok.")
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Stop-Setup 'npm was not found.' 'Reinstall Node.js from https://nodejs.org (npm ships with it), then re-run setup.bat.'
}
}

# --------------------------------------------------------------- 4. backend
Write-Step 'installing the backend (uv sync)'
Write-Host 'Creating backend\.venv and installing dependencies. First run takes a minute or two.'
Invoke-Step 'uv' @('sync') (Join-Path $Repo 'backend') `
    'Check the uv output above. A failed download is usually a network or proxy problem - re-run setup.bat.'
Write-Host ("Backend ready: " + (Join-Path $Repo 'backend\.venv'))

# -------------------------------------------------------------- 5. frontend
Write-Step 'building the web app (npm ci && npm run build)'
if ($prebuilt) {
    Write-Host ("Skipped - using the prebuilt web app (" + $prebuilt + "). Pass -RebuildFrontend to build it yourself.")
} elseif ($SkipFrontend) {
    Write-Host 'Skipped (-SkipFrontend).'
} else {
    Write-Host 'Installing web dependencies and building the app.'
    Write-Host 'This is the slow step: roughly 1-3 minutes the first time, and it runs again on every update.'
    $web = Join-Path $Repo 'frontend\web'
    $npmHint = 'Check the npm output above. If it mentions locked files, close any editor or antivirus scan on frontend\web\node_modules, delete that folder, and re-run setup.bat.'
    Invoke-Step 'npm.cmd' @('ci', '--no-audit', '--no-fund') $web $npmHint
    Invoke-Step 'npm.cmd' @('run', 'build') $web $npmHint
    Write-Host ("Web app built: " + (Join-Path $web 'dist'))
}

# --------------------------------------------------------------- 6. launcher
Write-Step 'creating the shortcuts'
try {
    & (Join-Path $PSScriptRoot 'make-launcher.ps1') -RepoRoot $Repo
} catch {
    Write-Host ("Could not create the shortcuts: " + $_.Exception.Message) -ForegroundColor Yellow
    Write-Host 'Not fatal - you can always start Mnemify by double-clicking mnemify.bat.'
}

# ------------------------------------------------------------ 7. done summary
$script:Step = 'printing the summary'
$dataHome = ''
try {
    Push-Location (Join-Path $Repo 'backend')
    $dataHome = & uv run --no-sync python -c "from src import paths; print(paths.describe()['home'])" 2>$null
} catch {
    $dataHome = ''
} finally {
    Pop-Location
}
if (-not $dataHome) { $dataHome = '(run mnemify.bat once to create it)' }

Write-Host ''
Write-Host '---------------------------------------------------------------'
Write-Host 'Done. Mnemify is installed.'
Write-Host ''
Write-Host '  Start    the Mnemify shortcut (Desktop / Start Menu), or: mnemify.bat'
Write-Host '  Fallback cd backend; uv run mnemify up'
Write-Host ("  Data     " + $dataHome)
Write-Host '  Update   get the new code (git pull, or unzip a fresh download), then: setup.bat'
Write-Host '  Stop     Settings -> General -> Quit Mnemify, or: cd backend; uv run mnemify stop'
Write-Host '  Keys     enter them in the app: Settings -> AI & Models, Build -> Sources'
Write-Host '---------------------------------------------------------------'

# ---------------------------------------------------------------- 8. launch
if ($NoLaunch) {
    Write-Host ''
    Write-Host 'Not launching (-NoLaunch). Start it whenever you like.'
    exit 0
}
# Start it detached and hidden, exactly the way the shortcut does. Running it
# in this console instead would pin the server to a window the user is about to
# close - and closing that window would kill Mnemify.
Write-Host ''
Write-Host 'Starting Mnemify. Your browser will open in a moment.'
$logHint = $env:MNEMIFY_LOG_DIR
if (-not $logHint) { $logHint = Join-Path $env:LOCALAPPDATA 'Mnemify\logs' }
Write-Host ("If nothing happens, look in " + (Join-Path $logHint 'launcher.log') + '.')
$pwshExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
# One pre-quoted string, not an array: Start-Process joins array elements
# with spaces and does not quote them, so a repo under "C:\Users\Jane Doe\..."
# would be split at the space and the hidden window would die silently.
# Same shape as the .lnk arguments in make-launcher.ps1.
$launch = Join-Path $PSScriptRoot 'mnemify.ps1'
Start-Process -FilePath $pwshExe -WorkingDirectory $Repo -WindowStyle Hidden -ArgumentList (
    '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $launch + '" -Gui'
)
exit 0
