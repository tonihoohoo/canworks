## Context

An explore checked README.md, docs/ and openspec/specs/ against `main` at 33e2872. README and docs were current apart from one command name. The specs carry leftovers from the plugin, as listed in the proposal. Each delta below was checked against the code:

| Spec text | Code on main |
|---|---|
| PLC-cycle SYNC choice, DBC scenarios | `app.js` SYNC source offers Off and Timer; `contract.py` and `config.cpp` refuse `"sync_source": "plc_cycle"`; `dbcexport.py` has no `sync_source` |
| `scan_watchdog_ms` warns as unused | Not in the schema or `targets.py`; the bridge (`check_known`) and the PC check warn "unknown field '…' (…) ignored" |
| CiA 402 tab, axis | No tab; `server.py` strips `axis` from old configs; an `axis` key is an unknown field |
| `--bundle`, `--project`, `--doc-cycle-ms`, `--runtime` | Not in `cli.py`'s parser (`--project` exists only on `library`); argparse rejects them as unrecognized |
| install-runtime, install-stock | Deleted; `release-deploy.yml` ships install-pc and install-bridge (`.sh`, `.ps1`) and `device-probe.sh` |
| `canworks-deploy diag` | No such subcommand; `diag.py` `mailbox_status_line` is printed by `canworks-diag status` |
| Bit channel locations, Suggest, `%IX` placement | `targets.py`: `bits.iec_location` used by no target and refused by the bridge; the bridge column shows the bit's coil or discrete-input number |
| PDO headings | `target.js`: "Inputs (TPDOs, device to Modbus registers)", "Outputs (RPDOs, Modbus registers to device)", column "Location" |
| Recent tag | `TARGET_TITLES`: "Modbus bridge", "CODESYS", "OpenPLC plugin (removed)" |
| Node sheet: axis, program download | `software_file`/`software_version` are removed node fields; `docexport.py` has neither |
| PLCopen tests, three targets | `plcopen_targets.TARGETS = ("trust", "generic")`; `--for codesys` is refused |
| CI paths | `plugin/src/network.cpp`, `plugin/src/j1939/ecu.cpp` and `codesys/script/import_canworks_modbus.py` do not exist; `.github/ci/plcopen-paths.txt` names the real ones |
| "Scan" in bridge specs | `bridge_host.h`: "There is no scan": the loop publishes inputs every 1 ms, and each accepted write publishes the output snapshot at once |

## Goals / Non-Goals

**Goals:** every spec requirement and scenario touched here says what `main` does; the two wrong docs lines are fixed; a guard stops the same class of slip.

**Non-goals:**
- No behaviour change: if a spec and the code disagree on purpose, the spec moves.
- No renaming of `plugin/` to `engine/`. It is only a name, and the move would touch every CI path filter. If wanted, that is a change of its own.
- No change to the word "runtime" for what the configurator connects to. `docs/wording.md` makes it the deliberate term.
- No line-by-line review of requirements that never touched the plugin.

## Decisions

**Define "scan" once, don't reword it everywhere.** About 25 requirements in J1939, raw CAN, SDO variables, supervision, slave, gateway, CiA 309 and diagnostics say "next scan", "last finished scan" or "PLC scan". For the bridge these have a precise meaning: the 1 ms input publication, and the output snapshot of the last accepted Modbus write. One ADDED requirement in `modbus-bridge` (Bridge image timing) states that mapping. The other specs keep their wording. Rewording all 25 would be a large diff with no behaviour in it, and it would conflict with any running change on those specs.

*Alternative:* reword each requirement. Rejected for now. It can still happen spec by spec when a change touches one.

**Purpose lines by hand.** OpenSpec deltas carry requirements only. The apply step edits the `## Purpose` paragraph of each listed spec directly, the same way earlier changes fixed purpose lines in their own PR.

**Dead configurator branches go with the spec.** The spec drops the bit-location column, so the code that would show it under some target goes too: `bitTable`, `mapBit`, `mapAllBits` and `bitsReplaceLocation` under a `usedBy("…bits.iec_location")` that is always false. Without this, the next reader of `app.js` would take it for a live feature.

**Guard in spec-check.** Widen `test_readme.py` (or add a sibling test in the same style, with no dependencies):
- for `canworks-deploy <word>` and `canworks-diag <word>` written in backticks, `<word>` must be a subcommand or an option the tool takes;
- every backticked repository path (`scripts/…`, `tools/…`, `plugin/…`, `config/…`, `docs/…`, `.github/…`, `test/…`) must exist, with a glob allowed;
- the check covers README.md, `docs/*.md` and `openspec/specs/**/spec.md`. Archived changes are history and are not checked.

## Risks / Trade-offs

- [The guard flags paths that specs name on purpose as gone, such as `install-stock.sh` in a "deleted" sentence] → After this change no live spec names a deleted path. If one is needed later, an allow list in the test covers it, like `NOT_PAGE` in the README test.
- [Removing the dead bit-location branches breaks a page test that asserts them] → Update or drop that assertion in the same PR. The bridge-number column test stays.
