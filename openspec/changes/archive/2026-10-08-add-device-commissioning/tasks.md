## 1. Write configuration (PC side)

- [x] 1.1 Add `commissioning.py`: the plan from a config node (`dcfexport.plugin_downloads`, command objects dropped with reasons, 0x1020 stamp kept) and from a DCF (writable `ParameterValue` entries, `$NODEID` resolved, left-out list); verify with unit tests on the fixture EDS files and an exported DCF.
- [x] 1.2 Sort DCF writes into PDO sequences (off, sub 0 = 0, entries, sub 0 = n, comm entries, COB-ID), skip read-only comm entries and fixed mappings; verify with unit tests that a DCF and the same config node give the same sequence.
- [x] 1.3 Implement the device read, differs/same, identity and node ID checks, the runtime refusal for a configured node (from `status`), hold and return to the previous state, failure handling inside a sequence, read-back and the result; verify with unit tests against a fake device on python-can's virtual bus.
- [x] 1.4 Implement `--store`, `--restore-defaults`, `--verify-only` and the `restore-defaults` command; verify with unit tests that 0x1010 is not written after a failed write and that neither object is written without the option.

## 2. CLI

- [x] 2.1 Add `configure NODE (--from-node N --config FILE [--network NAME] | --dcf FILE) [--dry-run] [--yes] [--no-hold] [--ignore-identity] [--store [--store-subindex N]] [--restore-defaults] [--verify-only]` and `restore-defaults NODE [--subindex N] [--reset] [--yes]` to `openplc-canopen-diag`, for runtime and adapter; verify with unit tests of option handling and the printed plan.
- [x] 2.2 Add `detect-bitrate --lone-device [--probe lss|sdo:NODE]` and `pdo-test NODE [--config FILE] [--sync MS] [--set NAME=VALUE ...] [--repeat MS] [--duration S] [--force]` (prints TPDO values live, stops on Ctrl-C); verify with unit tests.

## 3. Local adapter

- [x] 3.1 Add the lone-device mode to `localbus/sweep.py` (normal-mode open per rate, probe at half time, guards on another master and several node IDs, warning on several IDs at the detected rate, `only on a USB adapter` answer from the runtime client path); verify with unit tests using a mocked opener that records the open mode and the frames sent.
- [x] 3.2 Add the PDO test ops (`pdo_test_start/set/status/stop`) and the SYNC producer (`sync_start/stop`) to `LocalBus` through the single transmit path, with the allow-changes and another-master guards and stop on connection close; verify with unit tests against a fake device that answers RPDOs with TPDOs.
- [x] 3.3 Build the PDO layout from the config or by reading the device's PDO objects, names and types from the EDS; verify with unit tests for a configurable and a fixed-mapping fixture.
- [x] 3.4 Fix the listen-only sweep's `silent` result to carry the lone-device hint; verify with a unit test.

## 4. Configurator

- [x] 4.1 Write configuration dialog (DCF or config node source, plan with grouped PDO sequences and marked comm writes, ticks with their defaults, progress, Cancel, result with read-back, Verify) as a configurator job like restore; verify with server and page tests.
- [x] 4.2 Restore defaults… button with reset option; verify with page tests.
- [x] 4.3 PDO test tab on adapter targets (layout source, live TPDO values, RPDO inputs and Send, NMT Start, SYNC period, stop on leave, force question); verify with page tests on the virtual bus.
- [x] 4.4 "Only this device is on the bus" in both Detect places, with confirmation and the hint on `silent`; verify with page tests.
- [x] 4.5 Steps panel and commissioning log with Save log in Commission a device, and "Add to a config…"; verify with page tests, including the accessibility audit the browser tests run on every view.

## 5. CI

- [x] 5.1 Add `test/commissioning/run.sh` to the Linux vcan job: the standalone simulator with a configurable fixture device on `vcan0`; configure from a config node and from its exported DCF through `--adapter socketcan:vcan0`, dry run, PDO remap, identity and node ID refusals, `--verify-only` after a simulated power cycle with and without store, `restore-defaults --reset`, a PDO test round trip with SYNC, and the runtime refusal for a configured node through the plugin's channel; verify green on the PR.

## 6. Docs and version

- [x] 6.1 `docs/pc-adapter.md`: a commissioning walk-through for one device (bit rate, LSS, identity, write configuration, PDO test, store, verify, back up), the lone-device sweep and its bench-only warning, the PDO test and the SYNC exception to the guest rules.
- [x] 6.2 `docs/diagnostics.md` (`configure`, `restore-defaults`, `detect-bitrate --lone-device`), `docs/configurator.md` (Steps, log, Add to a config, Write configuration, Restore defaults, PDO test, lone-device Detect), README feature lists.
- [x] 6.3 Bump the PC tools version to the next free minor after what `main` carries when this is applied.

## 7. Hardware checks (manual)

- [ ] 7.1 Lone device: with the PLC's CANopen stopped and only the bench device and one adapter on the bus (any second adapter's interface down), `detect-bitrate` without `--lone-device` reports `silent` with the hint, and `--lone-device` detects the device's rate; then with `--probe sdo:NODE`. The device runs normally afterwards.
  - Partly passed 2026-10-09 on a gs_usb adapter: `--lone-device --rates 500` and `--rates 500,250` detect 500 kbit/s and the device runs normally afterwards. Open: `--probe sdo:NODE`, and the non-lone sweep (needs a listen-only adapter). A sweep step at 1000 kbit/s leaves gs_usb on macOS deaf until replugged (follow-up).
- [x] 7.2 On the bench device from the PC tools on an adapter: back it up, `configure` from a config node with a changed TPDO event timer and a startup SDO, read-back verified, PDO test shows its TPDO values, power-cycle without store and `--verify-only` lists the differences, then `restore` from the backup (nothing is stored on the device in this test).
  - Passed 2026-10-09 on a gs_usb adapter at 500 kbit/s. An NMT reset stood in for the power cycle. `restore --include-comm` writes no PDO objects, so the reset is what undid the PDO changes (follow-up).
- [x] 7.3 Configurator on a PC with the adapter: Commission a device through the Steps panel, Save log, Add to a config.
  - Passed 2026-10-09 on a gs_usb adapter (Bit rate step skipped, rate known; device without LSS).
