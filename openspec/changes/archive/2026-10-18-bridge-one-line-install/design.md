# Design: bridge-one-line-install

## Context

`pc-tools-speedups` added `install-runtime.sh` (bash, device or `--ssh`) and `install-runtime.ps1` (Windows, `-Ssh` only) as thin bootstraps: resolve the newest `deploy-v` release from the `releases/latest` redirect, download `archive/refs/tags/deploy-v<v>.tar.gz`, run the release's `install-stock.sh`. From a PC they run `ssh -t USER@HOST "curl <raw URL at the release tag> | sudo bash -s -- --version <v> <options>"`. The bridge's own installer, `install-bridge.sh`, builds from a checkout (Lely, dcfgen, the EDS lint venv, the bridge) and writes `canworks-bridge@.service`; instances are set up by hand.

## Goals / Non-Goals

**Goals:** the bridge installs and updates with one line on the device, from macOS/Linux over SSH and from Windows over SSH, behaving like the runtime line; the same line can also set up one bridge instance from a config folder; an update reaches running bridges; the first try works on a device with the Docker runtime.

**Non-Goals:** prebuilt bridge binaries as release assets (the device still builds, as the runtime line does; see Risks); a one-line route for the container image (it is already one `docker run`); config upload to a running bridge (`canworks-deploy --bridge` does that).

## Decisions

### One script name: `install-bridge.sh` gets a release mode

Users see one name for the bridge, on the device and from a PC, like `install-pc.sh`. The alternative, a separate bootstrap (`install-runtime.sh` beside `install-stock.sh`), was rejected for the bridge because there is no second name users already know; `install-bridge.sh` is the documented one.

The script decides its mode at the start:
- **release mode** when it is not in a checkout (`$REPO/tools/deploy/canworks/_lely_dcf/VERSION` missing next to it, which is the case when piped from GitHub), or when `--version` is given: resolve the release, download and unpack the tag's tarball into `mktemp -d`, check it has `scripts/install-bridge.sh`, and run that with the remaining options and `CANWORKS_PLUGIN_VERSION=<v>`. The temporary folder goes in an `EXIT` trap.
- **ssh mode** with `--ssh`: resolve the release on the PC, then `ssh -t [-p] [-i] USER@HOST "curl -LsSf <raw URL of install-bridge.sh at deploy-v<v>> | sudo bash -s -- --version <v> <options>"`, quoted with `printf %q`, `exec`'d so the exit status is the device's.
- **checkout mode** otherwise: today's behaviour.

The whole script moves into `main "$@"` on the last line, so piping it into bash is safe (bash has read the function before anything reads stdin). The release lookup, `--port`/`--identity` handling and the root check are copied from `install-runtime.sh` (two short functions; a shared sourced file is not possible for a piped script).

An older release named with `--version` runs its own `install-bridge.sh` from its tarball, so it installs as it did then; options this change adds do not exist there and the old script refuses them with its usual "unknown option".

### `install-bridge.ps1`

Same shape as `install-runtime.ps1`: `-Ssh` (mandatory), `-Version`, `-Port`, `-Identity`, `-Options`, `-Instance`, `-Config`, `-DryRun`; `throw` instead of `exit`; quoting for the device's POSIX shell. Runs as `& ([scriptblock]::Create((irm <raw URL>))) -Ssh pi@rpi.local`.

### Instance from the install line

`--instance NAME --config DIR` on the device: after the install, run `<prefix>/bin/canworks-bridge --config DIR/canworks.json --check-only` where the folder is (its EDS paths are relative to it), then copy the regular files of `DIR` (not subfolders; a config's EDS/DBC files sit next to it, as the docs already say) to `/etc/canworks-bridge/NAME/`, then `systemctl enable` and `restart` (restart, so an existing instance picks up a new config). A failed check prints its output, copies nothing, leaves a running instance on its old config and exits non-zero. Existing files in the instance folder that the new folder does not have are kept (the bridge may have saved an uploaded config there); the docs say so.

Over SSH the PC side runs one `ssh` without `-t` that makes `/tmp/canworks-bridge-upload.<random>` with `mktemp -d` and prints it, then `scp [-P PORT] [-i KEY] DIR/* USER@HOST:<that folder>`, then the `ssh -t` install with `--config <that folder> --remove-config-dir`. Three connections; with a key or an agent no prompt appears, otherwise the password is asked up to three times (documented; the SSH guides already recommend a key). `--remove-config-dir` is internal (not documented) and only removes a folder under `/tmp` whose name starts `canworks-bridge-upload.`. Windows uses the built-in `scp`.

Alternative considered: streaming a tar over the install's own `ssh -t`. Rejected: `-t` puts the remote end on a terminal, so a binary stream on stdin breaks, and `sudo` would compete with it for stdin.

### Update restarts running instances

Before replacing the binary, list active instances with `systemctl list-units 'canworks-bridge@*' --state=active --plain --no-legend`; after installing the unit, `systemctl restart` each and print their names. Through `CANWORKS_SYSTEMCTL` the test sees the calls. Instances that were not active are not touched; `enable` state is not changed.

### Prefix next to a Docker runtime

Today the check at the venv step dies with "install the bridge into its own prefix: --prefix /opt/canworks-bridge". Without an explicit `--prefix`, the same check now switches to `/opt/canworks-bridge` and says so; with an explicit `--prefix` it still dies. For updates and `--uninstall` without `--prefix`: if `/opt/canworks-bridge/bin/canworks-bridge` exists and `/opt/canworks/bin/canworks-bridge` does not, that prefix is used. The check moves before the build so the switch happens before anything is written.

### Release version

`install-runtime.sh` and the bridge's release mode export `CANWORKS_PLUGIN_VERSION=<v>` before running the release's script; `plugin/CMakeLists.txt` already prefers it over `git describe`. `install-stock.sh` must pass the environment through to its build (and into the managed Docker build, where the plugin is built in the container); the task checks that path.

## Testing

`test/pc-tools/test_install_scripts.py` gets bridge cases with `--dry-run` against the local fake release server: newest-version lookup, `--version`, pass-through options, the exact `ssh -t` command line (port, key), the `ssh`/`scp`/`ssh -t` sequence for `--instance`/`--config`, refusal of `--instance` without `--config`, and `install-bridge.ps1` the same under `pwsh` when available. The restart and prefix choice run the real script in checkout mode with `--binary` (a stub executable), `CANWORKS_SYSTEMCTL` pointing at a recording stub, and temporary `CANWORKS_UNIT_DIR`/`CANWORKS_BRIDGE_CONF_DIR`; the prefix choice needs new `CANWORKS_DEFAULT_PREFIX` and `CANWORKS_FALLBACK_PREFIX` test hooks. `shellcheck` already runs on the install scripts in the tools shard; `install-bridge.sh` is added to its list.

## Risks / Trade-offs

- The bridge still builds on the device (Lely, dcfgen, the bridge): on a Pi 5 that is several minutes, as with the runtime line. Prebuilt binaries per architecture would cut it to seconds but add release jobs and a libc/Debian compatibility promise; left for later. The container image is the fast route and the docs say so next to the line.
- Piping a script from `main` trusts `main`; the same mitigations as the runtime line (installs released code only, pinned and download-first forms documented).
- Up to three password prompts with `--config` over SSH without a key. Acceptable; documented.
- Editing `install-bridge.sh` triggers `bridge-image.yml` on this PR (path filter), which is wanted here: the image build uses checkout mode and must keep working.
