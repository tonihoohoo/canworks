## MODIFIED Requirements

### Requirement: Notes skeleton command
The deploy tool SHALL provide `canworks-deploy notes skeleton <eds>` (canopen-device-notes), printing a `canworks-notes.v1` document with the EDS identity and an entry per manufacturer object and sub-object (0x2000-0x5FFF), each with its EDS name, data type (`x-type`) and access (`x-access`). With `--all` it SHALL have an entry for every object and sub-object of the EDS, each also with the EDS default (`x-default`), limits (`x-low`, `x-high`) and PDO mapping (`x-pdo`, true or false), each value as the EDS writes it and left out when the EDS has none. `--output FILE` SHALL write it to a file instead. An EDS that cannot be read SHALL exit non-zero with the reason.

#### Scenario: Skeleton of a device
- **WHEN** the user runs `canworks-deploy notes skeleton valve.eds` for an EDS with VAR 0x2010 (UNSIGNED8, rw) and RECORD 0x2011 with subs 0-2
- **THEN** the output has `"format": "canworks-notes.v1"`, the EDS identity, `0x2010` with its name, `x-type` UNSIGNED8 and `x-access` rw, and `0x2011:0`, `0x2011:1` and `0x2011:2`

#### Scenario: Every object with its EDS values
- **WHEN** the user runs `canworks-deploy notes skeleton --all valve.eds` and the EDS gives 0x2010 the default 100 and no limits
- **THEN** the output also has `0x1000` and `0x1018:1`, and `0x2010` has `x-default` "100", `x-pdo` false and no `x-low` or `x-high`
