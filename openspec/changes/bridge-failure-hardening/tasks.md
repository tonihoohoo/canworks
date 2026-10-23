## 0. Order

- [ ] 0.1 Apply only after `modbus-connections` is merged and archived (both edit `bridge_host.cpp`; that change also fixes the restart replay for PLC-link clients, which this change leaves out). Rebase on main and re-validate.
- [ ] 0.2 Independent of `faster-mailboxes`, `add-nodered-blocks` and `mailboxes-on-demand`: rebase over whichever of them lands first. When `mailboxes-on-demand` has merged, put `last_stop` next to its `bridge.mailboxes` status part.
- [ ] 0.3 `safe-node-defaults` takes status byte 7 bit 1 after this change; keep bits 1-7 at 0 here.

## 1. Supervisor and systemd

- [x] 1.1 Progress counters: 1 ms loop, Modbus server thread (after each poll), each CANopen bus thread (per loop slice), J1939 and raw loops
- [x] 1.2 Supervisor thread in `bridge_main.cpp`: 500 ms tick, 10 s stall → error log naming the thread → `abort()`; paused around `apply_upload`; threshold settable for tests only
- [x] 1.3 sd_notify without libsystemd (`NOTIFY_SOCKET`, abstract `@` names, no-op when unset): `READY=1` after start, `WATCHDOG=1` each second while every counter moved within 3 s, also during an upload apply
- [x] 1.4 Unit in `install-bridge.sh`: `StartLimitIntervalSec=0`, `Type=notify`, `NotifyAccess=main`, `WatchdogSec=20s`, `Restart=always`, `RestartSec=1`; `test/bridge/install_test.sh` checks the lines
- [x] 1.5 C++ tests: a stalled loop aborts in a child process with the thread named; a 2 s pause does not; notify datagrams arrive on a test socket

## 2. Disk and upload

- [x] 2.1 `apply_upload`: temp + fsync + rename per file, folder fsync, backup the same way, every step checked, roll back on failure, answer names file and errno
- [x] 2.2 Neither config starts → log both, exit 1 from `main`
- [x] 2.3 `dcf_gen.cpp`: fsync master DCF and concise DCF files before writing `inputs.hash`
- [x] 2.4 Space and read-only check before regenerating (statvfs, 1 MiB); lint/dcfgen failure on a full or read-only folder gets the disk message, not the deploy-tool hint
- [x] 2.5 Tests: upload with an injected write failure keeps the previous files; full folder (the free-space floor raised for the test with `CANWORKS_TEST_MIN_FREE_BYTES`, so no disk is filled) gives the disk message; cached config starts on a full folder

## 3. Unclean stop

- [x] 3.1 Run marker `.canworks/running` written and fsynced after start, removed on SIGTERM or SIGINT stop; warning log when found at start
- [x] 3.2 Status block byte 7 bit 0; status JSON `last_stop`; `canworks-diag status` prints it
- [x] 3.3 Tests: clean stop → 0 and `clean`; killed → 1 and `unclean`; first start → `unknown`

## 4. Modbus connections

- [x] 4.1 `SO_KEEPALIVE`, `TCP_KEEPIDLE` 5, `TCP_KEEPINTVL` 2, `TCP_KEEPCNT` 3 on accepted sockets
- [x] 4.2 Writer at its address's limit closes that address's longest-idle connection, with a log line
- [x] 4.3 Tests: the keepalive options are set on an accepted socket; four idle connections plus a writer from the same address

## 5. Docs and release

- [x] 5.1 `docs/modbus-bridge.md`: "When the bridge fails" section (crash, hang, restart, full disk, upload; what the PLC and the nodes see; unit settings; link to `safe-node-defaults`' node settings once merged); status block byte 7; Clients and access text; README only if a user-visible line there changes
- [x] 5.2 Tools minor version bump (release notes are a template; nothing per version)
- [ ] 5.3 State CI wall time and summed job time against the baseline in the PR

## 6. Hardware (Linux device with node 23; needs the coordinator's OK on the Pi and Toni's typed go)

- [ ] 6.1 Install the new unit; `systemctl show` lists notify, the watchdog, `Restart=always`, the 1 s delay and no start limit
- [ ] 6.2 `kill -9` the bridge: time until Modbus answers and node 23 is operational again; status byte 7 bit 0 set; `canworks-diag status` says unclean
- [ ] 6.3 `kill -STOP` the bridge for 15 s: the stall abort (or systemd's watchdog) restarts it, and node 23 runs again
- [ ] 6.4 Clean PLC start afterwards
