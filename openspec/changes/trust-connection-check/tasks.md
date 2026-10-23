## 1. Checks

- [ ] 1.1 `connections.problems`: for each truST connection the `plcopen_targets.check(cfg, "trust")` texts, for each Other PLC connection `check(cfg, "generic")`, as warnings with paths (connection row for the PLC link, `bridge.mailboxes` for the map size, `bridge.watchdog_ms` for the watchdog); one warning per text even with several connections of a kind
- [ ] 1.2 `canworks-deploy --check` prints the warnings

## 2. Configurator

- [ ] 2.1 Problems fixes **Set the watchdog to 500 ms** and **Trim the mailboxes for truST** (one undo step, repack), the trim button's title naming what OpenPLC loses when the config has an OpenPLC connection
- [ ] 2.2 Connection row state "Cannot download" with the first reason

## 3. Tests and docs

- [ ] 3.1 Server tests (OpenPLC + truST config warns; truST-only config with trimmed mailboxes and 500 ms does not), page test (fix buttons, row state), CLI check test
- [ ] 3.2 docs/modbus-bridge.md and docs/plcopen.md; README if a label it names changes
- [ ] 3.3 Version bump; CI time against the baseline in the PR

## 4. Hardware

- [ ] 4.1 Mac: the OpenPLC + truST config from the 8.2 run shows the warnings, the two fixes make the truST Download work
