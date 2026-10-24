## 1. Export

- [ ] 1.1 `plcopen_targets.py`: `TARGETS = ("generic",)`; remove `trust_io`, `trust_io_st`, the byte copy loops, `TRUST_MIN_WATCHDOG_MS` and the watchdog check, the one-request check and `_trimmed_sizes`, the loopback default host, the truST README; module docstring
- [ ] 1.2 `plcopen.py`: drop the `trust` dialect (`DIALECTS`, `NAMESPACES`, docstring)
- [ ] 1.3 `cli.py`: `--for` choices `generic`/`codesys`, help and usage texts
- [ ] 1.4 `openplcmodbus.py`: comments name strict IEC compilers, not truST

## 2. Connections and check

- [ ] 2.1 `bridgecheck.py`: `trust` out of the kind, title, field and format tables; drop `CONNECTION_BLOCKS_TRUST` and its check; writer rule with `plc` only
- [ ] 2.2 `connections.py`: GETS, `DOWNLOAD_TARGETS`, `OPENPLC_TRIM_LOSES` and the trim text, kind lists
- [ ] 2.3 Both schema copies: `kind` enum and field descriptions without `trust`

## 3. Configurator

- [ ] 3.1 `bridge.js`: Add connection list, format list, blocks list without the truST limit, `trimMailboxesForTrust`, `noMailboxesForTrust`, watchdog hint, Writes default, page texts
- [ ] 3.2 `app.js`: drop the `watchdog-trust`, `trim-trust` and `trust-blocks-none` fixes; "Works with" text
- [ ] 3.3 `target.js`, `server.py`: texts and kind lists

## 4. Tests and CI

- [ ] 4.1 `test_plcopen.py`: remove the truST cases and goldens (`tests/data/plcopen/trust/`), `--for trust` usage error test, `TrustImport` imports and builds the generic export with all mailboxes (no `canworks_io.st`)
- [ ] 4.2 `test_configurator_bridge.py`, `test_configurator_bridge_page.py`, other page tests: truST cases out or moved to Other PLC; a `kind: trust` config fails the check
- [ ] 4.3 CI step name, `ci_changes.py`, `plcopen-paths.txt` and `test_changes.py` wording ("compile check"); CI time: wall and summed job time against the main baseline, in the PR description

## 5. Docs and version

- [ ] 5.1 README.md (other PLCs line, Connections line, docs table)
- [ ] 5.2 `docs/plcopen.md` (target table, truST section, examples), `docs/modbus-bridge.md`, `docs/configurator.md`, `docs/deploy.md`, `docs/plc-library.md`, `docs/node-red.md`, `examples/node-red-dashboard/` (README and flow text); truST only in `docs/development.md` as the CI compiler
- [ ] 5.3 Minor version bump (0.134.0); regenerate the version-stamped goldens

## 6. Hardware checks

None: no bridge, device or runtime behaviour changes. A desktop check of Add connection and an Other PLC Download on Mac is enough (6.1).

- [ ] 6.1 Mac configurator: Add connection lists no truST; an Other PLC PLCopen Download gives the zip; an old config with `kind: trust` shows the check error in Problems
