# Design

Explore notes: the project's research notes of 2026-10-21 ("install from configurator"), with a clickable mockup of the Devices workspace.

## Where it lives

A third workspace, **Devices**, next to **Configure | Commission**. Installing is not editing the config and not working on the live bus, and it outlives one page view (a job runs for minutes), so it gets its own place instead of a dialog off the top bar. The other pages only point to it:

| Where | What it shows | Action |
|---|---|---|
| Configure → Online access, Runtime host | the device's state when the host is a device of the project (`canworks 0.93.4, off`) | **Open in Devices** |
| Configure → Modbus bridge | where the bridge runs and its state | **Install on device…** |
| Commission → Connect…, nothing found | "No runtime found on this network." | **Install canworks on a device…** |
| status bar | the running install job | **Show** |

A CODESYS project shows the Devices workspace with a one-line note that CODESYS installs its runtime itself; nothing is offered there.

## Devices of a project

Kept on the PC in `devices.json` in the settings folder, per project folder (like `online.json`): host, port, SSH user, key choice (agent and `~/.ssh` keys, or the canworks key), the host key, and the last probe result with its time. Never a password. A device is added by **Add device…** (host, user; port folded) or from the discovered list (`_canworks._tcp`, plus plain SSH hosts typed by hand). The first device added to a project with no runtime host sets Online access's host.

## SSH

`paramiko` in the configurator's process. Reasons: same code on all three PC systems; password and host-key questions are page dialogs rather than terminal prompts (the configurator has no terminal); no PowerShell script on Windows. It uses the user's SSH agent (Pageant and the Windows OpenSSH agent on Windows) and the default keys in `~/.ssh`, and reads `~/.ssh/config` for host aliases, user and port.

