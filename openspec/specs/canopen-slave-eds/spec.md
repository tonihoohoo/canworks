# canopen-slave-eds Specification

## Purpose
Gives users an EDS for their OpenPLC slave without writing one by hand: generated on the PC from a list of objects, run by the plugin, and imported unchanged into the other master's configuration tool.

## Requirements

### Requirement: Generate an EDS from an object list
`canworks-deploy slave-eds` SHALL write a CiA 306 EDS from a JSON description with identity (device name, vendor ID, product code, revision), heartbeat default and a list of objects, each with a name, data type, direction (`from_master` or `to_master`) and optional default, low and high limits. The description MAY give `date` (`YYYY-MM-DD`, optionally followed by ` HH:MM`) and `order_code`. The file SHALL pass the plugin's EDS lint with `eds_lint: "all"` and the CiA 306 check of the PC tools; when either fails, the generator SHALL write nothing and report every finding.

#### Scenario: Generate and lint
- **WHEN** the user runs `canworks-deploy slave-eds slave.json -o canworks/slave.eds` with two inputs and two outputs
- **THEN** `canworks/slave.eds` is written, and neither the plugin's lint nor the CiA 306 check finds anything in it

#### Scenario: Unsupported type
- **WHEN** an object has data type `STRING`
- **THEN** generation stops with an error naming the object and the supported types

### Requirement: Object layouts
The generator SHALL support two layouts: `manufacturer` (default), with objects the master writes from 0x2000 and objects it reads from 0x2100, one record per data type; and `cia401`, with device type 401 and the CiA 401 objects for digital and analog inputs and outputs, accepting only the types CiA 401 defines.

#### Scenario: CiA 401 with a REAL
- **WHEN** layout `cia401` is chosen and an object has type `REAL`
- **THEN** generation stops with an error naming the object and the layout

#### Scenario: Access types
- **WHEN** an object has direction `from_master` in the manufacturer layout
- **THEN** its EDS entry has `AccessType=rww` and `PDOMapping=1`

### Requirement: Default PDOs in the generated EDS
The generated EDS SHALL have default RPDO and TPDO mappings that together carry every object, packed in object order into as few PDOs as fit 8 bytes each, using the CiA 301 default COB-IDs, transmission type 255 for TPDOs and RPDOs, and writable mapping objects so the master can remap.

#### Scenario: Ten bytes of outputs
- **WHEN** the objects the master reads are five UNSIGNED16 values
- **THEN** TPDO 1 maps the first four and TPDO 2 maps the fifth

### Requirement: Identity tracks the content
Unless the user sets the revision number, the generator SHALL derive 0x1018:3 from a hash of the object list and layout, so a master that checks identity notices an EDS that changed without being imported again. The vendor ID SHALL default to 0.

#### Scenario: Object added
- **WHEN** the user adds one object and generates again
- **THEN** the revision number in the new EDS differs from the old one

### Requirement: Generated EDS is the file that runs
The generator SHALL write the EDS into the project's `canworks/` folder as a normal file that the config names in `slave.eds`; the plugin SHALL run that file unchanged and the export SHALL be byte-identical to it.

#### Scenario: Export for the other master
- **WHEN** the user exports the slave EDS from the configurator
- **THEN** the exported file has the same SHA-256 as the file in `canworks/` that the plugin runs

### Requirement: Standard objects follow CiA 301
The standard objects the generator writes SHALL have the names and default values CiA 301 gives them. 0x1003 sub-index 0 SHALL be named "Number of errors" and SHALL have the default value 0.

#### Scenario: Error history starts empty
- **WHEN** the user generates a slave EDS
- **THEN** `[1003sub0]` has `ParameterName=Number of errors` and `DefaultValue=0`

### Requirement: REAL values in decimal
REAL32 and REAL64 DefaultValue, LowLimit and HighLimit SHALL be written as decimal numbers that read back to exactly the same value, not as a hexadecimal bit pattern. The plugin SHALL run the file unchanged, reading its REALs through the prepared EDS copy.

#### Scenario: REAL default
- **WHEN** an object of type REAL has default 21.5
- **THEN** its EDS entry has `DefaultValue=21.5`, and the plugin's slave reads 21.5 from the object at start

### Requirement: File and device information
`[FileInfo]` SHALL have `FileName`, `FileVersion`, `FileRevision`, `EDSVersion`, `Description`, `CreationTime`, `CreationDate`, `CreatedBy`, `ModificationTime`, `ModificationDate` and `ModifiedBy`, with dates as `mm-dd-yyyy` and times as `hh:mm` followed by `AM` or `PM`. The dates and times SHALL come from the description's `date`; without it, they SHALL be the current date at 12:00AM. Generating twice from the same description with a `date` SHALL give byte-identical files.

#### Scenario: Reproducible file
- **WHEN** a description with `"date": "2026-10-16 14:30"` is generated twice
- **THEN** both files are byte-identical and have `CreationDate=10-16-2026` and `CreationTime=02:30PM`

### Requirement: Order code
`[DeviceInfo]` SHALL have `OrderCode`, from the description's `order_code` or else the device name.

#### Scenario: No order code given
- **WHEN** the description names the device `pump-io` and gives no `order_code`
- **THEN** `[DeviceInfo]` has `OrderCode=pump-io`

### Requirement: Text within CiA 306 limits
The device name, vendor name, order code, object names and description text SHALL be printable ASCII. `ProductName` SHALL be at most 243 characters, and no line of the file SHALL be longer than 255 characters. A value outside these limits SHALL stop generation with an error naming the field and the limit.

#### Scenario: Non-ASCII device name
- **WHEN** the description's device name is `Pumppuasema ä`
- **THEN** generation stops with an error naming `device_name` and saying only printable ASCII is allowed
