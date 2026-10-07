## 1. Plugin: raw frames

- [x] 1.1 Build the network's COB-ID map from the generated configuration at session start (NMT, SYNC, TIME, EMCY, PDOs both directions, SDO channels, heartbeats, LSS; slave networks: the slave's own) with a lookup that names the use; verify with unit tests on the example configs, including a slave network.
- [x] 1.2 Add `frame_tx.{h,cpp}`: per-network raw send socket opened on first use in the diagnostics thread (virtual bus tap on simulated networks), single sends with a per-client token bucket (50/s), cyclic jobs (10-60000 ms, count, 10-minute cap, max 8 per network) on monotonic deadlines, jobs ended on disconnect and on write errors with the reason kept 60 s; verify with unit tests on a fake socket.
- [x] 1.3 Add `send_frame` and `send_frame_stop` to `diag.cpp` with field validation, `allow_changes`, the `force` cases (COB-ID map, OPERATIONAL node or slave) with reasons, logging with the client address, and `send_jobs` in `status`; verify with diag protocol unit tests.

## 2. Plugin: bit rate detection

- [x] 2.1 Add `LinkOps::set_listen_only` (rtnetlink `IFLA_CAN_CTRLMODE`, `CAN_CTRLMODE_LISTENONLY`) and a sweep helper that sets rate + listen-only, listens on a raw socket with error frames, counts frames/errors/identifiers, and always restores the configured rate without listen-only; verify the link call sequence, including `EOPNOTSUPP` and an unplugged adapter mid-sweep, with mocked `LinkOps`.
- [x] 2.2 Let `Bus` run a requested sweep between sessions (end the session as the supervision tick does, sweep, restore, then the normal `prepare()` + session loop), with progress and the result held for `detect_bitrate_status`; verify with a unit test on a fake adapter and that other networks keep running in a two-network test.
- [x] 2.3 Add `detect_bitrate` and `detect_bitrate_status` to the diagnostics hub, served without a session; refusals for `allow_changes`, OPERATIONAL without `force`, vcan and simulated networks, `configure_link: false`, missing interface; "no bus" for other ops during a sweep; `bitrate_sweep` in `status`; the verdict rules of design D5; verify with unit tests of the verdict and the refusals.

## 3. PC tools

- [x] 3.1 Add `send`, `send-stop` and `detect-bitrate` to `openplc-canopen-diag` with the options of the spec, `--network`, progress and table output, exit codes, and the "plugin too old" message on `unknown op`; verify with CLI tests against a fake diag server.
- [x] 3.2 Configurator: Send panel in the Trace view (single, cyclic, jobs list, sent list, "Send this frame" from a trace row, force confirmation, disabled without `allow_changes`, jobs stopped when leaving the view) and Detect bit rate on the Scan page (warning and confirmation, progress, table, verdict, "Use N kbit/s" setting the field unsaved); verify with configurator API and headless page tests against a fake diag server.
- [ ] 3.3 Bump the deploy tool minor version.

## 4. CI

- [ ] 4.1 vcan test: a frame sent with `send_frame` arrives on a second socket and in a trace as Tx; a cyclic job with count sends exactly that many; disconnect ends a job; an identifier from the map is refused without `force`; `detect_bitrate` on vcan is refused and the session goes on.

## 5. Docs

- [x] 5.1 `docs/diagnostics.md`: the new ops, fields and refusals in the protocol table, the commands, the guards in Security, and how detection works (listen-only, what the nodes see, `silent` and the power-cycle hint, drivers without listen-only).
- [x] 5.2 `docs/trace.md` (sending frames while recording), `docs/configurator.md` (Send panel, Detect bit rate), README (Online features and `openplc-canopen-diag` commands).

## 6. PC-direct backend (needs add-local-bus-commissioning merged; otherwise moved to a follow-up)

- [ ] 6.1 Implement `listen_only` in `localbus.adapter.open` for slcan (`L`), PCAN and SocketCAN (link setting, clear refusal without CAP_NET_ADMIN), refusing for adapters without it; verify with unit tests on fakes per adapter type.
- [ ] 6.2 Add `send_frame`, `send_frame_stop`, `detect_bitrate`, `detect_bitrate_status` to the `LocalBus` op table through `_transmit`, with the guards of design D9 and the shared verdict; verify on python-can's `virtual` bus and with a verdict parity test against the plugin's cases.
- [ ] 6.3 "Detect" next to the bit rate in the configurator's adapter connection dialog; verify with a page test against a fake local bus.

## 7. Hardware check

- [ ] 7.1 On the bench (Pi, CANable slcan, one real node): send an SDO upload request for 0x1018:1 by hand to the node with nothing OPERATIONAL and see the answer in a configurator trace; check that a frame on the node's RPDO COB-ID needs force; run a 100 ms cyclic frame for 10 s and stop it.
- [ ] 7.2 Set `adapter.bitrate` to a wrong rate, upload, and run Detect bit rate from the configurator: the node's real rate is detected (power-cycle the node during the sweep if it is silent while unconfigured), "Use N kbit/s", save and upload boots the node. Confirm that slcan accepts listen-only on the Pi's kernel and that the sweep sends nothing (trace from a second adapter if available).
- [ ] 7.3 Put the bench config back and check the node boots.
- [ ] 7.4 When section 6 is in: run 7.1 and 7.2 again from the PC with the USB adapter directly (no runtime).
