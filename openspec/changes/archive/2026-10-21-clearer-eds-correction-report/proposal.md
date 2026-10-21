# Proposal

## Why

After adding a node from an EDS in a standalone CODESYS project, the configurator showed this info bar:

> The PLC reads it through a corrected copy: "<number>+$NODEID" rewritten as "$NODEID+<number>" (8).

Toni asked whether text was missing. It was:

- **No subject.** "It" is the EDS file just imported. When a node is added from an EDS, this line is the only one in the banner, so the file name never appears. It shows up only when a UTF-8 conversion line comes first.
- **"(8)" is unexplained.** It is the number of entries rewritten (DefaultValue, ParameterValue, LowLimit or HighLimit lines).
- **No reason, and no word that the file is kept.** The user cannot tell why the rewrite happens, or whether their EDS was changed. The stored file stays exactly as imported.
- **Wrong reader for CODESYS and the bridge.** "The PLC" means the OpenPLC plugin. With CODESYS as the target, CODESYS never reads the EDS. It installs the DCFs canworks exports, and those are built from the corrected copy. With the Modbus bridge as the target, the bridge reads the copy. In the DCFs, REAL values are written as decimals again (`canopen-dcf-export`), so for CODESYS the REAL correction leaves no trace and naming it only adds noise.

## What Changes

- **The correction report names the file, says the file is kept, and names who reads the copy for the project's target:**
  - OpenPLC: "`valve.eds` is kept as imported. The OpenPLC plugin reads a corrected copy, because its CANopen stack cannot read these values:"
  - Modbus bridge: the same, with "The Modbus bridge reads a corrected copy".
  - CODESYS (master network): "`valve.eds` is kept as imported. The DCFs exported to CODESYS are built from a corrected copy:"
- **Each correction is one line, with its count in words, singular or plural:**
  - `8 values written "<number>+$NODEID" are read as "$NODEID+<number>"`
  - `1 bare "$NODEID" value is read as "$NODEID+0"`
  - `3 decimal REAL values are read as their hexadecimal bit pattern` (not listed for CODESYS, whose DCFs carry decimals)
  - `1 OCTET_STRING/DOMAIN value is cleared: [2051] DefaultValue was "----"`
- The UTF-8 conversion line stays as it is, since that one does change the stored file.
- Applies everywhere the import report is shown: Add node from EDS…, adding a node in Commission, and the slave EDS import. A slave network is never handed to CODESYS, so the slave EDS import uses the OpenPLC or bridge wording, with "canworks" as the reader under a CODESYS target.
- docs/configurator.md says what the banner shows. PC tools patch version bump.

## Non-goals

- The plugin's log line (`edslint.prepared_note`) and the deploy tool's output keep their wording.
- No change to which corrections are made.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-configurator`: Import an EDS (what the correction report says, per target; the `$NODEID` rewrites are listed among the corrections).

## Impact

- `tools/deploy/canworks/configurator/static/app.js`: `importReport()` takes the reader from the project target (`projectTarget()` in target.js) and whether the import is for a slave EDS.
- `tools/deploy/canworks/edslint.py` unchanged: the page builds its own words from each correction's `kind` and `count`, so the plugin's log text stays as it is.
- Tests: `tests/test_configurator_page.py` (report text for OpenPLC and CODESYS, singular and plural); a new lint fixture `test/fixtures/eds/lint/nodeid-suffix.eds` with `<number>+$NODEID` values (made by `make_fixtures.py`).
- No README change: the README does not describe the import banner.
