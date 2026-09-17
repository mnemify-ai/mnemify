<#
    Mnemify - one-line installer for Windows.

        irm https://raw.githubusercontent.com/mnemify-ai/mnemify/main/scripts/install.ps1 | iex

    It clones (or updates) the repo into $HOME\Mnemify and runs setup there.
    Set $env:MNEMIFY_INSTALL_DIR first to put it somewhere else.

    Re-running this one-liner is the manual update path: if the folder already
    exists it does a fast-forward `git pull` and re-runs setup, which rebuilds
    the backend and the web app. Your harvested and compiled data lives outside
    the folder, so nothing here can touch it.

    This file is executed by `iex` with no file on disk, so it must never look
    at $MyInvocation.MyCommand.Path and must not declare a param() block.
    Configure it through environment variables only.
#>

$ErrorActionPreference = 'Stop'

$repoUrl = $env:MNEMIFY_REPO_URL
if (-not $repoUrl) { $repoUrl = 'https://github.com/mnemify-ai/mnemify' }
$dest = $env:MNEMIFY_INSTALL_DIR
if (-not $dest) { $dest = Join-Path $HOME 'Mnemify' }

Write-Host 'Mnemify installer'
Write-Host ("Source: " + $repoUrl)
Write-Host ("Folder: " + $dest)
Write-Host ''

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host 'git is required and was not found.' -ForegroundColor Red
    Write-Host 'Install it with:  winget install Git.Git'
    Write-Host '  or download it from https://git-scm.com/download/win'
    Write-Host ''
    Write-Host 'No git? Download the ZIP instead:'
    Write-Host ("  " + $repoUrl + "/archive/refs/heads/main.zip")
    Write-Host '  unzip it, then double-click setup.bat'
    exit 1
}

if (Test-Path (Join-Path $dest '.git')) {
    Write-Host 'Already installed - updating to the latest code.'
    & git -C $dest pull --ff-only
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'git pull failed. Resolve it in that folder, then re-run.' -ForegroundColor Red
        exit 1
    }
} elseif (Test-Path $dest) {
    Write-Host ($dest + ' already exists and is not a git checkout.') -ForegroundColor Red
    Write-Host 'Move it aside, or set $env:MNEMIFY_INSTALL_DIR to another folder, then try again.'
    exit 1
} else {
    & git clone $repoUrl $dest
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'git clone failed.' -ForegroundColor Red
        exit 1
    }
}

Write-Host ''
Write-Host 'Running setup.'
Write-Host ''
& (Join-Path $dest 'scripts\setup.ps1')
