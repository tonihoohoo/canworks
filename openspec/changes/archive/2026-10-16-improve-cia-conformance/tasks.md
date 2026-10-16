## 1. CiA 306 checker

- [x] 1.1 `tools/deploy/canworks/cia306.py`: rules for required `[FileInfo]`/`[DeviceInfo]` keys, printable ASCII, line length 255, ProductName 243, NodeName 246, `[MandatoryObjects]` = 0x1000/0x1001/0x1018, object lists sorted and matching sections and `SupportedObjects`, REALs in decimal, CiA 306 date/time forms, CiA 301 defaults of 0x1003 sub 0; each finding with file, section, key and the CiA reference
- [x] 1.2 Unit tests for each rule (one passing and one failing file per rule)

## 2. Slave EDS

- [x] 2.1 Confirm the slave device mode reads decimal REALs (Lely C parser or prepared copy); route the slave EDS through the prepared copy if not (it already runs the prepared copy: `eds_lint.cpp` prepares the slave EDS too)
- [x] 2.2 `slaveeds.py`: 0x1003 sub 0 "Number of errors", default 0
- [x] 2.3 Decimal REAL defaults and limits (shortest text that reads back exactly)
- [x] 2.4 `date` and `order_code` in the description and schema; full `[FileInfo]`; `OrderCode`
- [x] 2.5 ASCII and length checks naming the field; run `cia306` before writing
- [x] 2.6 Configurator slave builder: fill `date` on first generate (server side, kept from the saved description), show the new errors as the build's error message
- [x] 2.7 Regenerate fixture and example slave EDS files; update tests (REAL slave start reads 21.5, reproducible file, non-ASCII name)

## 3. DCF export

- [x] 3.1 `dcfexport.py`: write REAL values as decimal; keep validation on Lely's form
- [x] 3.2 `NodeName` ASCII/length check; run `cia306` on the added/changed keys of the written file
- [x] 3.3 Tests: REAL limit in decimal, non-ASCII node name, CODESYS export golden files updated

## 4. Plugin

- [x] 4.1 `config_stamp`: date 1-65535, time 1-86 399 999; unit test for the ranges
- [x] 4.2 PLC-cycle SYNC: no send and no skip count while the master is NMT STOPPED; counter back to 1 on master reset communication
- [x] 4.3 TIME producer: no send while STOPPED, send at once on leaving STOPPED
- [x] 4.4 Simulated-bus tests: SYNC and TIME silent while the master is STOPPED, SYNC counter after reset communication

## 5. CI

- [x] 5.1 Run `cia306` over all generated slave EDS files and the DCFs written by the export tests, inside the existing PC tools job, no new package
- [ ] 5.2 State CI wall time and summed job time against the `main` median in the PR

## 6. Docs and versions

- [x] 6.1 `docs/standards.md`: per standard what canworks does, Lely vs canworks, deliberate departures and why, gaps, how it is checked, CiA's test tool as the route to certification of the slave mode
- [x] 6.2 `docs/slave.md` (`date`, `order_code`, limits), `docs/config.md` (0x1020 values, SYNC/TIME in STOPPED), README link to the standards page
- [x] 6.3 PC tools minor version bump (0.80.0); the plugin's version comes from `git describe`

## 7. Hardware

- [ ] 7.1 Pi: node with `config_check` gets configured once after the upgrade, then reports unchanged on the next start; clean PLC start afterwards
