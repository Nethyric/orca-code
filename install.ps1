# Orca Code installer for Windows - zero-dependency AI coding agent (Python 3.9+)
# Usage (PowerShell):
#   irm https://raw.githubusercontent.com/Nethyric/orca-code/main/install.ps1 | iex
$ErrorActionPreference = "Stop"

$Zip = "https://github.com/Nethyric/orca-code/archive/refs/heads/main.zip"

function Say($msg) { Write-Host "$msg" -ForegroundColor Cyan }
function Err($msg) { Write-Host "$msg" -ForegroundColor Red }

# -- 1. find a suitable Python ------------------------------------------
$found = $null
$candidates = @()
if (Get-Command py -ErrorAction SilentlyContinue)     { $candidates += ,@("py", "-3") }
if (Get-Command python -ErrorAction SilentlyContinue) { $candidates += ,@("python") }
if (Get-Command python3 -ErrorAction SilentlyContinue){ $candidates += ,@("python3") }

foreach ($c in $candidates) {
    $exe = $c[0]
    $rest = @()
    if ($c.Length -gt 1) { $rest = $c[1..($c.Length - 1)] }
    # MS Store alias prints nothing or opens the store; 2>$null guards that
    $out = (& $exe @rest --version 2>$null | Out-String).Trim()
    if ($out -match "^Python\s+(\d+)\.(\d+)") {
        if ([int]$Matches[1] -gt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 9)) {
            $found = $c
            break
        }
    }
}
if (-not $found) {
    Err "Python 3.9+ not found. Install it from https://www.python.org/downloads/ and retry."
    exit 1
}
$exe  = $found[0]
$rest = @()
if ($found.Length -gt 1) { $rest = $found[1..($found.Length - 1)] }
Say ("using: " + (& $exe @rest --version 2>$null))

# -- 2. install from the repo zip (no git required) ----------------------
Say "installing Orca Code..."
& $exe @rest -m pip install --quiet --upgrade --force-reinstall $Zip
if ($LASTEXITCODE -ne 0) {
    Err "pip install failed. Try manually: $exe -m pip install $Zip"
    exit 1
}

# -- 3. verify ------------------------------------------------------------
$ver = & $exe @rest -m orca --version
if ($LASTEXITCODE -ne 0) {
    Err "installation did not produce a working 'orca' module"
    exit 1
}
Say "installed: $ver"
Say "next:  orca auth login   -> add a provider key (validated live)"
Say "      orca               -> start coding"
Say "if 'orca' is not recognized, reopen the terminal (PATH refresh)"
