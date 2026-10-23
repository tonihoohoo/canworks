## Why

The bench run of the truST export (add-plcopen-export task 7.3) worked, but showed one problem. truST against the bridge on the Linux device with node 23 gave these results:

- the import was full and the build had no errors;
- `canworks.ok` was TRUE;
- `CO_SDO_READ` of 0x1018:1 and `CO_SDO_READ_STRING` of 0x1008 each ran about 170 times with no faults;
- the outputs went off by the watchdog when truST stopped.

The problem is the scan time. A truST scan with the copy programs and the library takes about 125 ms on a Pi 5, much longer than the 10 ms task (truST logs overruns). The config used OpenPLC's default watchdog (`watchdog_ms` 50, five polls of 10 ms). The bridge therefore switched the outputs off and on again on every scan, 472 times in 60 s, and node 23's RPDOs stopped and restarted each time. Nothing in the export says this will happen.

## What Changes

- `--for trust` refuses a config whose bridge watchdog is shorter than 500 ms, unless the watchdog is 0 (off). This covers the OpenPLC default of 50 ms.
  - The refusal names the fix: `"watchdog_ms": 500` or more in `bridge`.
  - The same refusal shows in the configurator's PLCopen dialog and in Problems on export.
- docs/plcopen.md states truST's scan time with the library (about 100–125 ms) and the watchdog floor, next to the existing one-request limit.
- Unchanged: the plain PLC link's default watchdog of 1000 ms passes, and CODESYS and generic exports have no floor.

## Capabilities

### Modified Capabilities
- `plcopen-export`: truST transport refuses a bridge watchdog under 500 ms.

## Impact

- `tools/deploy/canworks/plcopen_targets.py` (check), tests in `tests/test_plcopen.py` and `tests/test_configurator_bridge.py`, docs/plcopen.md.
- Tools patch version bump; no new CI job, and the tests run in the existing tools shard.
