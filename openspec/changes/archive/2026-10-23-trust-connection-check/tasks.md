## 1. Checks

- [x] 1.1 `connections.problems`: for each truST connection the `plcopen_targets.check(cfg, "trust")` texts, for each Other PLC connection `check(cfg, "generic")`, as warnings with paths (connection row for the PLC link, `bridge.mailboxes` for the map size, `bridge.watchdog_ms` for the watchdog); one warning per text even with several connections of a kind
- [x] 1.2 `canworks-deploy --check` prints the warnings

## 2. Configurator

- [x] 2.1 Problems fixes **Set the watchdog to 500 ms** and **Trim the mailboxes for truST** (one undo step, repack), the trim button's title naming what OpenPLC loses when the config has an OpenPLC connection
- [x] 2.2 Connection row state "Cannot download" with the first reason

## 3. Tests and docs

- [x] 3.1 Server tests (OpenPLC + truST config warns; truST-only config with trimmed mailboxes and 500 ms does not), page test (fix buttons, row state), CLI check test
- [x] 3.2 docs/modbus-bridge.md and docs/plcopen.md; README if a label it names changes
- [x] 3.3 Version bump; CI time against the baseline in the PR

## 4. Hardware

- [x] 4.1 Mac: the OpenPLC + truST config from the 8.2 run shows the warnings, the two fixes make the truST Download work
  - 2026-10-23, main 0e9cb97, 8.2 config copy (map 271/95, watchdog 50 ms): `--check` printed both "truST: Download refused" warnings, the map-size one naming the OpenPLC blocks; the truST row read "Cannot download" with the reason as title; Set the watchdog to 500 ms and Trim the mailboxes for truST cleared both (map hash 0x33ca8214 -> 0xdb78d780); the row read "Not downloaded yet", and Download gave cfg-truST.zip (README.txt, canworks.xml, canworks_io.st, io.toml.part), after which the row read "In sync".
