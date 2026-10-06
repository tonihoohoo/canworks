## 1. Library check (first, decides the route)

- [x] 1.1 In OpenPLC Editor 4.3.2, create a project with the current generator from a config with one drive node, add `drive : AXIS_REF_SM3; drive_bridge : SM_Drive_GenericDS402;` and an `MC_Power` call by hand, and run Build only for OpenPLC Runtime v4. Record whether the built-in PLCopen SoftMotion library resolves without an EtherCAT device. If it does not, stop and update design decision 1 to the own-library fallback before going on.
  Result: checked from the editor's source (bundled libraries are always loaded, `libs/plcopen-softmotion.stlib`) and by compiling the generated `main` with STruC++ v0.7.0, which resolves `AXIS_REF_SM3`, `SM_Drive_GenericDS402` and the `MC_*` blocks without EtherCAT. The Build only click in the editor's GUI is still open as 8.2.
- [x] 1.2 Fetch the STruC++ v0.7.0 release in a script (`scripts/fetch-strucpp.sh`, version in one place, cached, never committed) and compile a minimal ST file using `MC_Power` against its built-in libraries.

## 2. Config contract

- [x] 2.1 Add `axis` (`scale_numerator`, `scale_denominator`, `scale_factor`) to `schema/canopen.v1.schema.json` and `docs/config.md`.
- [x] 2.2 Plugin config parser: accept `axis` as a known node field (no warning, no behaviour change); unit test.
- [x] 2.3 Deploy tool contract checks: standard objects by direction and IEC type, duplicates, 0x6040/0x6041 required, `status_location` required, scaling values; warnings for device type not 402 and target without 0x6060; tests.

## 3. Fixtures and example

- [x] 3.1 New made-up drive EDS `servo402.eds` (device type 0x00020192, all eleven standard objects, 0x6083/0x6084, 0x6098/0x6099/0x609A, writable mapping, heartbeat) written by `config/cia402-drive/make_eds.py`; check it passes the EDS lint and banned-word guard.
- [x] 3.2 `config/cia402-drive/canopen_config.json` with one axis node, startup SDOs for ramps and homing method, and `drive_demo.st` (power, home, absolute move, velocity, halt, fault reset); `README.md`.

## 4. Editor project generator

- [x] 4.1 `editorproject.py`: axis and bridge declarations and the generated body lines per axis node, binding only mapped objects; tests for the axis, velocity-only and no-axis cases (existing output unchanged without axes).
- [x] 4.2 Share the generated lines with the configurator's declarations panel.

## 5. Configurator

- [x] 5.1 "CiA 402 axis" switch with scaling fields, status bit requirement and suggestion, profile-402 note; errors and warnings on the node.
- [x] 5.2 "Map CiA 402 objects": map what the EDS allows into free PDO entries with suggested locations, list what does not fit, fixed-mapping case; page tests.
- [x] 5.3 Axis lines in the declarations panel; page test.

## 6. Tests

- [x] 6.1 `test/cia402/drive_model.st`: ST CiA 402 drive model (power state machine, mode display, profile position handshake, profile velocity, homing, fault input).
- [x] 6.2 ST tests run with STruC++ v0.7.0 against the example's generated `main`: power on, absolute move done, velocity reached, fault and reset, status bit FALSE gives error stop. Add to CI (a `tools` shard or own job, with the fetch cached).
- [x] 6.3 `test/drive/cia402_slave.hpp`: Lely slave from `servo402.eds` with the same CiA 402 behaviour.
- [x] 6.4 `sim_cia402_demo` (instead of a `canopen_host` mode on vcan): the demo program compiled by STruC++ runs as the PLC program against the drive slave on the virtual bus through the real master; power on, home, move, velocity, halt, fault and reset, lost drive. Built in CI with `-DSTRUCPP` and `CANOPEN_REQUIRE_STRUCPP=1`.
- [x] 6.5 Library behaviour found by the tests and handled in the demo and docs: Execute is level-held; an idle block still writes controlword bits; homing mode selected before `MC_Home`; `MC_MoveAbsolute.Done` trusted only after `Busy`; fault reset retried on a new rising edge.

## 7. Docs and release

- [x] 7.1 `docs/cia402.md`: what is supported (profile position, velocity, homing), PDO layout and transmission types, scaling, one-scan latency, library limits, homing and ramps via startup SDOs, editor version needed; links from README, `docs/config.md` and `docs/configurator.md`.
- [x] 7.2 Deploy tool version bump (0.25.0; the repo keeps no changelog file).

## 8. Hardware (open in the PR if no drive is available)

- [x] 8.1 With a real CiA 402 drive: power on, home, absolute move, velocity, halt, fault reset from the demo program on the Pi.
  Skipped (Toni, 2026-10-06): no CiA 402 drive is available. Covered only by the simulated drive (6.2, 6.4).
- [x] 8.2 In OpenPLC Editor 4.3.2: a project from the example config with `drive_demo.st` as `main` passes Build only for OpenPLC Runtime v4.
  Done 2026-10-06 with the 4.3.2 release's own `openplc-cli compile` (the code path behind the Build button, run headless): the project from `--new-project` and the same project with `drive_demo.st` as `main` both compile for OpenPLC Runtime v4. The only warnings: the library's axis state, error and mode types are not debuggable.
