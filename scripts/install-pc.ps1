# Installs or updates the canworks PC tools (configurator, deploy tool,
# diagnostics) on Windows, with uv and a uv-managed Python: no Python and no
# admin rights needed. Run it again to update to the newest release.
#
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/tonihoohoo/canworks/main/scripts/install-pc.ps1 | iex"
#
# With options (a given release, or uninstall):
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/tonihoohoo/canworks/main/scripts/install-pc.ps1))) -Version 0.82.0
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/tonihoohoo/canworks/main/scripts/install-pc.ps1))) -Uninstall
#
#   -Version X    install release deploy-vX instead of the newest one
#   -Wheel FILE   install this local wheel instead of a release (CI)
#   -Python V     the Python uv uses (default 3.12; a path to an installed Python works too)
#   -Uninstall    remove the tools (uv and the tools' settings stay)
#   -DryRun       print what would run, change nothing
#
# It only installs released wheels, never the code on main. The newest release
# is found from GitHub's releases/latest redirect, so no API token is needed.
# Behind a TLS-inspecting company proxy set UV_NATIVE_TLS=1 (docs/install-pc.md).

param(
    [string]$Version = "",
    [string]$Wheel = "",
    [string]$Python = "3.12",
    [switch]$Uninstall,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$Repo = if ($env:CANWORKS_REPO) { $env:CANWORKS_REPO } else { "https://github.com/tonihoohoo/canworks" }
$Api = if ($env:CANWORKS_API) { $env:CANWORKS_API } else { "https://api.github.com/repos/tonihoohoo/canworks" }
$UserHome = if ($env:USERPROFILE) { $env:USERPROFILE } else { $HOME }
$UvInstaller = if ($env:CANWORKS_UV_INSTALLER) { $env:CANWORKS_UV_INSTALLER } else { "https://astral.sh/uv/install.ps1" }

# throw, not exit: run as a script block, exit would close the user's PowerShell window.
function Fail([string]$Message) { throw "install-pc: $Message" }
function Say([string]$Message) { Write-Host "install-pc: $Message" }

function Invoke-Step([string]$Exe, [string[]]$Arguments) {
    if ($DryRun) { Write-Host ("would run: " + $Exe + " " + ($Arguments -join " ")); return }
    # Windows PowerShell 5.1 turns a native program's stderr into errors when
    # its output is redirected (CI, a log); with "Stop" uv's progress lines
    # would end the script. The exit code decides instead.
    $ErrorActionPreference = "Continue"
    & $Exe @Arguments
    $ErrorActionPreference = "Stop"
    if ($LASTEXITCODE -ne 0) { Fail "$Exe exited with $LASTEXITCODE (see its message above)" }
}

# uv on PATH, else where its installer puts it, else install it now.
function Find-Uv {
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($dir in @($env:XDG_BIN_HOME, (Join-Path $UserHome ".local\bin"), (Join-Path $UserHome ".cargo\bin"))) {
        if ($dir -and (Test-Path (Join-Path $dir "uv.exe"))) { return (Join-Path $dir "uv.exe") }
    }
    return ""
}

# The newest release: GitHub redirects releases/latest to releases/tag/<tag>.
function Get-LatestVersion {
    $tag = ""
    try {
        $request = [System.Net.HttpWebRequest]::Create("$Repo/releases/latest")
        $request.AllowAutoRedirect = $false
        $request.Method = "GET"
        $response = $request.GetResponse()
        $location = $response.Headers["Location"]
        $response.Close()
        if ($location) { $tag = ($location -split "/")[-1] }
    } catch {
        Fail "could not reach $Repo/releases/latest (behind a company proxy? see docs/install-pc.md)"
    }
    if ($tag -notlike "deploy-v*") {
        # Fallback: the API, once.
        try { $tag = (Invoke-RestMethod -UseBasicParsing "$Api/releases/latest").tag_name } catch { $tag = "" }
    }
    if ($tag -notlike "deploy-v*") { Fail "could not find the newest release at $Repo/releases" }
    return $tag.Substring("deploy-v".Length)
}

$Version = $Version -replace '^deploy-v', '' -replace '^v', ''

$Uv = Find-Uv
if (-not $Uv) {
    if ($Uninstall) { Fail "uv is not installed, so neither are the tools" }
    Say "installing uv ($UvInstaller)"
    if ($DryRun) {
        Write-Host "would run: powershell -ExecutionPolicy ByPass -c `"irm $UvInstaller | iex`""
        $Uv = "uv"
    } else {
        Invoke-Step "powershell" @("-NoProfile", "-ExecutionPolicy", "ByPass", "-c", "irm $UvInstaller | iex")
        $Uv = Find-Uv
        if (-not $Uv) { Fail "uv was installed but not found in $UserHome\.local\bin; open a new terminal and run this again" }
    }
}

if ($Uninstall) {
    Invoke-Step $Uv @("tool", "uninstall", "canworks")
    Say "removed; uv and the tools' settings folder were kept"
    return
}

if ($Wheel) {
    if (-not (Test-Path $Wheel)) { Fail "no such wheel: $Wheel" }
    $Spec = $Wheel
    Say "installing $Wheel"
} else {
    if (-not $Version) { $Version = Get-LatestVersion }
    $Spec = "canworks @ $Repo/releases/download/deploy-v$Version/canworks-$Version-py3-none-any.whl"
    Say "installing canworks $Version"
}

Invoke-Step $Uv @("tool", "install", "--force", "--compile-bytecode", "--python", $Python, $Spec)

$Bin = Join-Path $UserHome ".local\bin"
if (-not $DryRun) {
    $ErrorActionPreference = "Continue"
    $dir = & $Uv tool dir --bin 2>$null
    $ErrorActionPreference = "Stop"
    if ($LASTEXITCODE -eq 0 -and $dir) { $Bin = "$dir".Trim() }
}
$NewTerminal = $false
if (-not (($env:PATH -split ";") -contains $Bin)) {
    if ($DryRun) { Write-Host "would run: $Uv tool update-shell" } else { Invoke-Step $Uv @("tool", "update-shell") }
    $NewTerminal = $true
}

if ($DryRun) {
    Write-Host "would run: $Bin\canworks-deploy.exe --version"
} else {
    Invoke-Step (Join-Path $Bin "canworks-deploy.exe") @("--version")
}
if ($NewTerminal) {
    Say "open a new terminal so $Bin is on PATH, then run canworks-config"
} else {
    Say "done; run canworks-config to open the configurator"
}
