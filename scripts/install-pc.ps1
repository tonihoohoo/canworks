# Installs or updates the canworks PC tools (configurator, deploy tool,
# diagnostics) on Windows, with uv and a uv-managed Python: no Python and no
# admin rights needed. Run it again to update to the newest release.
#
#   $f = "$env:TEMP\install-pc.ps1"; irm https://github.com/tonihoohoo/canworks/releases/latest/download/install-pc.ps1 -OutFile $f; powershell -NoProfile -ExecutionPolicy RemoteSigned -File $f
#
# Options go after the file name (a given release, or uninstall):
#   ... -File $f -Version 0.82.0
#   ... -File $f -Uninstall
#
#   -Version X    install release deploy-vX instead of the newest one
#   -Wheel FILE   install this local wheel instead of a release (CI)
#   -Constraints FILE  the dependency versions for -Wheel (a release brings its own)
#   -Python V     the Python uv uses (default 3.14; a path to an installed Python works too)
#   -Force        install even when this version is already installed
#   -NoShortcut   do not add the "canworks configurator" Start menu and desktop shortcut
#   -Uninstall    remove the tools and the shortcut (uv and the tools' settings stay)
#   -DryRun       print what would run, change nothing
#
# It only installs released wheels, never the code on main. The newest release
# is found from GitHub's releases/latest redirect, so no API token is needed.
# A release installs the exact dependency versions CI tested: its
# canworks-<version>-constraints.txt asset (docs/install-pc.md).
# A missing uv comes from uv's own release zip, checked against its SHA-256;
# the script runs no downloaded code and starts no other PowerShell.
# Behind a TLS-inspecting company proxy set UV_SYSTEM_CERTS=1 (uv before 0.11: UV_NATIVE_TLS=1; docs/install-pc.md).

param(
    [string]$Version = "",
    [string]$Wheel = "",
    [string]$Constraints = "",
    [string]$Python = "3.14",
    [switch]$Uninstall,
    [switch]$NoShortcut,
    [switch]$Force,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$Repo = if ($env:CANWORKS_REPO) { $env:CANWORKS_REPO } else { "https://github.com/tonihoohoo/canworks" }
$Api = if ($env:CANWORKS_API) { $env:CANWORKS_API } else { "https://api.github.com/repos/tonihoohoo/canworks" }
$UserHome = if ($env:USERPROFILE) { $env:USERPROFILE } else { $HOME }
$UvDownload = if ($env:CANWORKS_UV_DOWNLOAD) { $env:CANWORKS_UV_DOWNLOAD } else { "https://github.com/astral-sh/uv/releases/latest/download" }

# throw, not exit: run inside a PowerShell window (older docs used a script
# block), exit would close it.
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

# uv's Windows zip for this PC, checked against the .sha256 next to it, then
# uv.exe, uvx.exe and uvw.exe into %USERPROFILE%\.local\bin, where uv's own
# installer puts them. Nothing is copied unless the checksum matches.
function Install-Uv {
    $arch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "aarch64" } else { "x86_64" }
    $zipName = "uv-$arch-pc-windows-msvc.zip"
    $url = "$UvDownload/$zipName"
    $target = Join-Path $UserHome ".local\bin"
    Say "installing uv from $url"
    if ($DryRun) {
        Write-Host "would download: $url (checked against $url.sha256)"
        Write-Host "would copy: uv.exe, uvx.exe, uvw.exe to $target"
        return
    }
    $work = Join-Path ([System.IO.Path]::GetTempPath()) ("canworks-uv-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $work | Out-Null
    try {
        $zip = Join-Path $work $zipName
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $zip
            $sumText = (Invoke-WebRequest -UseBasicParsing -Uri "$url.sha256").Content
        } catch {
            Fail "could not download uv from $url (behind a company proxy? see docs/install-pc.md)"
        }
        if ($sumText -is [byte[]]) { $sumText = [System.Text.Encoding]::ASCII.GetString($sumText) }
        $expected = ("$sumText".Trim() -split "\s+")[0].ToLowerInvariant()
        $actual = (Get-FileHash -Algorithm SHA256 -Path $zip).Hash.ToLowerInvariant()
        if (-not $expected -or $actual -ne $expected) {
            Fail "the uv download did not match its checksum ($url); nothing was installed"
        }
        $unpacked = Join-Path $work "uv"
        Expand-Archive -Path $zip -DestinationPath $unpacked
        New-Item -ItemType Directory -Force -Path $target | Out-Null
        foreach ($name in @("uv.exe", "uvx.exe", "uvw.exe")) {
            $found = Get-ChildItem -Path $unpacked -Recurse -Filter $name | Select-Object -First 1
            if ($found) { Copy-Item -Force -Path $found.FullName -Destination (Join-Path $target $name) }
            elseif ($name -eq "uv.exe") { Fail "the uv download has no uv.exe ($url)" }
        }
    } finally {
        Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
    }
}

