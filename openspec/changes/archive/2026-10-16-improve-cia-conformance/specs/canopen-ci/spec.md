## ADDED Requirements

### Requirement: Written EDS and DCF files checked against CiA 306
CI SHALL run the PC tools' CiA 306 check on every slave EDS that canworks generates for the fixtures and examples, and on every DCF the DCF export tests write, and SHALL fail naming the file, section and key of each finding. The check SHALL run inside an existing PC tools test job, SHALL install no package, and SHALL NOT run on vendor EDS files that canworks only reads.

#### Scenario: Wrong default slips in
- **WHEN** a change makes the slave EDS generator write `DefaultValue=8` on 0x1003 sub 0
- **THEN** the CI run fails naming the generated file, `[1003sub0]` and `DefaultValue`

#### Scenario: Vendor EDS without OrderCode
- **WHEN** a fixture vendor EDS has no `OrderCode`
- **THEN** the CiA 306 check does not run on it and CI does not fail for it
