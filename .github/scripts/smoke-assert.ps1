<#
.SYNOPSIS
    Windows mirror of .github/scripts/smoke-assert.sh.

.DESCRIPTION
    Checks that a freshly-installed Mnemify came up, kept its state where it
    was told to, and can be stopped again. Then stops it.

        $env:MNEMIFY_HOME = "$env:RUNNER_TEMP\mnemify-home"
        $env:MNEMIFY_LAUNCHER_DIR = "$env:RUNNER_TEMP\launchers"
        .\.github\scripts\smoke-assert.ps1 -Port 8789

    Run by .github/workflows/install-smoke.yml after `setup.ps1 -NoLaunch` and
    a backgrounded `mnemify.ps1 -- --no-browser --port <port>`.

.NOTES
    Keep the assertions in step with smoke-assert.sh - they are the same list.
#>
[CmdletBinding()]
param(
    [int]$Port = 8789,
    [string]$Repo
)

$ErrorActionPreference = 'Stop'

if (-not $Repo) { $Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }
$Repo = (Resolve-Path $Repo).Path
$base = "http://127.0.0.1:$Port"

if (-not $env:MNEMIFY_HOME) { throw 'smoke-assert: MNEMIFY_HOME must be set.' }
if (-not $env:MNEMIFY_LAUNCHER_DIR) { throw 'smoke-assert: MNEMIFY_LAUNCHER_DIR must be set.' }

$script:Failures = 0

function Write-Pass { param([string]$M) Write-Host ("  PASS  " + $M) }
function Write-Fail {
    param([string]$M)
    Write-Host ("  FAIL  " + $M) -ForegroundColor Red
    $script:Failures++
}
function Assert-Equal {
    param([string]$What, $Actual, $Expected)
    if ("$Actual" -eq "$Expected") {
        Write-Pass ("$What = $Actual")
    } else {
        Write-Fail ("${What}: expected '$Expected', got '$Actual'")
    }
}
function Write-Section { param([string]$M) Write-Host ''; Write-Host ("== " + $M) }

