## 1. Local backend: gs_usb and echo frames

- [x] 1.1 `localbus/core.py`: skip received messages with `is_rx` False in `_handle` (no other master, heartbeat or answer from them); use them as send confirmation; record each sent frame once in the trace
- [x] 1.2 `localbus/core.py` `transmit`: wait up to 0.5 s for the echo where the adapter gives echoes; on timeout or a send exception, end the session with "adapter stopped sending"
- [x] 1.3 `localbus/adapter.py`: gs_usb timings from the device's timing limits with sample points 87.5, 85, 80 and 75 %; refuse a rate with no timing before touching the adapter
- [x] 1.4 gs_usb open, start and mode changes: set the channel to reset mode on any failure; EPIPE on open resets the USB device once and retries once, then "does not answer (USB stall): unplug it and plug it in again"; close resets the channel before releasing the interface
- [x] 1.5 gs_usb listen-only (`GS_CAN_MODE_LISTEN_ONLY` when the device has it) and one-shot (`GS_CAN_MODE_ONE_SHOT`) modes through the open path; add gs_usb to the adapters with listen-only where the device reports it
- [x] 1.6 Tests on python-can's virtual bus with a fake echoing adapter: own SDO requests do not raise other master, trace lists sent frames once, a missing echo ends the session

## 2. Local backend: bit rate check, bus errors, scan stop

- [x] 2.1 Bit rate check in `core.acquire` / Core start: listen phase verdict (traffic, errors), silent-bus probe (LSS inquire node ID, once, one-shot), node ID SDO check (`check_node`) for adapters without send confirmation; close the adapter on a refusal; `bitrate_check` in `hello` and `status`
- [x] 2.2 Bus errors end the session: bus-off, error passive, or 10 error frames in 1 s with no valid frame; stop scan, PDO test, SYNC, raw send and trace jobs; "connection ended: <reason>" to every handle
- [x] 2.3 `scan_stop` op and stop flag in `_scan_run`; end the scan at once on a transmit error or a closed session (`stopped`, `error`)
- [x] 2.4 `canworks-diag`: `--check-node N`; the check on every `--adapter` command; exit 1 with the check's reason
- [x] 2.5 Tests: wrong rate refused (error frames injected), busy bus confirmed without any frame sent, silent bus probe acknowledged / not acknowledged, `--check-node` with answer and abort, bus errors end the session, scan stop and scan ending on a transmit error; vcan test of the check against the standalone simulator

## 3. Remove bit rate detection

- [x] 3.1 Remove `localbus/sweep.py`, the `detect_bitrate` / `detect_bitrate_status` local ops, the lone-device guards and probes, and `adapter.unsupported_rates` / `retune` where nothing else uses them
- [x] 3.2 Remove the plugin's `detect_bitrate`, `detect_bitrate_status` and `detect_bitrate_stop` and their listen-only link and slcan helpers where nothing else uses them; the ops answer `unknown op`
- [x] 3.3 Remove `canworks-diag detect-bitrate`, `bitrate.py`'s sweep verdicts where unused, `test/fixtures/sweep_verdicts.json` and the sweep tests (plugin, PC tools, vcan scripts)
- [x] 3.4 Configurator server: remove `/api/online/adapter_detect*`, `detect_bitrate*` routes and the lone-device guard

## 4. Commission a CANopen device: layout and behaviour

- [x] 4.1 Side bar in commissioning: Bus and master, Nodes, Trace, Frame lab; no Online or Scan the bus page in this mode
- [x] 4.2 Bus and master tab: adapter list and Refresh, bit rate (no Detect, no "Only this device is on the bus"), node ID field for the check on adapters without send confirmation, Allow changes as a live toggle on the open connection, Connect / Disconnect, check result, bus state and counters, other master, log count and Save log; a refused check or ended connection shows its reason
- [x] 4.3 Server: Disconnect route closing the adapter target and its jobs; `AdapterTarget` keyed without `allow_changes` so the toggle updates the open connection; commissioning adapter settings in the configurator's own settings file
- [x] 4.4 Nodes tab: merged node table (heard, scanned, LSS, added), Scan the bus with progress and Cancel (`scan_stop`), Add node from EDS… (node ID + EDS, page only), unconfigured devices panel, node page with object dictionary, Parameters, PDO test, notes and "Add to a config…"
- [x] 4.5 Remove the Steps panel (`COMM_STEPS`, `stepDone`, `openStep`, `stepsPanel`) and keep the log calls
- [x] 4.6 Log kept per commissioning session: ask to save on Close and "Add to a config…" when there are unsaved entries, then clear; no log in config mode (`logBar` removed)
- [x] 4.7 Trace view: `onlineReady()` true on the commissioning adapter connection; recording and Send panel work there; mode-specific hint text
- [x] 4.8 Browser tests: commissioning layout, Disconnect, wrong rate message, Allow changes toggle without "another master", scan Cancel, Add node from EDS…, Trace record on the virtual adapter, log save prompt on leaving

