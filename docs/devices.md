# Installing on a device from the configurator

The configurator's **Devices** workspace installs what a project needs on a Linux device over SSH: the canworks plugin for an OpenPLC project (and the OpenPLC Runtime itself on a fresh device), or the Modbus bridge with the project's saved config for a bridge project. It runs the same release scripts as the one-line installs ([install-stock.md](install-stock.md), [modbus-bridge.md](modbus-bridge.md#install)), always the newest release, and shows their progress step by step. A CODESYS project has nothing to install: the page says so.

**Configure | Commission | Devices** at the top of the page switches to it. The devices are kept per project folder on this PC, in `devices.json` in the configurator's settings folder: host, SSH port and user, the last check and the last job. No password is ever kept.

## Adding a device

**Add device…** asks for the host name or address, and optionally the SSH user and port. A host that is an alias in `~/.ssh/config` takes its host name, user, port and key files from there; with no user anywhere, this PC's user name is used. Runtimes that announce themselves on the local network are listed under **Found on this network** with **Add**.

The first connection to a device shows its host key's fingerprint (`SHA256:…`); nothing is sent to the device before **Trust and connect**. To compare, run `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` on the device. Trusted keys are kept in the configurator's own `known_hosts` in its settings folder, not in `~/.ssh`. When a device later answers with another key, the connection is refused with the key it now shows; if the device was reinstalled, **Forget key** and connect again, otherwise do not connect.

The configurator logs in with the SSH agent and the default keys of this PC (`~/.ssh/id_ed25519` and the others ssh tries). When none works it asks for the SSH password, for that connection only. After a password login it offers **Use key login from now on**: it makes a key for this PC once (`canworks_ed25519` in the settings folder, readable by your user only) and adds its public key to the device user's `~/.ssh/authorized_keys`, unless it is there already. The next connections log in with it.

A connection stays open for two minutes after its last use, so checking a device and starting a job need one login.

## What the page shows

Picking a device checks it again (**Check again** does too). The check is a read-only script, `device-probe.sh` from the PC tools, run on the device through the SSH connection; it needs neither root nor canworks on the device and changes nothing. The page shows:

- a header line: system, architecture, free disk, internet access to github.com, and when the device was checked;
- one row per part: **OpenPLC Runtime** (native, managed Docker or a container of your own, its version and whether its HTTPS port answers), **canworks plugin** (version, the runtime version it was built for, on or waiting for an upload), **Modbus bridge** (version and its running bridges), **Remote link** and **CAN interfaces** (with bit rate, up or down, virtual interfaces and serial adapters), each with what the device has and what this project needs. Parts the project's target does not use are greyed and have no action;
- one main action, or **Up to date**;
- a running or last install job ([Install jobs](#install-jobs)).

| The device has | The main action |
| --- | --- |
| No OpenPLC runtime (OpenPLC project) | **Install OpenPLC Runtime and canworks X** |
| A runtime, no plugin | **Install canworks X** |
| A plugin older than the newest release X | **Update A → X** |
| A plugin built for another runtime version (the runtime was updated) | **Rebuild for runtime vN** |
| No bridge (bridge project) | **Install and start this project's bridge** |
| A bridge older than X | **Update A → X** |
| A current bridge without this project's saved config running | **Start this project's bridge** |

X is the newest `deploy-v` release, looked up on github.com from this PC (or from the device when this PC has no internet access), and the job installs exactly that version. When the PC tools are older than the canworks on the device, one line says so with how to update them; nothing is blocked or downgraded. **Options** under the main action has **Remote link** (`--with-link`, [remote-access.md](remote-access.md)) and **Found on the local network** (discovery), both on by default.

An action that cannot run is greyed with the reason: no systemd, the SSH user cannot use sudo, no internet access to github.com, less than 2 GB free, an install already running, or the newest release could not be found.

Each installed part has **Uninstall…** (the plugin with `install-runtime.sh --uninstall`, the bridge with `install-bridge.sh --uninstall`). The **Device** menu has **Remove everything…** (both, with `--purge`, and the remote link) and **Remove device**, which only forgets the device on this PC. The OpenPLC Runtime itself is never removed from here.

## Starting an action

An action asks once, and only for what stops or loses something: a plugin install or update on a managed Docker runtime ("The PLC stops and comes back without a program; upload it again afterwards."), a bridge update ("Running bridges restart."), installing the OpenPLC Runtime (names upstream's installer, `https://runtime.getedge.me`, which installs Docker too), and uninstalling. When the SSH user needs a password for `sudo`, the same dialog asks for it. A user that is root or has password-less sudo is never asked, and an action with nothing to confirm then starts at once.

A bridge action copies the saved config folder (the regular files next to `canworks.json`, at most 50 MB) to a temporary folder on the device and installs it as the bridge instance named after the project folder; the job removes the temporary folder. A bridge action with unsaved changes asks to save first.

## Install jobs

A job runs on the device by itself, as the systemd unit `canworks-install-<id>`, under the lock `/run/canworks-install.lock`, with its output in `/var/log/canworks-install/<id>.log` (the last five logs are kept, readable without root). It goes on when the SSH connection drops, the PC sleeps or the configurator stops. A second job while one runs, also from another PC, ends at once with "Another install is running on this device".

The page shows the steps the scripts announce, each with its time, the time so far and the time the last job of that kind took on this device, and the log folded. **Stop** stops the unit (what it changed so far stays). The status bar lists the job with **Show**. Opening the device again, also after the configurator was restarted, picks the job up from its log.

A failed job shows its exit status, its last 20 log lines and, for the failures the scripts name (no internet access, a full disk, apt locked by another program, no runtime found, the runtime's image changed), what to do.

When a job ends, the device is checked again and the page says what comes next: for the plugin, that canworks switches on with the next upload (the editor's **Build and upload**, or `canworks-deploy`) and, on a managed Docker runtime, that the PLC has no program until then; for the bridge, that it runs this project's saved config, with **Open in Commission**. The device becomes the project's runtime host under **Online access** when that was empty.

After **Install OpenPLC Runtime and canworks**, a runtime with no user asks for the first user's name and password (twice) and creates it through the runtime's API on the device itself. A runtime that has users is left alone.

## Other ways in

- **Online access** shows whether the runtime host is in Devices, with **Open in Devices** or **Install canworks on it…**.
- The connect panel's **Install canworks on a device…** under the runtime host.
- The **Modbus bridge** page's **Install on device…**.

## Security

- Passwords (SSH, sudo, the runtime's first user) are used for the one request that needs them and are written to no file, log, job log or browser storage. The sudo password reaches the device only on the standard input of `sudo -S`, checked alone first, so a wrong one never meets the job's commands.
- Host keys are trusted only after you saw them, and a changed key is never replaced by itself.
- The job runs the release's own scripts from `raw.githubusercontent.com/tonihoohoo/canworks/deploy-vX/scripts/` with `--version X`, as the one-line installs do.
- Nothing is saved to a device's non-volatile memory; the plugin and bridge install as their scripts do.

## Requirements

- The device: Linux with systemd, `curl`, `flock` and `sudo` (or root), reachable over SSH, with internet access to github.com and about 2 GB free for the build.
- The PC: the PC tools ([install-pc.md](install-pc.md)), which bring `paramiko` for SSH; no `ssh` command is needed.