# Windows paths compare case-insensitively, mix \ and /, and RUNNER_TEMP may
# arrive with a forward slash from the workflow's env block. `paths.home()`
# hands back whatever Path.resolve() produced. Flatten both sides before
# comparing or the prefix check fails for cosmetic reasons.
function ConvertTo-ComparablePath {
    param([string]$P)
    if (-not $P) { return '' }
    return ([System.IO.Path]::GetFullPath($P)).TrimEnd('\', '/').Replace('\', '/').ToLowerInvariant()
}

function Test-ServerUp {
    try {
        $null = Invoke-RestMethod -Uri "$base/api/health" -TimeoutSec 5
        return $true
    } catch {
        return $false
    }
}

# ---------------------------------------------------------------- 1. health
Write-Section "waiting for $base/api/health (up to 60s)"
$health = $null
for ($i = 0; $i -lt 60; $i++) {
    try {
        $health = Invoke-RestMethod -Uri "$base/api/health" -TimeoutSec 5
        if ($health) { break }
    } catch {
        $health = $null
    }
    Start-Sleep -Seconds 1
}
if (-not $health) {
    throw "smoke-assert: the server never answered on $base/api/health after 60s."
}
Write-Host ("Answered after ~" + $i + "s.")
Write-Host ''
$health | ConvertTo-Json -Depth 6 | Write-Host

Write-Section 'health assertions'
Assert-Equal 'ok' $health.ok $true
Assert-Equal 'paths.layout' $health.paths.layout 'env'

$pyproject = Join-Path $Repo 'backend\pyproject.toml'
$match = Select-String -Path $pyproject -Pattern '^version = "([^"]*)"' | Select-Object -First 1
$expectedVersion = ''
if ($match) { $expectedVersion = $match.Matches[0].Groups[1].Value }
Assert-Equal 'version' $health.version $expectedVersion

$homeReal = ConvertTo-ComparablePath $env:MNEMIFY_HOME
$dataDir = ConvertTo-ComparablePath $health.paths.data_dir
if ($dataDir.StartsWith($homeReal + '/')) {
    Write-Pass ("paths.data_dir is under MNEMIFY_HOME (" + $health.paths.data_dir + ")")
} else {
    Write-Fail ("paths.data_dir '$dataDir' is not under MNEMIFY_HOME '$homeReal'")
}

# ------------------------------------------------------------- 2. launcher
# make-launcher.ps1 writes exactly one Mnemify.lnk when MNEMIFY_LAUNCHER_DIR is
# set (Desktop + Start Menu when it is not).
Write-Section 'launcher'
$lnk = Join-Path $env:MNEMIFY_LAUNCHER_DIR 'Mnemify.lnk'
if (Test-Path $lnk) {
    Write-Pass ("shortcut exists: " + $lnk)
    $sc = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
    Write-Host ("        target: " + $sc.TargetPath + " " + $sc.Arguments)
    if ($sc.Arguments -like ("*" + $Repo + "*")) {
        Write-Pass 'shortcut points at this checkout'
    } else {
        Write-Fail ("shortcut arguments do not mention " + $Repo)
    }
} else {
    Write-Fail ("shortcut missing: " + $lnk)
}

# --------------------------------------------------- 3. no writes into cwd
# Any of the three under backend\ would also flip paths.layout() to "legacy"
# on the next run (paths.py _LEGACY_MARKERS).
Write-Section 'nothing written into the checkout'
foreach ($rel in '.mnemify', '.env', 'mnemify.yaml', 'backend\.mnemify', 'backend\.env', 'backend\mnemify.yaml') {
    $stray = Join-Path $Repo $rel
    if (Test-Path $stray) {
        Write-Fail ("created in the checkout: " + $stray)
    } else {
        Write-Pass ("absent: " + $stray)
    }
}

# ------------------------------------------------- 4. runtime files in home
Write-Section 'runtime files under MNEMIFY_HOME'
$pidFile = Join-Path $env:MNEMIFY_HOME 'server.pid'
$portFile = Join-Path $env:MNEMIFY_HOME 'server.port'
if (Test-Path $pidFile) { Write-Pass 'server.pid exists' } else { Write-Fail ("server.pid missing at " + $pidFile) }
if (Test-Path $portFile) {
    Write-Pass 'server.port exists'
    Assert-Equal 'server.port contents' ((Get-Content $portFile -Raw).Trim()) $Port
} else {
    Write-Fail ("server.port missing at " + $portFile)
}

# ------------------------------------------------------------- 5. shutdown
Write-Section 'POST /api/system/shutdown'
$shutdownOk = $false
try {
    $resp = Invoke-RestMethod -Method Post -Uri "$base/api/system/shutdown" `
        -Headers @{ 'X-Mnemify-Client' = 'ci' } `
        -ContentType 'application/json' -Body '{}' -TimeoutSec 10
    Write-Host ($resp | ConvertTo-Json -Compress)
    $shutdownOk = [bool]$resp.ok
} catch {
    Write-Fail ("shutdown request failed: " + $_.Exception.Message)
}
if ($shutdownOk) { Write-Pass 'shutdown accepted (ok = true)' } else { Write-Fail 'shutdown was not accepted' }

Write-Section 'server exit (up to 15s)'
$gone = $false
for ($i = 0; $i -lt 15; $i++) {
    if ((-not (Test-Path $pidFile)) -and (-not (Test-Path $portFile)) -and (-not (Test-ServerUp))) {
        $gone = $true
        break
    }
    Start-Sleep -Seconds 1
}
if ($gone) {
    Write-Pass ("server.pid + server.port removed and the port stopped answering after ~" + $i + "s")
} else {
    Write-Fail 'server did not shut down cleanly within 15s'
    if (Test-Path $pidFile) { Write-Host '        server.pid still present' }
    if (Test-Path $portFile) { Write-Host '        server.port still present' }
    if (Test-ServerUp) { Write-Host ("        still answering on " + $base + "/api/health") }
}

Write-Host ''
if ($script:Failures -eq 0) {
    Write-Host 'smoke-assert: all checks passed.'
    exit 0
}
Write-Host ("smoke-assert: " + $script:Failures + " check(s) failed.") -ForegroundColor Red
exit 1
