## Why

The explore of 2026-10-23 (`research/bridge-failure-hardening-2026-10-23.md`) tried failures against a running bridge: kill, hang, restart, client flood, abandoned connections, a missing interface, a taken port and a full disk. The bridge restarts fast (Modbus answers 0.3 s after a start with its cached files) and stays responsive under a read flood. Several gaps remain:

- **A hang is never restarted.** The unit has no watchdog and the bridge has none inside. A deadlock leaves a process that the kernel still accepts connections for, but that answers nothing and runs no network, for good.
- **systemd can give up.** `Restart=on-failure` with `RestartSec=2` and the default start limit (5 starts in 10 s) leaves the unit `failed` after a few fast failed starts: a taken port, a full disk, a broken config.
- **A full disk gives the wrong message.** Without its `.canworks/` cache (first start, new config, upload), the bridge refused to start on a full disk with "cannot run the EDS lint … the deploy tool must be installed next to canworks-bridge (rerun scripts/install-bridge.sh)".
- **A config upload is not atomic.** `put_config` copies files over the live ones with no temporary file, fsync or rename, and ignores copy errors. A power loss or full disk during an upload can leave a truncated `canworks.json` that is refused at every boot.
- **An upload can leave a bridge that runs nothing.** When neither the new nor the previous config starts, the process stays alive with no Modbus and no CAN, and systemd sees a healthy service.
- **The generated-file cache is not synced.** `inputs.hash` is written after `master.dcf` but nothing is fsynced, so after a power loss the hash could outlive a short DCF.
- **Nobody learns that the bridge crashed.** The status block's byte 7 is always 0, and the log of a new start does not say that the previous run ended without a stop.
- **Abandoned connections hold slots for 60 s.** There is no TCP keepalive, and a writer is refused when four dead connections from its own address fill `max_clients_per_address` (reproduced).

The restart replay of the control block and SDO request for PLC-link clients was found by the same explore and is fixed inside `modbus-connections`. It is not part of this change.

## What Changes

- **Stall watchdog in the bridge.** A supervisor thread checks that the 1 ms loop, the Modbus server and every network's bus thread make progress. When one has made none for 10 s, the bridge logs which one and aborts, so systemd or Docker's restart policy starts it again. It is paused while a config upload is being applied.
- **systemd readiness and watchdog.** The unit becomes `Type=notify` with `WatchdogSec=20s`. The bridge sends `READY=1` once its Modbus port is bound and `WATCHDOG=1` every second while the supervisor sees progress. No libsystemd is needed: it is one datagram to `NOTIFY_SOCKET`.
- **Restarts never give up.** The unit gets `Restart=always`, `RestartSec=1` and `StartLimitIntervalSec=0`.
- **Full or read-only disk named as such.** Before generating files the bridge checks that the config folder is writable and has room. A write that fails for that reason, the EDS lint's included, is reported as "no space left on …" or "… is read-only", with the free space, instead of the deploy-tool hint.
- **Atomic config upload.** Each uploaded file goes to a temporary name in the config folder, is fsynced and renamed into place, and the folder is fsynced. Every copy is checked; any failure puts the previous files back. When neither the new nor the previous config starts, the bridge exits with status 1 instead of idling.
- **Synced cache.** The generated DCF and concise DCF files are fsynced before `inputs.hash` is written.
- **Unclean stop is reported.** At start the bridge writes a run marker in `.canworks/` and removes it on a clean stop. When it finds a marker at start:
  - it logs that the previous run ended without a stop (crash, kill, hang or power loss);
  - the status block's byte 7 has bit 0 set for this run;
  - the diagnostics status has `last_stop: "unclean"`. It is `"clean"` otherwise, and `"unknown"` on the first start of a config.
- **Dead connections close sooner.** Modbus connections get TCP keepalive (idle 5 s, interval 2 s, 3 probes), so a peer that lost power is closed after about 11 s. When `max_clients_per_address` is reached and the newcomer may write, the bridge closes that address's longest-idle connection instead of refusing the writer, with a log line.
- **Docs.** `docs/modbus-bridge.md` gets a "When the bridge fails" section: crash, hang, restart, full disk and upload, what the PLC and the nodes see, and the unit settings. The status block table gets byte 7.

## Capabilities

### Modified Capabilities

- `modbus-bridge`:
  - Status block (byte 7 bit 0);
  - Clients and access (keepalive, writer per-address rule);
  - Bridge service limits (notify, watchdog, restart settings).
  - ADDED requirements: Stall watchdog, Unclean stop reported, Full or read-only config folder, Generated files survive a power loss.
- `canopen-online-diagnostics`: Config upload to the bridge (atomic replace, exit when nothing starts, `last_stop` in the status).

## Impact

- **Bridge:**
  - `plugin/src/bridge/bridge_main.cpp`: supervisor, sd_notify, marker, exit on a failed restore;
  - `bridge_host.cpp`: progress counters, atomic upload, `last_stop` and byte 7;
  - `bridge_blocks.cpp`: byte 7;
  - `modbus_server.cpp`: keepalive and the per-address writer rule;
  - `plugin/src/canopen/bus.cpp` and the J1939 and raw loops: a progress counter each;
  - `dcf_gen.cpp`: fsync before the hash; the space check and the EDS lint message.
- **Install:** `scripts/install-bridge.sh` writes the new unit. An update rewrites it and restarts running instances, as today.
- **Docker image:** unchanged. The stall abort plus `--restart unless-stopped` covers it.
- **PC tools:** `canworks-diag status` prints `last_stop`. Tools minor version bump.
- **Tests:**
  - C++ tests for the supervisor (a stalled loop aborts in a child process), byte 7 and the marker, keepalive options on accepted sockets, the per-address writer rule, and the upload's temp-and-rename with a failing write;
  - `test/bridge/install_test.sh` checks the unit's new lines;
  - a test that a full config folder (small tmpfs where the runner allows it, otherwise a read-only folder) gives the new message.
- **Order:** apply after `modbus-connections` merges, because both edit `bridge_host.cpp`. It does not depend on the mailbox changes; rebase over whichever of them lands first.
- **Hardware:** on the Linux device with node 23:
  - SIGSTOP the bridge: it is aborted and restarted, and node 23 is operational again;
  - kill -9: the restart time, and byte 7 bit 0 set;
  - `systemctl show` lists the new unit settings.
