## 1. Script and plan

- [x] 1.1 Read `0x01017000` from the SP22 dump: a plain UINT "Heartbeat-Producer Time" in ms, no elements
- [x] 1.2 `import_canworks.py`: `_unique_name` checks names across the whole project tree
- [x] 1.3 `plan.py`: heartbeat producer device setting for every node with `heartbeat_ms` > 0

## 2. Stand-in and tests

- [x] 2.1 `tests/fake_codesys.py`: `add` refuses a name used anywhere in the project with CODESYS's message
- [x] 2.2 Tests: virtual-plant three networks build with managers `CANopen_Manager`, `CANopen_Manager_2`, `CANopen_Manager_3`; a node name used in two networks becomes `rtd_2`; node whose heartbeat equals the EDS default gets the heartbeat setting in the plan and in the stand-in project

## 3. Release

- [x] 3.1 PC tools patch version bump and release notes
- [ ] 3.2 Windows CODESYS check (Toni's typed go): virtual-plant into a new project builds all three networks; `conveyor` shows heartbeat producer 50 ms