- **Host key**: unknown key → dialog with the SHA256 fingerprint, **Trust and connect** / Cancel; trusted keys go to `known_hosts` in the canworks settings folder (not the user's own file). A changed key stops the connection with "The device's key changed. If it was reinstalled, Forget its key and connect again." and **Forget key**; no silent replace.
- **Login**: agent and keys first; when none works, the password dialog. After a password login, **Use key login from now on** creates `canworks_ed25519` in the settings folder once (mode 0600) and appends its public key to the device user's `~/.ssh/authorized_keys` (no duplicate line).
- **Passwords**: held only in the request that uses them and dropped after. The sudo password is written once to `sudo -S -p ''` on the job's stdin. The page never sends a password back to the browser, and logs never contain one.
- One SSH connection per device at a time, opened for a probe or job start and closed after; the job itself does not need it.

## Probe

`scripts/device-probe.sh` (POSIX sh, read-only, no root), shipped inside the PC tools package and in each release, sent over the connection's stdin and run with `sh -s`. It prints one JSON object. Reading it needs no canworks on the device, so the same probe works on a fresh device.

Fields: `os`, `arch`, `systemd`, `disk_free_mb` (`/opt`, `/var/lib/docker`), `mem_mb`, `internet` (HEAD of the release host, 5 s), `sudo` (`none` for root, `nopasswd`, `password`), `runtime` (`none` | `native` | `docker-managed` | `docker-other`, `version`, `plc_state` when its local status answers), `plugin` (`version` from `/opt/canworks/VERSION`, `built_for` from `lib/runtime-version`/`runtime-commit`, `enabled` from the `canworks` line in `plugins.conf`), `bridge` (`version`, `prefix`, instances with state), `link`, `discovery`, `can` (`ip -j -d link show type can` and vcan: name, state, bit rate), `serial` (`/dev/serial/by-id`), `j1939_module`, `install_job` (a running or last job: id, state, step). Missing tools give `null`, never a failure.

The page turns the JSON into rows; the logic (what the project needs, which action) is in Python (`devices/plan.py`) and tested without a device.

## Actions

`plan(probe, project, pc_version)` gives one main action and the row actions:

| State | Main action |
|---|---|
| OpenPLC project, no runtime | **Install OpenPLC Runtime and canworks** |
| runtime, no plugin | **Install canworks X** |
| plugin older than X | **Update A → X** |
| plugin built for another runtime version | **Rebuild for runtime vN** (also when the version is equal) |
| plugin newer than X | none; "This device has canworks A, newer than these PC tools (X). Update the PC tools." |
| bridge project, no bridge | **Install and start this project's bridge** |
| bridge older than X or instance config differs | **Update A → X** / **Start this project's bridge** |
| all current | none, "Up to date" |

X is the PC tools' version. A release for X must exist (checked through the same `releases/latest` / tag URL the scripts use); a PC tools build without a release (development) offers the newest release with a note. Options fold under the main action: remote link (on by default, it stays off the internet until the config says so), discovery (on), protocols (both).

Not offered when the probe forbids it, with the reason in one line: no systemd, no internet, less than 2 GB free, sudo refused, another job running.

## The job

On the device, as root:

```
systemd-run --unit canworks-install-<id> --collect --property=Type=exec \
  flock -n /run/canworks-install.lock \
  sh -c 'curl -LsSf <release>/install-runtime.sh | bash -s -- --version X [options]' \
  > /var/log/canworks-install/<id>.log 2>&1
```

(the bridge with `install-bridge.sh`, its `--instance/--config` folder copied first over SFTP to a temporary folder the job removes). The configurator follows the log with `tail -c +OFFSET` on each poll (2 s while the page is open) and the unit state from `systemctl show`. The job keeps running when the connection drops or the configurator stops; the probe reports it (`install_job`), and the page resumes from the log. **Stop** runs `systemctl stop` on the unit and then the probe. The last five logs are kept on the device.

Steps come from the scripts' `::canworks-step N/M text` lines; any other line is log. The page shows the step list with times, the current step's elapsed time and, once measured on a device class, a typical total ("usually about 12 min on this device", from the last job's duration on that device).

Errors: the job's exit status and the last 20 log lines, plus one sentence for the known cases the scripts name (`no internet`, `disk full`, `apt is locked by another program`, `runtime not found`, `runtime image changed`, `sudo refused`).

## OpenPLC runtime

`install-runtime.sh --with-openplc`: when no runtime is found, run upstream's installer (`curl -fsSL https://runtime.getedge.me | bash` as root, managed Docker), wait until the runtime answers locally, then install the plugin. With a runtime present it does nothing extra. The confirmation names the upstream URL and that it installs Docker. After the job the page asks for the runtime's first user (name, password twice), creates it through the runtime's API as `canworks-sim-runtime` does, and then forgets the password. A runtime that already has users is left alone.

## After the job

Probe again. OpenPLC: "canworks switches on with the next upload (editor's Build and upload, or canworks-deploy)", and Online access's host is the device. Docker mode also says the PLC is empty until then. Bridge: "The bridge runs this project's config", **Open in Commission**.

## Uninstall

Row action **Uninstall** per part (plugin: `install-runtime.sh --uninstall`; bridge: `install-bridge.sh --uninstall`), **Remove everything** in the device's menu (`--purge` on both). Each confirms in one sentence. The OpenPLC runtime itself is never removed from here.

## Alternatives

- **System `ssh` with `SSH_ASKPASS`**: no new dependency, but password handling on older Windows 10 OpenSSH builds is unreliable and every question would still be a terminal prompt somewhere. Rejected.
- **Running the job over the SSH session (`ssh -t`)**: what the scripts do today; a sleeping laptop kills a long build. Kept for the terminal route only.
- **Install the newest release**: the device could then be ahead of the configurator's config format. The PC tools' version is the safer default.

## Risks

- `paramiko` adds about 10 MB (`cryptography`, `bcrypt`, `pynacl` wheels exist for every platform the tools ship on). The one-line installer's time must stay within the fast-start requirement.
- Upstream's runtime installer changes outside our control; the job reports its output as is, and the docs keep the manual route.
