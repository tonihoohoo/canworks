# Installs or updates canworks-bridge, the Modbus TCP bridge, on a remote
# Linux device from a Windows PC, over SSH (the OpenSSH client built into
# Windows 10 and 11). The device downloads the newest release and runs its
# install-bridge.sh; nothing else is needed on the PC. Run it again to update.
#
#   $f = "$env:TEMP\install-bridge.ps1"; irm https://github.com/tonihoohoo/canworks/releases/latest/download/install-bridge.ps1 -OutFile $f; powershell -NoProfile -ExecutionPolicy RemoteSigned -File $f -Ssh admin@plc.local
#   ... -Ssh admin@plc.local -Instance line1 -Config .\line1     # also set up and start a bridge
#   ... -Ssh admin@plc.local -WithOpenplc -Instance line1 -Config .\line1   # OpenPLC runtime first
#   ... -Ssh admin@plc.local -Options --uninstall,--purge        # install-bridge.sh options
#
#   -Ssh USER@HOST   the device (sudo there may ask for its password)
#   -Version X       install release deploy-vX instead of the newest one (from 0.84.0 on)
#   -Port N          SSH port
#   -Identity FILE   SSH key
#   -Instance NAME   with -Config: the bridge instance canworks-bridge@NAME
#   -Config DIR      folder on this PC with canworks.json and its EDS/DBC files;
#                    copied to the device, checked, installed as
#                    /etc/canworks-bridge/NAME/ and started
#   -WithOpenplc     when the device has no OpenPLC runtime, install upstream's at the
#                    release's pinned versions first (install-bridge.sh --with-openplc)
#   -PinnedRuntime   put a managed Docker runtime on the release's pinned version
#                    (install-bridge.sh --pinned-runtime)
#   -Options ...     options for the release's install-bridge.sh
#   -DryRun          print the ssh and scp commands, change nothing
#
# It only installs released code, never main. The newest release is found
# from GitHub's releases/latest redirect, so no API token is needed. Without
# an SSH key, -Config asks for the device password up to three times.

param(
    [Parameter(Mandatory = $true)][string]$Ssh,
    [string]$Version = "",
    [string]$Port = "",
    [string]$Identity = "",
    [string]$Instance = "",
    [string]$Config = "",
    [string[]]$Options = @(),
    [switch]$WithOpenplc,
    [switch]$PinnedRuntime,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$Repo = if ($env:CANWORKS_REPO) { $env:CANWORKS_REPO } else { "https://github.com/tonihoohoo/canworks" }
$Raw = if ($env:CANWORKS_RAW) { $env:CANWORKS_RAW } else { "https://raw.githubusercontent.com/tonihoohoo/canworks" }
$Api = if ($env:CANWORKS_API) { $env:CANWORKS_API } else { "https://api.github.com/repos/tonihoohoo/canworks" }

# throw, not exit: run inside a PowerShell window (older docs used a script
# block), exit would close it.
function Fail([string]$Message) { throw "install-bridge: $Message" }

# The newest release: GitHub redirects releases/latest to releases/tag/<tag>.
function Get-LatestVersion {
    $tag = ""
    try {
        $request = [System.Net.HttpWebRequest]::Create("$Repo/releases/latest")
        $request.AllowAutoRedirect = $false
        $response = $request.GetResponse()
        $location = $response.Headers["Location"]
        $response.Close()
        if ($location) { $tag = ($location -split "/")[-1] }
    } catch {
        Fail "could not reach $Repo/releases/latest"
    }
    if ($tag -notlike "deploy-v*") {
        try { $tag = (Invoke-RestMethod -UseBasicParsing "$Api/releases/latest").tag_name } catch { $tag = "" }
    }
    if ($tag -notlike "deploy-v*") { Fail "could not find the newest release at $Repo/releases" }
    return $tag.Substring("deploy-v".Length)
}

# One word for the device's POSIX shell.
function Quote([string]$Word) { "'" + ($Word -replace "'", "'\''") + "'" }

function Show([string]$Tool, [string[]]$Arguments) {
    "would run: $Tool " + (($Arguments | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join " ")
}

# The checks that need nothing on the device.
$files = @()
if ($Instance -or $Config) {
    if (-not ($Instance -and $Config)) { Fail "-Instance NAME and -Config DIR go together" }
    if ($Instance -notmatch '^[A-Za-z0-9_-]+$') { Fail "-Instance ${Instance}: use letters, digits, - and _ only" }
    if (-not (Test-Path -LiteralPath (Join-Path $Config "canworks.json") -PathType Leaf)) {
        Fail "-Config $Config has no canworks.json"
    }
    # Its regular files: the EDS and DBC files sit next to canworks.json.
    $files = @(Get-ChildItem -LiteralPath $Config -File | ForEach-Object { $_.FullName })
}

$Version = $Version -replace '^deploy-v', '' -replace '^v', ''
if (-not $Version) { $Version = Get-LatestVersion }
$Tag = "deploy-v$Version"

$sshOpts = @()
$scpOpts = @()
if ($Port) { $sshOpts += @("-p", $Port); $scpOpts += @("-P", $Port) }
if ($Identity) { $sshOpts += @("-i", $Identity); $scpOpts += @("-i", $Identity) }

if (-not $DryRun -and -not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    Fail "ssh is needed: Settings > Apps > Optional features > OpenSSH Client"
}

Write-Host "install-bridge: installing canworks-bridge $Version on $Ssh"
$deviceArgs = @("--version", $Version) + $Options
if ($WithOpenplc) { $deviceArgs += "--with-openplc" }
if ($PinnedRuntime) { $deviceArgs += "--pinned-runtime" }
if ($Instance) {
    # The config goes to a folder of its own on the device first; the install
    # over ssh -t cannot carry files (its stdin is the terminal).
    $mkArgs = $sshOpts + @($Ssh, "mktemp -d /tmp/canworks-bridge-upload.XXXXXX")
    if ($DryRun) {
        $upload = "<upload folder>"
        Write-Host (Show "ssh" $mkArgs)
        Write-Host (Show "scp" ($scpOpts + $files + @("${Ssh}:$upload/")))
    } else {
        $ErrorActionPreference = "Continue"
        $upload = (& ssh @mkArgs | Select-Object -Last 1)
        $ErrorActionPreference = "Stop"
        if ($LASTEXITCODE -ne 0 -or "$upload" -notlike "/tmp/canworks-bridge-upload.*") {
            Fail "could not make an upload folder on $Ssh"
        }
        Write-Host "install-bridge: copying $($files.Count) config files to $Ssh"
        $ErrorActionPreference = "Continue"
        & scp -q @scpOpts @files "${Ssh}:$upload/"
        $ErrorActionPreference = "Stop"
        if ($LASTEXITCODE -ne 0) { Fail "could not copy $Config to $Ssh" }
    }
    $deviceArgs += @("--instance", $Instance, "--config", $upload, "--remove-config-dir")
}

# The device runs install-bridge.sh as of the release it installs, pinned to it.
$remote = "curl -LsSf " + (Quote "$Raw/$Tag/scripts/install-bridge.sh") + " | sudo bash -s --"
foreach ($a in $deviceArgs) { $remote += " " + (Quote $a) }
$installArgs = @("-t") + $sshOpts + @($Ssh, $remote)

if ($DryRun) {
    Write-Host (Show "ssh" $installArgs)
    return
}
$ErrorActionPreference = "Continue"  # ssh's stderr is not an error of this script
& ssh @installArgs
$ErrorActionPreference = "Stop"
if ($LASTEXITCODE -ne 0) { Fail "the install on $Ssh ended with exit status $LASTEXITCODE" }
