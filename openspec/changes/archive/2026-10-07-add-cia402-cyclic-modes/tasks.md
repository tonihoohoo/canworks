## 1. Library route (first, decides design decision 1)

- [x] 1.1 Build a test `openplc_canopen.stlib` with one ST block taking `AXIS_REF_SM3` (`library/build.sh` with `-L` to the bundled libraries) and install it in OpenPLC Editor 4.3.2 the way the deploy tool installs the SDO library; run `openplc-cli compile` (headless, the Build button's path) on a project that calls it. If the editor does not load a user library depending on `plcopen-softmotion`, switch to the fallback (blocks written into the project as POUs) and update design decision 1 before going on. Result: OpenPLC Editor 4.3.2 `openplc-cli compile` built a project calling an ST block of `openplc_canopen.stlib` that takes `AXIS_REF_SM3`; no fallback needed.
- [x] 1.2 Check that the SDO blocks still build and pass their tests with the library's new dependency (`library/build.sh --check`, SDO block tests). Result: `library/build.sh --check` passes; the SDO block tests pass.

## 2. Config contract

- [x] 2.1 `cyclic` and `interpolation_period_us` in the axis object of `schema/canopen.v1.schema.json` (v2 follows by `$ref`); `docs/config.md`.
- [x] 2.2 Deploy tool `axis.py`: the cyclic checks (PLC-cycle SYNC with `sync_cycles` 1, 0x6060 and a set-point mapped, synchronous RPDOs after EDS defaults, period representable) and warnings (TPDO feedback not synchronous, no 0x60C2, no 0x6065, mode not in 0x6502); unit tests including a two-network config.
- [x] 2.3 Plugin config parser: read the fields, refuse a cyclic axis without PLC-cycle SYNC or with `sync_cycles` above 1 and an unrepresentable period; config tests.

## 3. Plugin

- [x] 3.1 Write 0x60C2 sub 1/sub 2 during node configuration for a cyclic axis (from `interpolation_period_us` or base tick times `sync_cycles`), skipped when a startup SDO writes 0x60C2 or the EDS has none; log once; unit test of the value/exponent choice (10 ms, 2.5 ms, 1 ms, 125 us, 333 us refused).
- [x] 3.2 Compare the measured mean SYNC interval after 100 SYNCs with each cyclic axis's period, warn once at more than 10 % difference; test with the virtual bus. Test: `sim_tests --exact sim_cia402_cyclic_period_warning`.
- [x] 3.3 Show the interpolation period per cyclic axis in the diagnostics status and `openplc-canopen-diag status`.

## 4. Program blocks

- [x] 4.1 `CO402_CyclicPosition`, `CO402_CyclicVelocity`, `CO402_CyclicTorque`: bumpless start, mode change with bit 3 kept, `ModeTimeout`, step limits on `Axis.fCycleTime`, hand-over on `Enable` FALSE, error IDs; in `library/` next to the SDO blocks, rebuilt `openplc_canopen.stlib`.
- [x] 4.2 `CO402_CyclicMoveAbsolute` over the editor library's S7RTT planner (`FB_S7RTT_Plan`, segments evaluated each scan), starting from the actual position, `Done` on reaching the target.
- [x] 4.3 `test/cia402/drive_model.st`: modes 8, 9, 10 following their targets per call, 0x6502 mask, refusing a mode the mask does not list.
- [x] 4.4 ST tests (STruC++ 0.7.0): bumpless start from a non-zero position, mode refused, step limit, hand-over between the cyclic blocks (the cyclic demo: CSP move, CSV, CST, standstill), CSP move limits, error stop on fault and on lost drive; in CI with the existing CiA 402 tests. (`MC_Halt` does not apply in the cyclic modes: it sets the halt bit, which a drive ignores or handles its own way in modes 8-10; the demo stops in CSV instead, docs/cia402.md.)

## 5. Project generator and configurator

- [x] 5.1 Generated axis lines: `fCycleTime` for a cyclic axis from `--task-interval` / the project's task interval; tests (cyclic, non-cyclic unchanged).
- [x] 5.2 Configurator: "Cyclic synchronous" switch and interpolation period on the axis settings, the checks shown on the node, the "use SYNC from the PLC cycle" fix button; page tests.
- [x] 5.3 "Map CiA 402 objects" cyclic layout with transmission type 1 on the PDOs it fills and the changes listed; declarations panel cycle time line with a task interval field; page tests.

## 6. Simulator

- [x] 6.1 `plugin/sim/sim_drive.cpp`: mode 10 with `drive.torque_accel`, 0x60C2 read, SYNC watchdog (EMCY 0x8700, `sync_watchdog: false`), set-point step counter in `sim_status`; `schema/canopen-sim.v1.schema.json`; simulator unit tests.
- [x] 6.2 `docs/simulator.md`: CST, the watchdog, the step counter.

## 7. Example and end-to-end test

- [x] 7.1 `config/cia402-drive/make_eds.py`: 0x6502 lists 1, 3, 6, 8, 9, 10; add 0x60C2 and 0x6065/0x6066; regenerate `servo402.eds`; EDS lint and banned-word guard pass; existing profile-mode tests unchanged.
- [x] 7.2 `config/cia402-drive/canopen_config_cyclic.json` (cyclic axis, `"sync_source": "plc_cycle"`, synchronous PDOs, following error window by startup SDO) and `drive_cyclic_demo.st` (power, home, CSP move, CSV run, CST step, halt, reset); README of the example.
- [x] 7.3 `sim_tests --exact sim_cia402_cyclic`: the cyclic demo compiled by STruC++ as the PLC program through the real master against the in-plugin simulated drive with SYNC from the PLC cycle: 0x60C2 written, each step ends without a fault, zero oversized set-point steps, PLC stop faults the drive by its watchdog, `MC_Reset` and restart recover. In CI with `CANOPEN_REQUIRE_STRUCPP=1`.

## 8. Docs and release

- [x] 8.1 `docs/cia402.md`: cyclic synchronous section (config, blocks and their names in other motion libraries, start sequence, fixed three-cycle loop and the following error window formula, `fCycleTime`, PLC stop faults the drive, `MC_ReadStatus` shows discrete motion, `InSync`), update "What works" and "Related work".
- [x] 8.2 README: the CiA 402 line names CSP, CSV and CST.
- [x] 8.3 Deploy tool version bump. 0.36.0 (chain step 5).

## 9. Hardware and editor (open in the PR when not available)

- [x] 9.1 In OpenPLC Editor 4.3.2: the cyclic example's project with `drive_cyclic_demo.st` as `main` passes Build only for OpenPLC Runtime v4 (headless `openplc-cli compile` is enough). Result: the project from `--new-project --task-interval T#10ms` with `drive_cyclic_demo.st` as `main` built for OpenPLC Runtime v4 with headless `openplc-cli compile` (Editor 4.3.2).
- [x] 9.2 On the Pi (when reachable through Toni's Mac), the cyclic example against the simulated drive with the real runtime: 10 minutes of CSP motion at a 10 ms and a 2 ms task, SYNC interval min/max and late PDOs from the diagnostics status, no drive fault; Toni's template project back on afterwards. Passed 2026-10-07 on the Pi (real runtime, simulated network, demo looped): 10 ms task 10 min, SYNC 9874-10089 us, 0 skipped, 0 late PDOs, 0x60C2 10000 us, 0 oversized steps, no fault or EMCY, 25 moves; 2 ms task 10 min, SYNC 1934-2082 us, 0 skipped, 0 late, 0x60C2 2000 us, no fault, 18 moves. Found and fixed two bugs: the frame-inject channel on a simulated bus was never read (bus blocked after 1024 frames; cfd0d70) and the first start after an upload used the runtime's default base tick (eec214a); both rechecked on the Pi.
- [ ] 9.3 With a real CiA 402 drive: CSP move, CSV run, CST step, PLC stop and recovery. Left open until a drive is available.
