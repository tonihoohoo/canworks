## ADDED Requirements

### Requirement: Notes skeleton command
The deploy tool SHALL provide `canworks-deploy notes skeleton <eds>` (canopen-device-notes), printing a `canworks-notes.v1` document with the EDS identity and an entry per manufacturer object and sub-object (0x2000-0x5FFF), each with its EDS name, data type (`x-type`) and access (`x-access`). `--output FILE` SHALL write it to a file instead. An EDS that cannot be read SHALL exit non-zero with the reason.

#### Scenario: Skeleton of a device
- **WHEN** the user runs `canworks-deploy notes skeleton valve.eds` for an EDS with VAR 0x2010 (UNSIGNED8, rw) and RECORD 0x2011 with subs 0-2
- **THEN** the output has `"format": "canworks-notes.v1"`, the EDS identity, `0x2010` with its name, `x-type` UNSIGNED8 and `x-access` rw, and `0x2011:0`, `0x2011:1` and `0x2011:2`

### Requirement: Built-in notes command
The deploy tool SHALL provide `canworks-deploy notes builtin <eds>`, printing the built-in notes that apply to the EDS as a `canworks-notes.v1` document, with `--output FILE` as for `skeleton`.

#### Scenario: Built-in notes of a drive
- **WHEN** the EDS's 0x1000 default has device profile 402
- **THEN** `canworks-deploy notes builtin` prints the CiA 301 and CiA 402 notes for the objects that EDS has, including the controlword bit names

### Requirement: Notes check command
The deploy tool SHALL provide `canworks-deploy notes check <eds> <notes file>`, printing the findings the configurator shows for that notes file, one per line, and exiting with status 1 when there is any finding and 0 when there is none. An EDS or notes file that cannot be read SHALL exit non-zero with the reason.

#### Scenario: Check a notes file
- **WHEN** a notes file has a note for 0x2012, which the EDS does not have
- **THEN** `canworks-deploy notes check` prints that the notes file has a note for 0x2012, which the EDS does not have, and exits with status 1
