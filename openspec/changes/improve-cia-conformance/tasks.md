## 1. CiA 306 checker

- [ ] 1.1 `tools/deploy/canworks/cia306.py`: rules for required `[FileInfo]`/`[DeviceInfo]` keys, printable ASCII, line length 255, ProductName 243, NodeName 246, `[MandatoryObjects]` = 0x1000/0x1001/0x1018, object lists sorted and matching sections and `SupportedObjects`, REALs in decimal, CiA 306 date/time forms, CiA 301 defaults of 0x1003 sub 0; each finding with file, section, key and the CiA reference
- [ ] 1.2 Unit tests for each rule (one passing and one failing file per rule)

## 2. Slave EDS

- [ ] 2.1 Confirm the slave device mode reads decimal REALs (Lely C parser or prepared copy); route the slave EDS through the prepared copy if not
- [ ] 2.2 `slaveeds.py`: 0x1003 sub 0 "Number of errors", default 0
- [ ] 2.3 Decimal REAL defaults and limits (shortest text that reads back exactly)
- [ ] 2.4 `date` and `order_code` in the description and schema; full `[FileInfo]`; `OrderCode`
- [ ] 2.5 ASCII and length checks naming the field; run `cia306` before writing
- [ ] 2.6 Configurator slave builder: fill `date` on first generate, show the new errors on the field
- [ ] 2.7 Regenerate fixture and example slave EDS files; update tests (REAL slave start reads 21.5, reproducible file, non-ASCII name)

## 3. DCF export

- [ ] 3.1 `dcfexport.py`: write REAL values as decimal; keep validation on Lely's form
- [ ] 3.2 `NodeName` ASCII/length check; run `cia306` on the added/changed keys of the written file
- [ ] 3.3 Tests: REAL limit in decimal, non-ASCII node name, CODESYS export golden files updated

## 4. Plugin

- [ ] 4.1 `config_stamp`: date 1-65535, time 1-86 399 999; unit test for the ranges
- [ ] 4.2 PLC-cycle SYNC: no send and no skip count while the master is NMT STOPPED; counter back to 1 on master reset communication
- [ ] 4.3 TIME producer: no send while STOPPED, send at once on leaving STOPPED
- [ ] 4.4 Simulated-bus tests: SYNC and TIME silent while the master is STOPPED, SYNC counter after reset communication

## 5. CI

- [ ] 5.1 Run `cia306` over all generated slave EDS files and the DCFs written by the export tests, inside the existing PC tools job, no new package
- [ ] 5.2 State CI wall time and summed job time against the `main` median in the PR

## 6. Docs and versions

- [ ] 6.1 `docs/standards.md`: per standard what canworks does, Lely vs canworks, deliberate departures and why, gaps, how it is checked, CiA's test tool as the route to certification of the slave mode
- [ ] 6.2 `docs/slave.md` (`date`, `order_code`, limits), `docs/config.md` (0x1020 values, SYNC/TIME in STOPPED), README link to the standards page
- [ ] 6.3 PC tools and plugin minor version bumps

## 7. Hardware

- [ ] 7.1 Pi: node with `config_check` gets configured once after the upgrade, then reports unchanged on the next start; clean PLC start afterwards
