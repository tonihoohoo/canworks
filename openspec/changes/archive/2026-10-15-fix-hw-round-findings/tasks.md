## 1. Fixes

- [x] 1.1 `pyproject.toml`: python-can's gs_usb extra on Windows as on macOS, and the `libusb` package on Windows; `localbus/adapter.py` `_libusb_path()` puts its DLL on the process PATH before pyusb looks (gs_usb open, `adapters`) (`test_localbus.py`: the PATH on a faked Windows)
- [x] 1.2 `localbus/adapter.py` `_gs_usb_drain()`: read and drop what the adapter holds before the channel starts (`test_localbus.py`)
- [x] 1.3 `localbus/core.py`: an error frame with no error on the wire (CRTL only, not passive) is not a bus error for the check, the burst rule or the error count; it stays in the trace (`test_localbus_check.py`: counters going down with traffic confirm the rate)
- [x] 1.4 `configurator/online.py` `fingerprints()`: rewrite slave EDS paths too, with `contract.eds_users` like `bundle.rewrite` (`test_configurator_online.py` on the virtual plant)
- [x] 1.5 `static/connection.js`: the connect panel leaves out empty parts (page test: no "null" in the first panel)
- [x] 1.6 `userdirs.replace_file()`: retry the rename on Windows for about a second, remove the temporary file when it still fails; used for `online.json`, `ui.json`, `recent.json` and notes files (`test_configurator_online.py`)
- [x] 1.7 `bustrace/decode.py`, `layouts.py`: SDO upload answers give the source "device", confirmed downloads "bus" (`test_trace_decoding.py`)
- [x] 1.8 Plugin: `NodeState::boots`, counted at each successful boot, in the status as `boots`; `static/nodes.js` logs "Booted" when it goes up (page test)

## 2. Docs and version

- [x] 2.1 `docs/pc-adapter.md` and `docs/install-pc.md`: gs_usb on Windows needs nothing else; `docs/diagnostics.md`: `boots`; `docs/trace.md`: layouts read in a trace; README
- [x] 2.2 Tools 0.69.0

## 3. Hardware

- [x] 3.1 Windows PC with the gs_usb adapter on the 500 kbit/s bench bus, the wheel installed with uv and nothing else: `adapters` lists it; 1000, 250 and 50 kbit/s refused and 500 kbit/s connects right after each; with the PLC running ten reads in a row all answer (2026-10-15, the branch installed with uv in a fresh environment: all as described, 10 of 10 reads)
- [x] 3.2 Silent bus (PLC stopped, the device without heartbeat): the probe confirms 500 and refuses 250 kbit/s, and 500 connects right after (2026-10-15: 250, 1000 and 125 refused, 500 confirmed after each)
- [ ] 3.3 Configurator on the virtual plant after an upload to the local simulator runtime: no "different configuration" note; node 6 reset from its Status tab logs "Booted"
- [x] 3.4 Pi redeploy and clean PLC start; the status gives `boots` (2026-10-15 from the branch: node 23 `boots` 1 after the start, 2 after a reset)
