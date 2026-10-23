## Context

canworks-bridge is one process with these threads:
- a 1 ms loop: snapshot, blocks, watchdog, mailboxes;
- a Modbus server thread: poll() with a 1 s timeout;
- one bus thread per network: the Lely loop in slices for CANopen, and the J1939 and raw loops;
- the diagnostics server.

The loop and the Modbus thread share `exchange_mu_`, so a stall in one usually stalls both. It runs under systemd (`canworks-bridge@NAME`) or in Docker (`--restart unless-stopped`). Measured in the explore:
- start to Modbus: 0.28 s with the cache, 0.78 s with dcfgen;
- RSS 12 MB, 5 threads for one network.

## Goals / Non-Goals

**Goals:** a stuck bridge restarts by itself on both routes; a restart is never given up; disk and upload failures leave the device able to start with a known-good config, with a message that names the cause; the PLC and the operator can tell that the bridge restarted after a crash.

**Non-Goals:**
- node safe states and defaults (that is `safe-node-defaults`);
- automatic fallback to the previous config at boot: a refused config stays refused and visible;
- core dumps;
- the restart replay of the control block and SDO request (fixed in `modbus-connections`).

## Decisions

**Progress counters, one supervisor.**
- Each watched thread bumps an atomic counter once per iteration: the loop every 1 ms, the Modbus thread after each poll() (at most 1 s), each bus thread once per slice.
- The supervisor thread wakes every 500 ms. A counter that has not moved for 10 s is a stall. The bridge then logs `canworks-bridge: <thread> made no progress for 10 s; aborting so the service restarts` and calls `abort()`.
- 10 s is far above any normal pause: the Lely loop slice is short, poll() is 1 s, and an SDO timeout runs on timers, not by blocking.
- Alternative considered: only systemd's `WatchdogSec` kicked from the loop. Rejected because it does not cover Docker, does not see a stuck bus thread, and its kill gives no reason in the log.

**sd_notify without libsystemd.** A dozen lines: `socket(AF_UNIX, SOCK_DGRAM)` and `sendto` to `$NOTIFY_SOCKET`, with the abstract-namespace `@` handled. It does nothing when the variable is unset (Docker, tests). The supervisor sends `WATCHDOG=1` each second only while every counter moved within the last 3 s, so systemd's `WatchdogSec=20s` is a backstop for a stuck supervisor and never fires before the bridge's own abort with its log line. `READY=1` is sent after `host.start()` returns true.

**Upload apply pauses the supervisor.** `apply_upload` stops everything and starts again, possibly running dcfgen for seconds. While it runs, the supervisor watches nothing but keeps sending `WATCHDOG=1` from its own thread. A start that never returns is caught by systemd's watchdog after 20 s.

**Unit settings.**

```
[Unit]
StartLimitIntervalSec=0
[Service]
Type=notify
NotifyAccess=main
WatchdogSec=20s
Restart=always
RestartSec=1
```

`Restart=always` also restarts an exit with status 0 that systemd did not ask for. A stop through `systemctl stop` is never restarted. The existing `MemoryMax` and `TasksMax` stay.

**Atomic replace.**
- For each staged file: write `<dir>/.<name>.canworks-new`, fsync it, `rename()` it over `<dir>/<name>`, then fsync `<dir>` once at the end. The backup to `.canworks-previous/` uses the same routine.
- Any failed write, rename or backup puts back every file already replaced and answers the upload as rejected, naming the file and errno.
- When neither the new nor the restored config starts, the bridge logs both and exits 1, and the unit's `Restart=always` retries on the restored files.

**Disk checks.**
- Before generating files, `statvfs` on the config folder: fewer than 1 MiB free, or a read-only mount, is reported before the lint runs: "no space left in /etc/canworks-bridge/line1 (212 KiB free); the bridge writes its generated files there". The check runs only when the cache must be regenerated; with a valid cache the bridge starts as today.
- An EDS lint or dcfgen run that fails while the folder is full gets the same message instead of the deploy-tool hint.

**Run marker.**
- `.canworks/running`, written and fsynced after a successful start and removed in `stop()` on SIGTERM or SIGINT.
- It lives on the config folder's disk, not in `/run`, so a power loss is caught too.
- A marker found at start sets `last_stop` to `"unclean"` for the whole run. No `.canworks/` folder at all means `"unknown"`.
- It costs one small write per start, never per cycle.

**Byte 7 bits.** Bit 0 is "the previous run did not stop cleanly". Bits 1-7 stay 0 here; `safe-node-defaults` takes bit 1 for "a CAN bus is not ok".

**Keepalive and the per-address rule.**
- `SO_KEEPALIVE` with `TCP_KEEPIDLE` 5, `TCP_KEEPINTVL` 2 and `TCP_KEEPCNT` 3 on accepted sockets.
- When a writer arrives and its address already has `max_clients_per_address` connections, the bridge closes the one with the oldest last complete request, with the log line `closing <peer>: to make room for writer <peer>`, as the existing `max_clients` rule does.

## Risks / Trade-offs

- **A false stall abort is itself an outage** (a short one, with a restart). The 10 s threshold and per-thread naming keep it rare and diagnosable. Tests run the supervisor with a short threshold in a child process.
- **`Restart=always` restarts a bad config forever, about once a second.** Each start logs the check's messages; journald's rate limit keeps the log bounded. This is preferred over a silent `failed` unit.
- **fsync on an SD card costs milliseconds per file.** It happens only at upload and cache regeneration.
