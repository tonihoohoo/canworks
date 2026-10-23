## 0. Start

- [x] 0.1 Rebase on `main` and run `openspec validate tidy-specs-after-plugin-removal --strict` (CI's OpenSpec 1.14.0). If a change merged since 33e2872 touched one of the modified requirements, re-copy that requirement from `main` before applying the edits

## 1. Spec deltas (applied at archive)

- [x] 1.1 Check each MODIFIED block against `main` once more: the SYNC source choices, PDO headings, bit table and Recent tag in the configurator; the `cli.py` options; the release assets; and `diag.py`'s mailbox line

## 2. Purpose lines (edited by hand, deltas do not carry them)

- [x] 2.1 `canopen-master-bringup`: brings a network up in canworks-bridge (not "from the OpenPLC runtime")
- [x] 2.2 `canopen-pdo-io`: PDO values exchanged with the bridge's byte image (1 ms input publication, outputs per accepted write; see `modbus-bridge` "Bridge image timing"), not "once per scan cycle"
- [x] 2.3 `canopen-node-supervision`: "the bridge keeps serving" instead of "the PLC keeps scanning"
- [x] 2.4 `canopen-slave-device`, `canopen-gateway`: "the bridge", not "an OpenPLC controller"
- [x] 2.5 `canopen-configurator`: the config of a canworks project (a config folder or an editor project's `canworks/` folder) for the Modbus bridge or CODESYS
- [x] 2.6 `canopen-config-contract`: shared by the bridge, the PC tools and the configurator (not "any future editor GUI")
- [x] 2.7 `canopen-deploy`: checks a config, uploads it to canworks-bridge over the diagnostics channel, writes it into editor projects and exports it (no runtime upload over REST)
- [x] 2.8 `plc-library`: drop "how each block family finds its plugin interface version"
- [x] 2.9 `toolkit-names`: drop "plugin and its files on the PLC"; name the bridge and its files on the device

## 3. Docs and dead code

- [x] 3.1 `docs/plc-library.md` and `docs/modbus-bridge.md`: `canworks-diag status` instead of `canworks-deploy diag`
- [x] 3.2 README: the PC tools table says `canworks-canopen-sim` runs on the bridge's device, next to "Five commands in one package" (or the row moves under the table)
- [x] 3.3 `diag.py`: remove the `interpolation_period_us` lines in `_print_protocol_status` (nothing sends it)
- [ ] 3.4 `configurator/static/app.js`: remove the bit-location branches under `usedBy("…bits.iec_location")` in `bitTable`, `mapBit`, `mapAllBits` and `bitsReplaceLocation` (no target uses them); keep the bridge's coil and discrete-input numbers. Update any page test that asserts the removed column (none did; `/api/place`'s dead `bit_in`/`bits_in` directions and their server test went too)

## 4. Guard

- [x] 4.1 Spec-check test (`test_readme.py` widened, or a sibling in the same style, with no dependencies): in README.md, `docs/*.md` and `openspec/specs/**/spec.md`, a backticked `canworks-deploy WORD` or `canworks-diag WORD` must use a real subcommand or option, and a backticked repository path (`scripts/`, `tools/`, `plugin/`, `config/`, `docs/`, `test/`, `.github/`, globs allowed) must exist. An allow list covers deliberate exceptions
- [x] 4.2 The guard finds nothing on the branch; on `main` before this change it would have flagged `canworks-deploy diag` and the missing `install-runtime`/`servo402` paths (shown in the PR)

## 5. Close

- [ ] 5.1 Tools patch version bump (app.js, diag.py); CI time against the median of the last five green `main` runs in the PR
- [ ] 5.2 `openspec archive tidy-specs-after-plugin-removal --yes` on the branch; Purpose edits from section 2 checked after the archive
