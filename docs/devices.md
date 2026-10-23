# Installing on a device from the configurator

The configurator's **Devices** workspace installs canworks on a Linux device over SSH: with a config open, what that project needs (for an OpenPLC project the OpenPLC Runtime on a fresh device and the Modbus bridge with the project's saved config, for a bridge project the bridge); with no config, what you pick for the device ([Without a config](#without-a-config)). It runs the same release script as the one-line install ([modbus-bridge.md](modbus-bridge.md#install)), always the newest release, and shows their progress step by step. A CODESYS project has nothing to install: the page says so.

**Configure | Commission | Devices** at the top of the page switches to it while a config is open, and **Install on a device** on the start page opens it with no config. The devices are kept once for this PC, in `devices.json` in the configurator's settings folder, and every project lists the same devices: host, SSH port and user, the last check and the last job. No password is ever kept.

Each device in the list says what it is to which project: **Runtime of line3** when it is the runtime host under **Online access** of the project `line3`, and **Bridge of packer** when its last check found the bridge instance `packer` (named after a bridge project's folder). With a config open, that project's devices come first and the others are greyed, but still usable.

## Without a config

**Install on a device** on the start page (or **Set up a Linux device** on the first run) opens Devices with no config: the header reads **Devices · no config**, and **Close** goes back to the start page. The parts table has no "This project" column. A device without the bridge asks **What should this device run?**:

- **OpenPLC PLC with canworks**: **Install OpenPLC Runtime and the bridge X** on a device with no runtime, **Install the bridge X** on one with a runtime. Build and upload the editor project afterwards, and put its config on the bridge from its Devices page.
- **Modbus bridge**: **Install the bridge X**, without a config. Open the bridge project and install it from its Devices page to start the bridge with that config.

A device that has the bridge gets its main action from what is installed (**Update A → X**, or **Up to date**), with no question. Uninstall, **Remove everything…** and the install jobs work as with a config. No project setting changes: the device becomes a project's runtime host only when an install runs with that project open.

## Adding a device

A device is any Linux computer this PC reaches over SSH. **Add device…** asks for the host name or address, and optionally the SSH user and port. A host that is an alias in `~/.ssh/config` takes its host name, user, port and key files from there; with no user anywhere, this PC's user name is used. Runtimes that announce themselves on the local network are listed under **Found on this network** with **Add**.

The first connection to a device shows its host key's fingerprint (`SHA256:…`); nothing is sent to the device before **Trust and connect**. To compare, run `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` on the device. Trusted keys are kept in the configurator's own `known_hosts` in its settings folder, not in `~/.ssh`. When a device later answers with another key, the connection is refused with the key it now shows; if the device was reinstalled, **Forget key** and connect again, otherwise do not connect.

The configurator logs in with the SSH agent and the default keys of this PC (`~/.ssh/id_ed25519` and the others ssh tries). When none works it asks for the SSH password, for that connection only. After a password login it offers **Use key login from now on**: it makes a key for this PC once (`canworks_ed25519` in the settings folder, readable by your user only) and adds its public key to the device user's `~/.ssh/authorized_keys`, unless it is there already. The next connections log in with it.

A connection stays open for two minutes after its last use, so checking a device and starting a job need one login.

## What the page shows

Picking a device checks it again (**Check again** does too). The check is a read-only script, `device-probe.sh` from the PC tools, run on the device through the SSH connection; it needs neither root nor canworks on the device and changes nothing. When the SSH user cannot read the managed Docker runtime's folder (`/var/lib/openplc-bootloader`, root's only) or use Docker, and `sudo` needs no password, it reads them through `sudo -n`; without that the runtime still shows as managed Docker, with no version. An old native `openplc-runtime` unit that is installed but stopped does not hide a managed Docker runtime. The page shows:

- a header line: system, architecture, free disk, internet access to github.com, and when the device was checked;
- one row per part: **OpenPLC Runtime** (native, managed Docker or a container of your own, its version and whether its HTTPS port answers; on a runtime other than the one canworks is pinned to, one grey line says so, for example "canworks runs on runtime v4.3.1; this device runs v4.3.2"), **Modbus bridge** (version and its running bridges), **Remote link** (and which config it serves), **Found on the local network** (the Avahi advertisement) and **CAN interfaces** (with bit rate, up or down, virtual interfaces and serial adapters), each with what the device has and what this project needs. Parts the project's target does not use are greyed and have no action;
- one main action, or **Up to date**;
- a running or last install job ([Install jobs](#install-jobs)).

| The device has | The main action |
| --- | --- |
| No OpenPLC runtime (OpenPLC project) | **Install OpenPLC Runtime and the bridge X** (`install-bridge.sh --with-openplc`: the pinned runtime, then the bridge with the project's saved config) |
| A runtime, no bridge (OpenPLC project) | **Install the bridge X** |
| No bridge (bridge project) | **Install and start this project's bridge** |
| A bridge older than X, or a development build | **Update A → X** |
| A bridge without its service (a partial install) | **Install the bridge X** or **Install and start this project's bridge** |
| A managed Docker runtime on another version than canworks' pinned v4.3.1 (moved from the OpenPLC Editor; OpenPLC project) | **Switch runtime to v4.3.1** (`install-bridge.sh --pinned-runtime`) |
| A current bridge without this project's saved config running | **Start this project's bridge** |

After the install the editor's **Build and upload** starts the PLC with the program and its Modbus settings. **Switch runtime** recreates the runtime container, so the program has to be uploaded again.

X is the newest `deploy-v` release, looked up on github.com from this PC (or from the device when this PC has no internet access), and the job installs exactly that version. When the canworks on the device has a newer major or minor version than the PC tools (a patch difference says nothing), one line says so with **Update PC tools…**: it checks for a newer release and offers the usual update (**Update now**, or the install command to copy where this copy cannot update itself); nothing is blocked or downgraded. **Options** under the main action has **Remote link** (`--with-link`, [remote-access.md](remote-access.md)) and **Found on the local network** (discovery), both on by default. A bridge install never moves a remote link that serves another config to this project's bridge: the option is then greyed and the link stays as it is.

An action that cannot run is greyed with the reason: no systemd, the SSH user cannot use sudo, no internet access to github.com, less than 2 GB free, an install already running, or the newest release could not be found.

The bridge has **Uninstall…** (`install-bridge.sh --uninstall`). The **Actions** menu has **Remove everything…** (the bridge with `--purge`, its configs and the remote link) and **Remove device**, which only forgets the device on this PC (for every project). The OpenPLC Runtime itself is never removed from here.

### Remote link and discovery

Once the bridge is on the device, the **Remote link** row has **Turn on…** or **Turn off…** (and **Start** when the link is installed but stopped), and **Found on the local network** has **Turn on…** or **Turn off…**. Each runs as a job with the release's `install-link.sh` ([remote-access.md](remote-access.md)), with and without a config open. The link serves the open project's bridge or the only bridge on the device; with several bridges and none of these, the dialog asks which one. Turning the link off keeps its key and paired PCs on the device, so turning it on again keeps the pairings, and the advertisement stays (without the link) when discovery is on. **Remove everything…** removes the key and paired PCs too. The CAN interfaces row is only shown: the bridge sets the interfaces up from the config.

In **Add device…** a wrong host, user or port is said under its field. A device that does not answer reads **Not reached**, with one sentence ("Can't reach 192.0.2.10 on SSH port 22.") and what to check: SSH on the device, the same network, the address and the port.

## Starting an action

An action asks once, and only for what stops or loses something: a bridge update ("Running bridges restart."), switching the runtime back to the pinned version (names both versions), installing the OpenPLC Runtime (names upstream's installer, `https://runtime.getedge.me`, which installs Docker, and the pinned runtime version it installs), and uninstalling. When the SSH user needs a password for `sudo`, the same dialog asks for it. A user that is root or has password-less sudo is never asked, and an action with nothing to confirm then starts at once.

A bridge action copies the saved config folder (the regular files next to `canworks.json`, at most 50 MB) to a temporary folder on the device and installs it as the bridge instance named after the project folder; the job removes the temporary folder. A bridge action with unsaved changes asks to save first.

## Install jobs

A job runs on the device by itself, as the systemd unit `canworks-install-<id>`, under the lock `/run/canworks-install.lock`, with its output in `/var/log/canworks-install/<id>.log` (the last five logs are kept, readable without root). It goes on when the SSH connection drops, the PC sleeps or the configurator stops. A second job while one runs, also from another PC, ends at once with "Another install is running on this device".

The page shows the steps the scripts announce, each with its time, the time so far and the time the last job of that kind took on this device, and the log folded. **Stop** stops the unit (what it changed so far stays). The status bar lists the job with **Show**. Opening the device again, also after the configurator was restarted, picks the job up from its log.

A failed job shows its exit status, its last 20 log lines and, for the failures the scripts name (no internet access, a full disk, apt locked by another program, no runtime found, the runtime's image changed), what to do.

When a job ends, the device is checked again and the page says what comes next: after the OpenPLC Runtime and the bridge are installed, or the runtime switched to the pinned version, that the editor project's **Build and upload** starts the PLC; for a project's bridge, that it runs this project's saved config, with **Open in Commission**; for a bridge installed with no config, that it starts with a config when that config's Devices page installs it there. The device becomes the project's runtime host under **Online access** when that was empty.

After **Install OpenPLC Runtime and the bridge**, a runtime with no user asks for the first user's name and password (twice) and creates it through the runtime's API on the device itself. A runtime that has users is left alone.

## Other ways in

- The start page's **Install on a device**, with no config ([Without a config](#without-a-config)).
- **Online access** shows whether the runtime host is in Devices, with **Open in Devices** or **Install canworks on it…**.
- The connect panel's **Install canworks on a device…** under the runtime host.
- The **Modbus bridge** page's **Install on device…**.

## Security

- Passwords (SSH, sudo, the runtime's first user) are used for the one request that needs them and are written to no file, log, job log or browser storage. The sudo password reaches the device only on the standard input of `sudo -S`, checked alone first, so a wrong one never meets the job's commands.
- Host keys are trusted only after you saw them, and a changed key is never replaced by itself.
- The job runs the release's own scripts from `raw.githubusercontent.com/tonihoohoo/canworks/deploy-vX/scripts/` with `--version X`, as the one-line installs do.
- Nothing is saved to a device's non-volatile memory; the bridge installs as its script does.

## Requirements

- The device: Linux with systemd, `curl`, `flock` and `sudo` (or root), reachable over SSH, with internet access to github.com and about 2 GB free for the build.
- The PC: the PC tools ([install-pc.md](install-pc.md)), which bring `paramiko` for SSH; no `ssh` command is needed.
