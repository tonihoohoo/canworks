# Installing on a device from the configurator

The configurator's **Devices** workspace installs and controls the canworks parts of a Linux device over SSH: the Modbus bridge, its remote link and the local network advertisement. With a config open it installs and starts the bridge with the project's saved config; with no config it installs the bridge alone ([Without a config](#without-a-config)). It never installs, changes or removes anything that is not canworks: install the OpenPLC Runtime with [upstream's installer](https://github.com/Autonomy-Logic/openplc-runtime), and other client programs (Node-RED, an HMI) as their own docs say. It runs the same release script as the one-line install ([modbus-bridge.md](modbus-bridge.md#install)), always the newest release, and shows their progress step by step. A CODESYS project has nothing to install: the page says so.

**Configure | Commission | Devices** at the top of the page switches to it while a config is open, and **Install on a device** on the start page opens it with no config. The devices are kept once for this PC, in `devices.json` in the configurator's settings folder, and every project lists the same devices: host, SSH port and user, the last check and the last job. No password is ever kept.

Each device in the list has one line on its bridges from its last check: **This project's bridge** when the open project's bridge is on it, otherwise the running bridges by name and how many are stopped (for example "packer running · 1 stopped"). A bridge is a folder under `/etc/canworks-bridge/` named as `install-bridge.sh --instance` allows (letters, digits, `-` and `_`) with a `canworks.json`; copies such as `packer.bak` are not counted. With a config open, that project's devices come first and the others are greyed, but still usable.

## Without a config

**Install on a device** on the start page (or **Set up a Linux device** on the first run) opens Devices with no config: the header reads **Devices · no config**, and **Close** goes back to the start page. The parts table has no "This project" column. A device without the bridge gets **Install the bridge X**, without a config: open the project and install it from its Devices page to start the bridge with that config.

A device that has the bridge gets its main action from what is installed (**Update A → X**, or **Up to date**), with no question. Uninstall, **Uninstall canworks from the device…** and the install jobs work as with a config. No project setting changes: the device becomes a project's runtime host only when an install runs with that project open.

## Adding a device

A device is any Linux computer this PC reaches over SSH. **Add device…** asks for the host name or address, and optionally the SSH user and port. A host that is an alias in `~/.ssh/config` takes its host name, user, port and key files from there; with no user anywhere, this PC's user name is used. Runtimes that announce themselves on the local network are listed under **Found on this network** with **Add**, except a device already in the list, whether it was saved by its name (`plc1.local`) or its address.

The first connection to a device shows its host key's fingerprint (`SHA256:…`); nothing is sent to the device before **Trust and connect**. To compare, run `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` on the device. Trusted keys are kept in the configurator's own `known_hosts` in its settings folder, not in `~/.ssh`. When a device later answers with another key, the connection is refused with the key it now shows; if the device was reinstalled, **Forget key** and connect again, otherwise do not connect.

The configurator logs in with the SSH agent and the default keys of this PC (`~/.ssh/id_ed25519` and the others ssh tries). When none works it asks for the SSH password, for that connection only. After a password login it offers **Use key login from now on**: it makes a key for this PC once (`canworks_ed25519` in the settings folder, readable by your user only) and adds its public key to the device user's `~/.ssh/authorized_keys`, unless it is there already. The next connections log in with it.

A connection stays open for two minutes after its last use, so checking a device and starting a job need one login.

## What the page shows

Picking a device checks it again (**Check again** does too). The check is a read-only script, `device-probe.sh` from the PC tools, run on the device through the SSH connection; it needs neither root nor canworks on the device, changes nothing, and reads canworks' own parts only (no OpenPLC runtime, no Docker). The page shows:

- a header line: system, architecture, free disk, internet access to github.com, and when the device was checked;
- one row per canworks part: **Modbus bridge** (version and its running bridges), **Remote link** (and which config it serves), **Found on the local network** (the Avahi advertisement) **CAN interfaces** (with bit rate, up or down, virtual interfaces and serial adapters) and **Remote CAN adapter** ([below](#remote-can-adapter)), each with what the device has and what this project needs. Parts the project's target does not use are greyed and have no action;
- one main action, or **Up to date**;
- a running or last install job ([Install jobs](#install-jobs)).

Below 1000 px wide the device list sits above the device's page.

| The device has | The main action |
| --- | --- |
| No bridge (a project open, with or without an OpenPLC connection) | **Install and start this project's bridge** |
| No bridge (no config open) | **Install the bridge X** |
| A bridge older than X, or a development build | **Update A → X** |
| A bridge without its service (a partial install) | **Install the bridge X** or **Install and start this project's bridge** |
| A current bridge without this project's saved config running | **Start this project's bridge** |

The saved config runs on the device when every file a bridge action copies (see below) is there with the same SHA-256: an EDS or simulation file edited next to `canworks.json` also offers **Start this project's bridge**.

When another project's bridge runs on the device, the **Start** and **Update** confirmations name it and offer **Stop A and start B** (the main button: A is stopped and disabled first) or **Start next to A**, with a warning when both use the same Modbus listen port, diagnostics port or CAN interface (the device check reads these from each running bridge's config with `python3`; without it the confirmation names A only).

For a project with an OpenPLC connection, the editor's **Build and upload** then starts the PLC with the program and its Modbus settings.

X is the newest `deploy-v` release, looked up on github.com from this PC (or from the device when this PC has no internet access), and the job installs exactly that version. When the canworks on the device has a newer major or minor version than the PC tools (a patch difference says nothing), one line says so with **Update PC tools…**: it checks for a newer release and offers the usual update (**Update now**, or the install command to copy where this copy cannot update itself); nothing is blocked or downgraded. **Options** under the main action has **Remote link** (`--with-link`, [remote-access.md](remote-access.md)) and **Found on the local network** (discovery). For a new install both are on; an update or a reinstall keeps them as the device has them (the link only when it is installed, serving the bridge instance it serves now, and discovery only when the device advertises now), and the box is shown unfolded when one is off. A bridge install never moves a remote link that serves another config to this project's bridge: the option is then greyed and the link stays as it is.

An action that cannot run is greyed with the reason: no systemd, the SSH user cannot use sudo, no internet access to github.com, less than 2 GB free, an install already running, or the newest release could not be found.

The bridge has **Uninstall…** (`install-bridge.sh --uninstall`). The **Actions** menu has **Uninstall canworks from the device…** (the bridge with `--purge`, its configs, the remote link and the remote CAN adapter) and **Forget this device**, which only forgets the device on this PC (for every project). Nothing that is not canworks is removed.

### Remote link and discovery

Before a bridge config runs on the device, the **Remote link** row says it turns on once one runs there. Once the bridge is on the device, the **Remote link** row has **Turn on…** or **Turn off…** (and **Start** when the link is installed but stopped), and **Found on the local network** has **Turn on…** or **Turn off…**. Each runs as a job with the release's `install-link.sh` ([remote-access.md](remote-access.md)), with and without a config open. The link serves the open project's bridge or the only bridge on the device; with several bridges and none of these, the dialog asks which one. Turning the link off keeps its key and paired PCs on the device, so turning it on again keeps the pairings, and the advertisement stays (without the link) when discovery is on. **Uninstall canworks from the device…** removes the key and paired PCs too. The CAN interfaces row is only shown: the bridge sets the interfaces up from the config.

### Remote CAN adapter

The **Remote CAN adapter** row turns the device's CAN adapter into an [adapter on another machine](pc-adapter.md#an-adapter-on-another-machine): PCs on the local network commission through it as through a USB adapter, with no bridge and no config needed. It is there with and without a config open, also on a device without the bridge, and lists each adapter server with its interface, bit rate, port, whether it runs, whether it allows changes and the PCs connected (`can0 · 500 kbit/s · running · changes allowed · 1 PC connected`), or **off**.

- **Turn on…** (**Add…** for another interface) asks in one dialog for the interface, the bit rate (required and never guessed: this project's bridge's on that interface, and then fixed, else the interface's own rate when it is up, else the config's; a simulated network's kept adapter counts for none of these), **Allow changes from PCs** (on: each PC still connects read-only and unlocks changes for its own session, as with a USB adapter; off: no PC can make changes) and **Advertise on the local network**. The job runs the release's `install-adapter.sh`: it installs the release's adapter server file (`canworks-adapter-<version>.pyz`, one file of about 1 MB) in `/opt/canworks-adapter` when that version is not there yet, and the server as a service of the SSH user (a root login is refused; log in as a user with sudo). This PC downloads the script and the file and uploads them, so the device needs no internet access for the remote CAN adapter (only when this PC cannot download them does the job download them on the device); it needs Python 3.11 or newer and the `openssl` command, and the row says in one line which one is missing instead of offering **Turn on…**. The first server uses port 7536, another interface the next free port.
- The token is made on this PC and kept in its settings for that server, as **Adapter on another machine** keeps it; only its verifier goes to the device, so the token is in no file or log there. **Copy token** gives it to another PC; a PC without it has **New token…**, after which every other PC must enter the new one.
- **Connect from this PC** (also in the notice after the job) opens the connect panel on **Adapter on another machine** with the device filled in; with no config open it opens **Commission a CANopen device** first. One **Connect** then runs the bit rate check.
- **Change…** runs the server with other settings and the same token; **Turn off…** removes it and frees the interface.
- Next to this project's bridge on the same interface, the dialog says that the bridge is the master there: a PC with this project's config connects through the bridge, and a PC's changes through the adapter need force while the bridge runs. A serial adapter that this project's bridge uses cannot be served: a serial port has one user at a time.

In **Add device…** a wrong host, user or port is said under its field. A device that does not answer reads **Not reached**, with one sentence ("Can't reach 192.0.2.10 on SSH port 22.") and what to check: SSH on the device, the same network, the address and the port.

## Starting an action

An action asks once, and only for what stops or loses something: a bridge update ("Running bridges restart.") and uninstalling. When the SSH user needs a password for `sudo`, the same dialog asks for it. A user that is root or has password-less sudo is never asked, and an action with nothing to confirm then starts at once.

A bridge action copies the saved config folder (the regular files next to `canworks.json`, at most 50 MB) to a temporary folder on the device and installs it as the bridge instance named after the project folder; the job removes the temporary folder. A bridge action with unsaved changes asks to save first.

## Install jobs

A job runs on the device by itself, as the systemd unit `canworks-install-<id>`, under the lock `/run/canworks-install.lock`, with its output in `/var/log/canworks-install/<id>.log` (the last five logs are kept, readable without root). It goes on when the SSH connection drops, the PC sleeps or the configurator stops. A second job while one runs, also from another PC, ends at once with "Another install is running on this device".

The page shows the steps the scripts announce, each with its time, the time so far and the time the last job of that kind took on this device, and the log folded. **Stop** stops the unit (what it changed so far stays). The status bar lists the job with **Show**. Opening the device again, also after the configurator was restarted, picks the job up from its log.

The job downloads each release script to a file before running it, so a script that cannot be downloaded (no internet access, or a release that is gone) ends the job failed with "could not download SCRIPT VERSION". A failed job shows its exit status, its last 20 log lines and, for the failures the scripts name (no internet access, a full disk, apt locked by another program), what to do.

When a job ends, the device is checked again and the page says what comes next: for a project's bridge, that it runs that project's saved config as its instance (named so also when another project is open by then), with **Open in Commission** in that project; for a bridge installed with no config, that it starts with a config when that config's Devices page installs it there. The device becomes the project's runtime host under **Online access** when that was empty.

## Other ways in

- The start page's **Install on a device**, with no config ([Without a config](#without-a-config)).
- **Online access** shows whether the runtime host is in Devices, with **Open in Devices** or **Install canworks on it…**.
- The connect panel's **Install canworks on a device…** under the runtime host.
- The **Modbus bridge** page's **Install on device…**.

## Security

- Passwords (SSH, sudo) are used for the one request that needs them and are written to no file, log, job log or browser storage. The sudo password reaches the device only on the standard input of `sudo -S`, checked alone first, so a wrong one never meets the job's commands.
- Host keys are trusted only after you saw them, and a changed key is never replaced by itself.
- The job runs the release's own scripts from `raw.githubusercontent.com/tonihoohoo/canworks/deploy-vX/scripts/` with `--version X`, as the one-line installs do.
- Nothing is saved to a device's non-volatile memory; the bridge installs as its script does.

## Requirements

- The device: Linux with systemd, `curl`, `flock` and `sudo` (or root), reachable over SSH, with internet access to github.com and about 2 GB free for the build.
- The PC: the PC tools ([install-pc.md](install-pc.md)), which bring `paramiko` for SSH; no `ssh` command is needed.