$Uv = Find-Uv
if (-not $Uv) {
    if ($Uninstall) { Fail "uv is not installed, so neither are the tools" }
    Install-Uv
    if ($DryRun) {
        $Uv = "uv"
    } else {
        $Uv = Find-Uv
        if (-not $Uv) { Fail "uv was installed but not found in $UserHome\.local\bin; open a new terminal and run this again" }
    }
}

# The first uv release that knows the default Python: an older uv is updated.
$UvMin = [version]"0.9.0"

# A uv too old to know the default Python: update it (uv's own zip or
# installer made it), else say how. An unreadable version is left as it is.
if (-not $Uninstall -and -not ($DryRun -and $Uv -eq "uv")) {
    $ErrorActionPreference = "Continue"
    $UvVersionText = "$(& $Uv --version 2>$null)"
    $ErrorActionPreference = "Stop"
    if ($UvVersionText -match '^uv (\d+\.\d+(\.\d+)?)' -and [version]$Matches[1] -lt $UvMin) {
        $UvVersion = $Matches[1]
        Say "uv $UvVersion is older than $UvMin; updating it"
        try { Invoke-Step $Uv @("self", "update") } catch {
            Fail "could not update uv $UvVersion; update it with the tool that installed it (for example winget upgrade astral-sh.uv) and run this again"
        }
    }
}

# Where uv puts the commands.
function Get-BinDir {
    $bin = Join-Path $UserHome ".local\bin"
    if (-not $DryRun) {
        $ErrorActionPreference = "Continue"
        $dir = & $Uv tool dir --bin 2>$null
        $ErrorActionPreference = "Stop"
        if ($LASTEXITCODE -eq 0 -and $dir) { $bin = "$dir".Trim() }
    }
    return $bin
}

# The installed tools from uv's own record ("canworks v0.94.2 [CPython 3.14.8]"):
# @{ Version; Python } (Python as major.minor), empty strings when not found.
function Get-Installed {
    $found = @{ Version = ""; Python = "" }
    if ($DryRun -and $Uv -eq "uv") { return $found }
    $ErrorActionPreference = "Continue"
    $lines = & $Uv tool list --show-python 2>$null
    $ErrorActionPreference = "Stop"
    foreach ($line in @($lines)) {
        if ("$line" -match '^canworks v(\S+)') {
            $found.Version = $Matches[1]
            if ("$line" -match '\[CPython (\d+\.\d+)') { $found.Python = $Matches[1] }
            break
        }
    }
    return $found
}

if ($Uninstall) {
    # The shortcut first, while canworks-config is still there to remove it.
    $Config = Join-Path (Get-BinDir) "canworks-config.exe"
    if ($DryRun -or (Test-Path $Config)) {
        try { Invoke-Step $Config @("--remove-shortcut") } catch { Say "could not remove the shortcut: $_" }
    }
    Invoke-Step $Uv @("tool", "uninstall", "canworks")
    Say "removed; uv and the tools' settings folder were kept"
    return
}

