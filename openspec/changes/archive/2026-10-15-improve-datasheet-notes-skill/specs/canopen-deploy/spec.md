## MODIFIED Requirements

### Requirement: Notes skeleton command
The deploy tool SHALL provide `canworks-deploy notes skeleton <eds>` (canopen-device-notes), printing a `canworks-notes.v1` document with the EDS identity and an entry per manufacturer object and sub-object (0x2000-0x5FFF), each with its EDS name, data type (`x-type`) and access (`x-access`). With `--all` it SHALL have an entry for every object and sub-object of the EDS, each also with the EDS default (`x-default`), limits (`x-low`, `x-high`) and PDO mapping (`x-pdo`, true or false), each value as the EDS writes it and left out when the EDS has none, and an entry with only the name for each ARRAY and RECORD object itself. `--index LOW-HIGH` SHALL keep only the entries of objects in that index range. Data types SHALL be named, UNSIGNED24-56 and INTEGER24-56 included. When the EDS lacks the vendor ID, product code or revision, the identity SHALL leave it out and a line on stderr SHALL name it. `--output FILE` SHALL write the document to a file instead. An EDS that cannot be read SHALL exit non-zero with the reason, naming the line for a syntax error and the section for a missing or wrong entry.

#### Scenario: Skeleton of a device
- **WHEN** the user runs `canworks-deploy notes skeleton valve.eds` for an EDS with VAR 0x2010 (UNSIGNED8, rw) and RECORD 0x2011 with subs 0-2
- **THEN** the output has `"format": "canworks-notes.v1"`, the EDS identity, `0x2010` with its name, `x-type` UNSIGNED8 and `x-access` rw, and `0x2011:0`, `0x2011:1` and `0x2011:2`

#### Scenario: Every object with its EDS values
- **WHEN** the user runs `canworks-deploy notes skeleton --all valve.eds` and the EDS gives 0x2010 the default 100 and no limits
- **THEN** the output also has `0x1000`, `0x1018:1` and `0x2011` with the RECORD's name, and `0x2010` has `x-default` "100", `x-pdo` false and no `x-low` or `x-high`

#### Scenario: One range of a large EDS
- **WHEN** the user runs `canworks-deploy notes skeleton --all --index 0x3000-0x30FF drive.eds` for an EDS with 600 manufacturer objects
- **THEN** the output has only the entries of objects 0x3000 to 0x30FF

#### Scenario: EDS without a product code
- **WHEN** the EDS's `[DeviceInfo]` has no `ProductNumber`
- **THEN** the identity has no `product_code` and stderr says the EDS gives no product code

#### Scenario: Syntax error in the EDS
- **WHEN** line 1843 of the EDS reads `ObjectType0x7`
- **THEN** the command exits non-zero and the reason names line 1843 and its text

### Requirement: Built-in notes command
The deploy tool SHALL provide `canworks-deploy notes builtin <eds>`, printing the built-in notes that apply to the EDS as a `canworks-notes.v1` document, with `--output FILE` as for `skeleton`. A line on stderr SHALL name the built-in sets used and, when the EDS's 0x1000 default names a device profile without built-in notes or has no default, say so.

#### Scenario: Built-in notes of a drive
- **WHEN** the EDS's 0x1000 default has device profile 402
- **THEN** `canworks-deploy notes builtin` prints the CiA 301 and CiA 402 notes for the objects that EDS has, including the controlword bit names

#### Scenario: Encoder profile
- **WHEN** the EDS's 0x1000 default has device profile 406
- **THEN** the output has the CiA 301 notes only and stderr says that there are no built-in notes for profile 406

### Requirement: Notes check command
The deploy tool SHALL provide `canworks-deploy notes check <eds> <notes file>`, printing the findings the configurator shows for that notes file, one per line, and exiting with status 1 when there is any finding and 0 when there is none. An EDS or notes file that cannot be read SHALL exit non-zero with the reason, naming the line or section as for `skeleton`.

#### Scenario: Check a notes file
- **WHEN** a notes file has a note for 0x2012, which the EDS does not have
- **THEN** `canworks-deploy notes check` prints that the notes file has a note for 0x2012, which the EDS does not have, and exits with status 1

#### Scenario: Object count wrong in the EDS
- **WHEN** the EDS's `[ManufacturerObjects]` says `SupportedObjects=7` and lists six objects
- **THEN** the command exits non-zero and the reason names `[ManufacturerObjects]` and the missing entry 7
