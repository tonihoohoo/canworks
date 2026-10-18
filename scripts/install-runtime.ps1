# Installs or updates the canworks runtime plugin on a remote Linux device from
# a Windows PC, over SSH (the OpenSSH client built into Windows 10 and 11). The
# device downloads the newest release and runs its install-stock.sh; nothing
# else is needed on the PC. Run it again to update.
#
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/tonihoohoo/canworks/main/scripts/install-runtime.ps1))) -Ssh pi@rpi.local
#   ... -Ssh pi@rpi.local -Options --with-link          # install-stock.sh options
#
#   -Ssh USER@HOST   the device (sudo there may ask for its password)
#   -Version X       install release deploy-vX instead of the newest one
#   -Port N          SSH port
#   -Identity FILE   SSH key
#   -Options ...     options for the release's install-stock.sh
#   -DryRun          print the ssh command, change nothing
#
# It only installs released code, never main. The newest release is found
# from GitHub's releases/latest redirect, so no API token is needed.

param(
    [Parameter(Mandatory = $true)][string]$Ssh,
    [string]$Version = "",
    [string]$Port = "",
    [string]$Identity = "",
    [string[]]$Options = @(),
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$Repo = if ($env:CANWORKS_REPO) { $env:CANWORKS_REPO } else { "https://github.com/tonihoohoo/canworks" }
$Raw = if ($env:CANWORKS_RAW) { $env:CANWORKS_RAW } else { "https://raw.githubusercontent.com/tonihoohoo/canworks" }
$Api = if ($env:CANWORKS_API) { $env:CANWORKS_API } else { "https://api.github.com/repos/tonihoohoo/canworks" }

# throw, not exit: run as a script block, exit would close the user's PowerShell window.
function Fail([string]$Message) { throw "install-runtime: $Message" }

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

$Version = $Version -replace '^deploy-v', '' -replace '^v', ''
if (-not $Version) { $Version = Get-LatestVersion }
$Tag = "deploy-v$Version"

$remote = "curl -LsSf " + (Quote "$Raw/$Tag/scripts/install-runtime.sh") + " | sudo bash -s -- --version " + (Quote $Version)
foreach ($o in $Options) { $remote += " " + (Quote $o) }

$sshArgs = @("-t")
if ($Port) { $sshArgs += @("-p", $Port) }
if ($Identity) { $sshArgs += @("-i", $Identity) }
$sshArgs += @($Ssh, $remote)

Write-Host "install-runtime: installing canworks $Version on $Ssh"
if ($DryRun) {
    Write-Host ("would run: ssh " + (($sshArgs | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join " "))
    return
}
if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    Fail "ssh is needed: Settings > Apps > Optional features > OpenSSH Client"
}
$ErrorActionPreference = "Continue"  # ssh's stderr is not an error of this script
& ssh @sshArgs
$ErrorActionPreference = "Stop"
if ($LASTEXITCODE -ne 0) { Fail "the install on $Ssh ended with exit status $LASTEXITCODE" }
