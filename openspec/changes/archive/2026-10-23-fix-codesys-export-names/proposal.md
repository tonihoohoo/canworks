## Why

Building a config with more than one CANopen network into a CODESYS project fails on the second network. On a real CODESYS (V3.5 SP22) the virtual-plant example stopped with "name conflicts with existing object 'CANopen_Manager'": CODESYS needs every object name to be unique in the whole device tree, while the script only checks names among the new object's siblings. The stand-in CODESYS in CI has the same blind spot, so CI passed.

The same run showed nodes whose configured heartbeat equals their EDS default (`conveyor` 50 ms, `cell` 200 ms) with heartbeat producer 0 in CODESYS. Their DCF carries the value only as `DefaultValue` (nothing to write), and CODESYS takes the General tab's heartbeat producer from configured values only, so the manager neither sets nor watches that node's heartbeat.

## What Changes

- **Tree-unique names.** New CANbus, CANopen Manager and node objects get a name no other object of the same device uses (`CANopen_Manager`, `CANopen_Manager_2`, ...). A node that cannot get its config name keeps the free name and the report says so, as today.
- **Heartbeat producer always set.** For a node with `heartbeat_ms`, the plan sets the CODESYS heartbeat producer setting to that value (and turns it on), whether or not it equals the EDS default. A node with heartbeat off is left as the DCF makes it.
- The stand-in CODESYS refuses a name used anywhere in the tree, as the real one does; the virtual-plant test (three networks) covers it.
- PC tools patch version bump.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `codesys-export`: new requirement "Unique object names"; "Plan settings per node" adds the heartbeat producer.

## Impact

- `tools/deploy/canworks/codesys/script/import_canworks.py` (`_unique_name`), `codesys/plan.py` (node heartbeat parameter), `tests/fake_codesys.py`, `tests/test_codesys.py`.
- No config or plan format change; projects built before keep working (a re-run reuses their bus and manager).
