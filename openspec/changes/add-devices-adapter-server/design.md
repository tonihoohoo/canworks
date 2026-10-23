## Context

`canworks-diag adapter-serve` (#165) serves a Linux device's CAN adapter to PCs: TLS with a certificate made at every start, a SCRAM-SHA-256 token login bound to it, and port 7536. `--install-service` writes `canworks-adapter-<if>.service`, which runs as the user who ran sudo with only CAP_NET_ADMIN, plus an Avahi file with `kind=adapter`. Only the token's verifier is stored, in that user's `~/.config/canworks/adapter-serve.json`, per port. The PC's connect panel already has **Adapter on another machine**. It keeps tokens per server in `online.json` (`adapter_tokens`, keyed by `remote.host_key`) and has the same **Allow changes** box as a USB adapter.

After devices-canworks-only (#283), the Devices page has four rows: Modbus bridge, Remote link, Found on the local network and CAN interfaces. It runs root jobs as `canworks-install-<id>` units, with their logs in `/var/log/canworks-install` (mode 0644), and uploads configs through `/tmp/canworks-bridge-upload.*`.

## Goals / Non-Goals

**Goals:**
- Turn an adapter server on, change it and turn it off from the device page, with and without a config, on a device with or without the bridge.
- No token copy-paste for the PC that turns it on, and no plain token on the device.
- One click from the device page to a connection that works like a USB adapter.
- Safe sharing of an interface with a running bridge.

**Non-Goals:**
- Carrying port 7536 over the remote link (iroh). That is a possible later change.
- A server-side choice of bit rate per PC. The bit rate stays the server's: a wrong rate from one PC would hit every PC on it.
- Changing the protocol, limits or login of `adapter-serve`.

## Decisions

**1. Its own row, not part of the Remote link row.** The remote link carries the bridge's diagnostics channel (7531) to paired PCs anywhere. It needs a bridge and a config, and it gives the config's online view. The adapter server is the bus itself on the local network. It needs neither, and it is meant for bench commissioning and devices without a config. Folding the two together would hide one behind the other. Alternative rejected: an action on the CAN interfaces row. The server has state of its own (running, PCs connected, permission), which needs its own line.

**2. Changes allowed on the server by default; read-only is each PC's choice.** Toni wants read-only by default, chosen while connecting, the same as for a USB adapter. The connect panel's **Allow changes** box (unticked by default) and Unlock…/Lock already give exactly that. A server started without `--allow-changes` would add a second lock that USB adapters don't have. So the dialog's **Allow changes from PCs** is ticked by default, and unticking it is for a device every PC must only read.

**3. The PC makes the token and uploads only the verifier.** The job log is readable by every user on the device, and a printed token would land in it. The configurator therefore makes the token (`diag.new_token`) and computes the verifier (`diag.token_verifier`). It uploads the verifier as a 0600 file in an upload folder and passes `--token-verifier-file`. The token goes into `online.json` under `remote.host_key(host, port)` before the job starts, so a failed job leaves a token that matches nothing. The next **Turn on…** simply replaces it. **Change…** passes no token option, so the stored verifier is kept. **New token…** uploads a new verifier and restarts the service. Alternative rejected: `--token-file` with the plain token, which would put the token on the device's disk, even if only for a moment.

**4. `install-adapter.sh` instead of growing `install-bridge.sh` or `install-link.sh`.** The adapter server needs the Python tools only: no Lely, no bridge build, and no iroh. The script uses `/opt/canworks/venv/bin/canworks-diag` when it is there (bridge with CANopen, or the link's venv). Otherwise it makes the venv and pip-installs `tools/deploy` with the release's constraints, as `install-bridge.sh` does. It then calls `canworks-diag adapter-serve --install-service --service-user U ...`. The job stays one line, like the link's. Steps: `1/2 Installing the PC tools` (skipped when present) and `2/2 Starting the adapter server on IF`.

**5. `--service-user` for root installs.** Jobs run as root via `systemd-run`, so there is no `SUDO_USER`. The SSH user becomes the service user, which is the same result as running the CLI with sudo from that user. The probe can then read the user's status file to show connected PCs, and the token's verifier stays in that user's settings. A serial adapter needs `dialout`, so the script adds the user to it. A root SSH login is refused for the service user, as on the CLI: the dialog says to log in as a normal user with sudo.

**6. Probe from the unit files.** `device-probe.sh` lists `/etc/systemd/system/canworks-adapter-*.service` and parses the `ExecStart` options with `sed`: `--adapter`, `--bitrate`, `--port`, `--allow-changes`. It gets each unit's state with `systemctl is-active`. When the `User=` home's `.config/canworks/adapter-serve-<port>.status.json` is readable, it passes that through. The probe stays read-only and needs no root. The plan shows `PCs connected` only when the status file was read.

**7. Bit rate sources and the shared interface.** The plan knows which interface this project's bridge uses (the open config's network adapter) and its bit rate. For that interface the dialog locks the rate. For other bridge instances the probe does not parse their configs: an interface that is up shows its rate from `ip -d`, and the dialog prefills that. The server already refuses an up interface at another rate. Sharing can0 with the bridge is fine at the SocketCAN level. The "another master is active" guard in the local bus then asks for force on writes, which is the right behaviour, and the dialog says so in one line. Serial adapters are exclusive, so the plan refuses them when a running bridge or server names that port.

**8. Port per interface.** The first server takes port 7536. A second interface takes the next free port from 7537 on, and the row shows it. Discovery advertises each server, so the connect panel finds them all.

## Risks / Trade-offs

- [The PC tools install on a small device takes a while (pip, wheels for python-can and cryptography)] → It is shown as a job step with the usual progress. Nothing is built from source, and the check is skipped when `canworks-diag` is already there.
- [A token kept on one PC only] → **Copy token** on that PC. **New token…** from any PC is the fallback, and its confirmation names the cost: other PCs must enter the new token.
- [Changes allowed by default on the server] → Each PC still starts read-only and must Unlock…, and the server keeps its limits and login back-off. Unticking **Allow changes from PCs** gives a read-only server.
- [The status file is unreadable when the SSH user is not the service user (another PC turned it on as another user)] → The row leaves out the PC count. It doesn't guess.

## Migration Plan

None. Servers installed by hand with `--install-service` are found by the probe and shown like the others. **Change…** keeps their token.

## Open Questions

None.
