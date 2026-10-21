## MODIFIED Requirements

### Requirement: Import an EDS
Adding a node SHALL start from an EDS file the user picks. The configurator SHALL check that it is a CiA 306 EDS the deploy tool accepts, store it under `canworks/` as UTF-8 (converting from Latin-1/CP1252 when it is not valid UTF-8) and refer to it by a path relative to `canworks/`. A different file with the same name SHALL NOT be overwritten silently. When "keep both" gives the new EDS another name, it SHALL get its own notes file (see `canopen-device-notes`), and replacing an EDS SHALL keep its notes file.

At import, the configurator SHALL also run the checks the PLC runs before dcfgen, on the same prepared copy (see `canopen-master-bringup`, "Prepared EDS copy"): dcfgen's EDS read and lint, and Lely's EDS parse rules, sorting the lint findings as the plugin does (see `canopen-master-bringup`, "EDS lint scope") under the config's `eds_lint` setting. The import SHALL show:
- that the file is readable, when nothing below applies;
- the corrections made in the prepared copy (UTF-8 conversion, `$NODEID` rewrites, REAL rewrite, cleared OCTET_STRING values), as described below;
- findings that do not stop the PLC, as a collapsed list with each finding's object, saying they are accepted.

The correction report SHALL name the imported file, SHALL say that the file is kept as imported, and SHALL name who reads the corrected copy for the project's target: the OpenPLC plugin, the Modbus bridge, or, for a node under a CODESYS target, the DCFs exported to CODESYS, which are built from it. A slave EDS import under a CODESYS target SHALL name canworks as the reader. Each kind of correction SHALL be listed on its own line with how many values it changed, in words that read correctly for one value and for several. Under a CODESYS target, a node import SHALL NOT list the REAL rewrite, since the exported DCFs write REAL values as decimals. The UTF-8 conversion, which changes the stored file, SHALL be reported on its own line as before.

The import SHALL be refused, showing the reason, and no node SHALL be added, when dcfgen or Lely cannot read the file even after the corrections, or when the lint has findings that would stop the PLC.

#### Scenario: Latin-1 vendor EDS
- **WHEN** the user imports `vendor.eds`, encoded in Latin-1 with `°C` in a ParameterName
- **THEN** on save `canworks/vendor.eds` is valid UTF-8 with the same text and the node's `eds` is `vendor.eds`

#### Scenario: Not an EDS
- **WHEN** the user picks a file without objects 0x1000 and 0x1018
- **THEN** the import is refused with the reason and no node is added

#### Scenario: Same name, different content
- **WHEN** an imported EDS has the same name as a different EDS already in `canworks/`
- **THEN** the user is asked to replace it or keep both under a new name, and nothing is overwritten without that choice

#### Scenario: Vendor EDS with findings in profile objects
- **WHEN** the user imports a drive EDS with signed limits written as unsigned hex in its profile objects
- **THEN** the node is added and the import shows its findings as accepted, listed collapsed with their objects

#### Scenario: Finding in a communication object
- **WHEN** the user imports an EDS whose 0x1A00 sub 0 has the data type UNSIGNED16, and `eds_lint` is unset
- **THEN** the import is refused, the finding in 0x1A00 sub 0 is shown, and no node is added

#### Scenario: Notes file for a new EDS
- **WHEN** the user imports `valve.eds`, which has no notes file, adds the node and saves
- **THEN** `canworks/valve.eds.notes.json` is written with the valve's identity and an entry for each manufacturer object

#### Scenario: $NODEID rewrite reported for OpenPLC
- **WHEN** the project target is OpenPLC and the user adds a node from `valve.eds`, which has 8 values written `<number>+$NODEID`
- **THEN** the banner names `valve.eds`, says it is kept as imported and that the OpenPLC plugin reads a corrected copy, and lists that 8 values written `<number>+$NODEID` are read as `$NODEID+<number>`

#### Scenario: One rewritten value
- **WHEN** the imported EDS has exactly one value written `<number>+$NODEID`
- **THEN** the line reads as one value ("1 value ... is read as"), not "1 values"

#### Scenario: $NODEID rewrite reported for CODESYS
- **WHEN** the project target is CODESYS and the user adds a node from the same `valve.eds`
- **THEN** the banner names `valve.eds`, says it is kept as imported and that the DCFs exported to CODESYS are built from a corrected copy, and lists the 8 rewritten values

#### Scenario: REAL rewrite only, CODESYS
- **WHEN** the project target is CODESYS and the only correction an imported EDS needs is decimal REAL values
- **THEN** no correction is listed, and the banner says the file is readable when nothing else applies