## 5. Configurator (config mode)

- [x] 5.1 Online: remove the Runtime / USB adapter choice and the adapter form; runtime only; drop `target`, `adapter` and `adapter_bitrate` from per-project online settings
- [x] 5.2 Remove the PDO test tab and the commissioning log bar in config mode
- [x] 5.3 Remove the Scan the bus page (`nav-scan`, `renderScan`, `detectSection`, scan actions "Add as node" and "Use for node…") and its server routes for config mode; keep the code that "Add to a config…" uses
- [x] 5.4 Network picker in Online and Trace only
- [x] 5.5 CiA 402 axis switch: disabled with the reason unless the EDS has 0x6040 and 0x6041; enabled to switch off when `axis` is already set
- [x] 5.6 Browser tests: no adapter target or scan in config mode, CiA 402 switch disabled for an I/O EDS and enabled for a drive EDS

## 6. Remove program (firmware) download

- [x] 6.1 Schemas v1 and v2: remove `software_file` and `software_version` (unknown fields are rejected)
- [x] 6.2 Plugin: `plugin/src/can/config.{h,cpp}`, `plugin/src/canopen/dcf_gen.cpp` and `tools/canopen_check.cpp`
- [x] 6.3 PC tools: `contract.py` (`software_files`, checks), `bundle.py`, `project.py`, `cli.py`, `configurator/server.py` / `online.py`, `dcfexport.py`, `docexport.py`, `commissioning.py`, `_lely_dcf/dcfgen_cli.py`; the node page's Program download section
- [x] 6.4 Editor hook: `canworks_hook/snapshot.py`
- [x] 6.5 Tests and fixtures: `test/fixtures/config/cases.json` (unknown-field rejections), unit and sim tests, deploy, project, DCF export and snapshot tests

## 7. Docs and release

- [x] 7.1 `docs/pc-adapter.md` and `docs/configurator.md`: commissioning layout, bit rate check, Disconnect, no detection, config mode without USB adapter or scan, CiA 402 switch rule
- [x] 7.2 `docs/diagnostics.md`: remove the detection ops; `scan_stop`; `bitrate_check`; `--check-node`
- [x] 7.3 `docs/config.md`, `docs/deploy.md`, `docs/tour.md`: remove `software_file` / `software_version`
- [x] 7.4 README.md feature list and usage
- [x] 7.5 Version bump of the PC tools and plugin; CI path filters unchanged or narrower

## 8. Hardware checks (bench, when the Pi is reachable)

- [ ] 8.1 Mac with the gs_usb adapter on the 500 kbit/s bench bus: connect at 1000, 250 and 50 kbit/s is refused with the right reason, and 500 kbit/s connects right after without a replug
- [ ] 8.2 Same bench: with the PLC stopped and the device in PRE-OPERATIONAL without heartbeat, the silent-bus probe confirms 500 kbit/s and refuses 250 kbit/s, and the adapter keeps working afterwards
- [ ] 8.3 SDO reads and Allow changes on and off report no other master; Disconnect frees the adapter for `canworks-diag`
- [ ] 8.4 Scan the bus finishes in a few seconds, and Cancel stops it; Trace records in commissioning
- [ ] 8.5 Windows PC with the slcan adapter: `--check-node` path on a silent bus, wrong rate refused
- [ ] 8.6 Redeploy the plugin on the Pi; clean PLC start
