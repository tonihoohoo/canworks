# canopen-slave-eds Specification

## Purpose
Gives users an EDS for their OpenPLC slave without writing one by hand: generated on the PC from a list of objects, run by the plugin, and imported unchanged into the other master's configuration tool.

## Requirements

### Requirement: Generate an EDS from an object list
`openplc-canopen-deploy slave-eds` SHALL write a CiA 306 EDS from a JSON description with identity (device name, vendor ID, product code, revision), heartbeat default and a list of objects, each with a name, data type, direction (`from_master` or `to_master`) and optional default, low and high limits. The file SHALL pass the plugin's EDS lint with `eds_lint: "all"`.

#### Scenario: Generate and lint
- **WHEN** the user runs `openplc-canopen-deploy slave-eds slave.json -o canopen/slave.eds` with two inputs and two outputs
- **THEN** `canopen/slave.eds` is written and the plugin's lint finds nothing in it

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
The generator SHALL write the EDS into the project's `canopen/` folder as a normal file that the config names in `slave.eds`; the plugin SHALL run that file unchanged and the export SHALL be byte-identical to it.

#### Scenario: Export for the other master
- **WHEN** the user exports the slave EDS from the configurator
- **THEN** the exported file has the same SHA-256 as the file in `canopen/` that the plugin runs
