## MODIFIED Requirements

### Requirement: Generate an EDS from an object list
`canworks-deploy slave-eds` SHALL write a CiA 306 EDS from a JSON description with identity (device name, vendor ID, product code, revision), heartbeat default and a list of objects, each with a name, data type, direction (`from_master` or `to_master`) and optional default, low and high limits. The description MAY give `date` (`YYYY-MM-DD`, optionally followed by ` HH:MM`) and `order_code`. The file SHALL pass the bridge's EDS lint with `eds_lint: "all"` and the CiA 306 check of the PC tools; when either fails, the generator SHALL write nothing and report every finding.

#### Scenario: Generate and lint
- **WHEN** the user runs `canworks-deploy slave-eds slave.json -o canworks/slave.eds` with two inputs and two outputs
- **THEN** `canworks/slave.eds` is written, and neither the bridge's lint nor the CiA 306 check finds anything in it

#### Scenario: Unsupported type
- **WHEN** an object has data type `STRING`
- **THEN** generation stops with an error naming the object and the supported types

### Requirement: Generated EDS is the file that runs
The generator SHALL write the EDS into the project's `canworks/` folder as a normal file that the config names in `slave.eds`; the bridge SHALL run that file unchanged and the export SHALL be byte-identical to it.

#### Scenario: Export for the other master
- **WHEN** the user exports the slave EDS from the configurator
- **THEN** the exported file has the same SHA-256 as the file in `canworks/` that the bridge runs

### Requirement: REAL values in decimal
REAL32 and REAL64 DefaultValue, LowLimit and HighLimit SHALL be written as decimal numbers that read back to exactly the same value, not as a hexadecimal bit pattern. The bridge SHALL run the file unchanged, reading its REALs through the prepared EDS copy.

#### Scenario: REAL default
- **WHEN** an object of type REAL has default 21.5
- **THEN** its EDS entry has `DefaultValue=21.5`, and the bridge's slave reads 21.5 from the object at start