$Downloaded = ""
if ($Wheel) {
    if (-not (Test-Path $Wheel)) { Fail "no such wheel: $Wheel" }
    $Spec = $Wheel
    Say "installing $Wheel"
    if ($Constraints) {
        if (-not (Test-Path $Constraints)) { Fail "no such constraints file: $Constraints" }
    } else {
        Say "the dependency versions are not locked: uv picks the newest ones the tools allow"
    }
} else {
    if ($Constraints) { Fail "-Constraints goes with -Wheel; a release brings its own" }
    if (-not $Version) { $Version = Get-LatestVersion }
    $Spec = "canworks @ $Repo/releases/download/deploy-v$Version/canworks-$Version-py3-none-any.whl"
    # Already this version on this Python: nothing to do, unless -Force. The
    # Python is compared only when -Python is a version, not a path.
    $Installed = Get-Installed
    $SamePython = $true
    if ($Python -match '^(\d+\.\d+)(\.\d+)?$') {
        $WantPython = $Matches[1]
        $SamePython = $Installed.Python -eq $WantPython
    }
    if (-not $Force -and $Installed.Version -eq $Version -and $SamePython) {
        Say "canworks $Version is already installed; -Force installs it again"
        if (-not (($env:PATH -split ";") -contains (Get-BinDir))) {
            Say "open a new terminal so $(Get-BinDir) is on PATH, then run canworks-config"
        }
        return
    }
    if ($Installed.Version -eq $Version -and -not $SamePython) {
        $was = if ($Installed.Python) { $Installed.Python } else { "another Python" }
        Say "installing canworks $Version again on Python $WantPython (it was on $was)"
    } else {
        Say "installing canworks $Version"
    }
    # The release's locked dependency versions. A release from before them has
    # no such asset (404) and installs unlocked, as it always did. Any other
    # failure stops here, with the installed tools unchanged. Also in a dry
    # run: the download changes nothing.
    $ConstraintsUrl = "$Repo/releases/download/deploy-v$Version/canworks-$Version-constraints.txt"
    $Downloaded = Join-Path ([System.IO.Path]::GetTempPath()) ("canworks-constraints-" + [guid]::NewGuid().ToString("N") + ".txt")
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $ConstraintsUrl -OutFile $Downloaded
        $Constraints = $Downloaded
    } catch {
        $status = 0
        if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
        if ($status -eq 404) {
            Say "release $Version does not lock its dependency versions; uv picks the newest ones the tools allow"
        } else {
            Remove-Item -Force $Downloaded -ErrorAction SilentlyContinue
            Fail "could not download canworks-$Version-constraints.txt from $ConstraintsUrl ($($_.Exception.Message)); nothing was changed"
        }
    }
}

# Only runtime dependencies: can-j1939 lists pytest as one but never imports
# it, so an override drops it (docs/install-pc.md).
$Overrides = Join-Path ([System.IO.Path]::GetTempPath()) ("canworks-overrides-" + [guid]::NewGuid().ToString("N") + ".txt")
Set-Content -Path $Overrides -Value "pytest; sys_platform == 'never'" -Encoding ASCII
$InstallArgs = @("tool", "install", "--force", "--compile-bytecode", "--python", $Python, "--overrides", $Overrides)
if ($Constraints) { $InstallArgs += @("--constraints", $Constraints) }
try {
    Invoke-Step $Uv ($InstallArgs + @($Spec))
} finally {
    Remove-Item -Force $Overrides -ErrorAction SilentlyContinue
    if ($Downloaded) { Remove-Item -Force $Downloaded -ErrorAction SilentlyContinue }
}

$Bin = Get-BinDir
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
# The Start menu and desktop shortcut: starts the configurator without a console window. Not fatal.
if (-not $NoShortcut) {
    try { Invoke-Step (Join-Path $Bin "canworks-config.exe") @("--create-shortcut") }
    catch { Say "could not add the shortcut; run canworks-config --create-shortcut later ($_)" }
}
if ($NewTerminal) {
    Say "open a new terminal so $Bin is on PATH, then run canworks-config"
} else {
    Say "done; open canworks configurator from the Start menu or the desktop, or run canworks-config"
}
