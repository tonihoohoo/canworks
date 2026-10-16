## Why

An exploration of how well canworks' output follows the CANopen standards (CiA 301, 302, 305, 306, 309-3) found that most of it conforms, because the Lely stack does the standard parts, but also found a few small real faults and that nothing checks conformance independently: every test compares Lely against Lely.

- The generated slave EDS gives object 0x1003 sub-index 0 the default 8. CiA 301 defines it as the number of stored errors, which starts at 0.
- REAL32/REAL64 values in the generated slave EDS and in exported DCFs are written as Lely's hexadecimal bit pattern (21.5 becomes `0x41AC0000`). CiA 306 has no such form, so another master's tool, CODESYS included, reads a huge integer.
- The generated EDS has no creation or modification date/time in `[FileInfo]` and no `OrderCode` in `[DeviceInfo]`, which CiA 306 lists and EDS checkers flag. Names may contain any Unicode and have no length limit, while CiA 306 expects ASCII and lines of at most 255 characters.
- With `config_check`, the value written to 0x1020 is a hash split in two. Sub 2 is the configuration time in milliseconds after midnight; a hash value of 86 400 000 or more is not a valid time, and a device that range-checks it can refuse the write.
- With `"sync_source": "plc_cycle"` and with `time_period_ms`, the plugin sends SYNC and TIME itself and keeps doing so while the master is in NMT STOPPED, where CiA 301 allows only NMT and error control. The PLC-cycle SYNC counter is never set back to 1 when the master resets communication.
- The master deliberately departs from CiA 302-2 in a few places (held nodes, retrying a missing mandatory node, its own configuration download instead of 0x1F22). These are design choices but are written down nowhere.

## What Changes

- **Slave EDS fixes:** 0x1003 sub 0 is named "Number of errors" with default 0. REAL defaults and limits are written as decimal numbers; the plugin already reads decimal REALs through its prepared EDS copy. `[FileInfo]` gets `CreationDate`, `CreationTime`, `ModificationDate`, `ModificationTime` and `ModifiedBy`, from a new optional `date` in the description so the output stays reproducible. `[DeviceInfo]` gets `OrderCode` from a new optional `order_code`, defaulting to the device name. Text fields must be printable ASCII and within CiA 306's lengths; otherwise generation stops naming the field.
- **DCF export:** REAL values (DefaultValue, ParameterValue, LowLimit, HighLimit) are written as decimal numbers in the exported file, while the checks still run on Lely's form. `NodeName` must be printable ASCII and at most 246 characters.
- **A strict CiA 306 check:** a new checker in the PC tools checks the files canworks writes for what Lely's lint does not require: the `[FileInfo]` and `[DeviceInfo]` keys CiA 306 lists, ASCII text, line length, `[MandatoryObjects]` holding 0x1000, 0x1001 and 0x1018, object lists sorted and matching the object sections, REAL values in decimal, the CiA 306 date and time forms, and CiA 301 default values of the standard objects canworks writes itself (such as 0x1003 sub 0). The slave EDS generator and the DCF export refuse output that fails it, and a CI test runs it on every generated slave EDS and exported DCF of the fixtures and examples.
- **0x1020 values in range:** the configuration date is kept to 1-65535 days and the configuration time to 1-86 399 999 ms. Every node with `config_check` gets its configuration downloaded once more after the upgrade, because the values change.
- **SYNC and TIME follow the master's NMT state:** PLC-cycle SYNC and the TIME producer send nothing while the master is NMT STOPPED and resume when it leaves STOPPED. The PLC-cycle SYNC counter starts again at 1 when the master resets communication, as Lely's timer SYNC does.
- **Standards page:** a new `docs/standards.md` lists which CiA standards canworks follows, which parts the Lely stack does, the deliberate departures (CiA 302-2 boot-up, configuration manager, 0x1020 contents, proprietary gateway objects, 309-3 services not served), the known gaps (SDO block transfer in the client, RTR PDOs, 29-bit PDO COB-IDs, CiA 302-4/-6/-7), and how conformance is checked. README links it.

Non-goals: CiA's Conformance Test Tool run or certification; an interoperability test against a second CANopen stack; changing the CiA 302-2 departures themselves; checking vendor EDS files more strictly (the strict check runs only on files canworks writes); master EMCY on RPDO timeout; 309-3 command additions.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-slave-eds`: CiA 301 defaults for 0x1003, decimal REALs, full `[FileInfo]` and `OrderCode`, ASCII and length limits, the strict CiA 306 check.
- `canopen-dcf-export`: decimal REALs in the written file, the strict CiA 306 check, ASCII `NodeName`.
- `canopen-master-bringup`: 0x1020 values in valid ranges; PLC-cycle SYNC and TIME stopped while the master is NMT STOPPED; SYNC counter reset.
- `canopen-ci`: produced EDS and DCF files checked against CiA 306 in CI.

## Impact

- `tools/deploy/canworks/slaveeds.py`, `tools/deploy/canworks/dcfexport.py`, a new `tools/deploy/canworks/cia306.py`; the configurator's slave EDS form gets the `date` and `order_code` fields and shows the new errors.
- `plugin/src/canopen/dcf_gen.cpp` (`config_stamp`), `plugin/src/canopen/network.cpp`/`network.h` (SYNC and TIME gating, counter reset).
- Regenerated fixture and example slave EDS files (their revision numbers stay: they hash the objects, which do not change).
- Tests: slave EDS and DCF export tests, the new CI conformance test (Python only, under the existing PC tools path filter, no new job), unit and simulated-bus tests for 0x1020, SYNC and TIME.
- `docs/standards.md` (new), `docs/slave.md`, `docs/config.md`, README.md. PC tools and plugin minor version bumps.
- Hardware: a short bench check that node 23 still boots with `config_check` after the 0x1020 change.
