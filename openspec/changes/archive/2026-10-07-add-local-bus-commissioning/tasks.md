## 1. Local backend core

- [x] 1.1 Add python-can and pyserial to `tools/deploy/pyproject.toml`, check that every dependency installs from a wheel or pure source on Windows, macOS (Intel, Apple silicon) and Linux (x86_64, ARM64), and record the result in the PR.
- [x] 1.2 Add `openplc_canopen_deploy/localbus/` with `adapter.open(spec, bitrate, listen_only=False, options)` (slcan, socketcan, pass-through, "adapter in use" and unknown-type messages, SocketCAN rate from an up link), a receive thread, the single `_transmit` path and the 1 s listen-before-first-transmit; verify with unit tests on python-can's `virtual` bus.
- [x] 1.3 Implement the SDO client (expedited and segmented upload and download up to 4096 bytes, toggle check, abort codes, timeout with abort, foreign-SDO wait); verify with a fake device in the tests (segmented read and write, aborts, timeout, a foreign request in between).
- [x] 1.4 Implement the listener (heartbeat, boot-up, EMCY ring of 16 per node, other-master detection from NMT, SYNC and foreign SDO requests) and the `status` and `emcy` results; verify with unit tests.
- [x] 1.5 Implement `nmt` (one node, never broadcast) and `scan`/`scan_status` with the plugin's algorithm and config comparison; verify with unit tests against several fake devices.
- [x] 1.6 Implement the LSS master ops (find with fastscan and optional vendor and product, inquire, set ID, set bit rate, store only with `store: true`, `force` while another master is seen, refuse IDs heard on the bus); verify with a fake LSS slave in the tests.
- [x] 1.7 Implement `trace_start`/`trace_fetch`/`trace_stop` (24-byte records, ring of 65536, filters, error frames, Tx flag, adapter or PC time stamps); verify that `bustrace` decodes and exports a local trace.
- [x] 1.8 Add `LocalBus` with `diag.Client`'s interface, the synthesized hello, the op table with `not available on a local adapter`, and the allow-changes gate; verify with unit tests that the gated ops refuse without it.

## 2. CLI

- [x] 2.1 Add `--adapter`, `--bitrate`, `--adapter-option`, `--allow-changes` and `--force` to `openplc-canopen-diag` (mutually exclusive with `--runtime`, no token, bit rate from `--config`/`--network`, no bit rate means exit 1), and the `adapters` command (pyserial ports with known slcan USB IDs plus python-can detection); verify with unit tests of option handling.
- [x] 2.2 Make the status printer show the local fields (adapter, bit rate, `other_master`, last heard) and leave out runtime-only columns; make `restore --hold-preop` send preop/start on a local adapter; verify with unit tests of the output.

## 3. Configurator

- [x] 3.1 Add the USB adapter target to online access (type, found ports with refresh, bit rate defaulting to the network's, "Allow changes" per connection, settings per project folder on this PC) and open `LocalBus` through the connection pool with the idle close; verify with server tests on the virtual bus.
- [x] 3.2 Hide the runtime-only fields and views on an adapter target, show the adapter banner with both bit rates when they differ and the other-master warning, and ask before LSS with `force`; verify with page tests.
- [x] 3.3 Add "Commission a device" on the start page (online pages without a config, EDS from the library match or picked, no "Add as node"); verify with page tests.

## 4. CI

- [x] 4.1 Run the virtual-bus tests in CI and in the PC tools job on all four runners.
- [x] 4.2 Add `test/localbus/run.sh` to the Linux vcan job: the simulated RTD module (`test/sensor_slave`, node 5) and `test/lss/lss_slave` on `vcan0`; status, scan, sdo-read and sdo-write, backup and compare, lss-find and lss-set-id, and a trace with pcapng export through `--adapter socketcan:vcan0`; then the parity step against the plugin's diagnostics channel on the same bus, and with the plugin running as master, `status` showing another master and `lss-find` refused without `--force`; verify green on the PR.

## 5. Docs and version

- [x] 5.1 Write `docs/pc-adapter.md`: which adapters, per OS port names and drivers (Windows 10/11 built-in CDC driver, macOS `/dev/tty.usbmodem*`, Linux `/dev/ttyACM*` and `dialout`, SocketCAN), first steps (adapters, status, scan, LSS, backup), the guest rules and another master, allow-changes and store, the limits (no NMT master, no PDOs, no simulator, one tool per adapter, untested pass-through types), and a pointer to the raw-frames and bit-rate commands once they exist.
- [x] 5.2 Update README ("On the engineering PC": commissioning with a USB adapter, no runtime needed; the configurator and diag bullets), `docs/install-pc.md` (adapter notes, the changed "only through the runtime" sentence), `docs/diagnostics.md` (`--adapter` options and the local differences table), `docs/configurator.md` (USB adapter target, Commission a device) and `docs/trace.md` (recording from a local adapter).
- [x] 5.3 Bump the PC tools version to the next free minor after what `main` carries when this is applied.

## 6. Hardware checks (manual)

- [x] 6.1 On the Pi with the PC tools installed with uv, the PLC stopped and the CANable opened through `--adapter slcan:/dev/ttyACM0`: `adapters`, `status`, scan finds the bench node, `sdo-read` of 0x1018, `backup` and `compare` with its EDS, a 30 s trace exported to pcapng, and `lss-inquire`. Afterwards the template project goes back on.
- [x] 6.2 Needs a second adapter on the same bus (the plugin holds the CANable's serial port while the PLC runs): with the template project running, the PC tools on the second adapter show another master in `status`, `lss-find --allow-changes` is refused without `--force`, and read-only SDO reads work while PDOs run. Left open if no second adapter is on the bench; 4.2 covers the same on vcan.
- [ ] 6.3 On a Mac and on a Windows PC with the CANable plugged in (the owner moves the adapter): the configurator's USB adapter target, scan, object dictionary view with watch, backup, and "Commission a device".
