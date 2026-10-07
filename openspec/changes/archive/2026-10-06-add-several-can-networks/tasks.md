# Tasks

## 1. Plugin refactor to a network config (no behavior change)

- [x] 1.1 Add `ConfigSet` (path, dir, hash, version, warnings, notes, `networks`) around the per-network `Config` (now with name, index, work_dir, log prefix); the top-level diagnostics are copied into each network's master; the v1 parser fills one unnamed network. Verify: unit tests and `canopen_check` output on every fixture unchanged.
- [x] 1.2 Keep `Bus`, `Network`, `BusMonitor`, `ProcessImage`, `DiagHub`, dcf_gen, eds_check and eds_lint on one network's `const Config&`, and switch `PluginState` to a per-network vector of {generated config, image, hub, bus} with `cycle_start`/`cycle_end` looping over it. Verify: full CI suite (unit, sim, pingpong, sensor, slcan, trace, LSS, params, dump) green with no expected-output changes.

## 2. Schema version 2 in the plugin

- [x] 2.1 Parse `schema_version: 2` (`networks`, top-level `diagnostics`, `name`), reject v1 top-level keys and `master.diagnostics` in v2 with the spec's messages, limit 8 networks. Verify: unit tests for each scenario in canopen-config-contract and canopen-networks "Network list" / "Network names".
- [x] 2.2 Cross-network checks: name uniqueness (case-insensitive), interface and slcan device uniqueness, IEC overlap over all networks; node ID / COB-ID / auto COB-ID stay per network. Verify: unit tests for each scenario; shared fixtures in `test/fixtures/config/` for the messages.
- [x] 2.3 Per-network work directory `.canopen/<name>/` with its own reuse stamp; v1 keeps `.canopen/`. Verify: unit test that changing one network regenerates only that network, and that a v1 config still uses `.canopen/`.
- [x] 2.4 Log prefix `<name>: ` on every network, bus and node line when there are several networks; one line per network at load. Verify: unit test of labels, and the pingpong log check unchanged for v1.
- [x] 2.5 Sim test with two virtual buses: nodes with the same ID on both, PDO values from both in one scan, one bus taken away while the other keeps exchanging, then restored. Verify: new case in `test/sim/sim_tests.cpp` passes.
- [x] 2.6 vcan test: `vcan0` + `vcan1` with a pingpong slave on each and a v2 config (`config/two-networks/`), run in the vcan CI job. Verify: `test/pingpong/run.sh --two-networks` (or a sibling script) passes in CI.
- [x] 2.7 Document v2 in `docs/config.md` (Top level, a `networks[]` section, an example, what is rejected, compatibility and the update-together note). Verify: the example validates with the v2 schema and loads with `canopen_check`.

## 3. Schema files and the deploy tool's contract check

- [x] 3.1 Write `schema/canopen.v2.schema.json` referencing v1's adapter, master and node definitions; copy it into the package; `contract.py` makes the refs local and copies v1's `$defs` in (no `jsonschema` bump), so the unknown-field walker works unchanged. Verify: every example config validates against its version, and the schema/plugin agreement tests cover v2 fixtures.
- [x] 3.2 `contract.networks(cfg)` normalizer for v1 and v2, and `check_config` running per-network checks plus the cross-network ones with the plugin's wording. Verify: deploy tool tests on the shared fixtures give the same messages as the plugin.
- [x] 3.3 `clash.py`: confirm cross-network clashes inside `conf/canopen.json` are reported by the existing same-file rule. Verify: a test with a v2 bundle.

## 4. Diagnostics channel

- [x] 4.1 `DiagServer` with one hub per network: `networks` in the hello, `network` selector with `network required` / `unknown network`, `name` in status, trace bound to the picked network's interface. Verify: diag unit tests and the fake-runtime tests for each scenario in canopen-online-diagnostics.
- [x] 4.2 `diag.py` client: read `networks`, send `network` only when there are several, `--network` on every command, `status` over all networks, trace with `--network`. Verify: CLI tests against `tests/fake_diag.py` extended to two networks, and against a single-network fake without `networks` in the hello (older plugin).
- [x] 4.3 `backup`, `compare`, `restore`, `store` take `--network` and pick the node's EDS from that network. Verify: parameters tests with node 2 on two networks.
- [x] 4.4 Trace decoding with the traced network's nodes; network name saved with the trace. Verify: bustrace tests decode node 2 differently per network.
- [x] 4.5 Update `docs/diagnostics.md` (protocol fields, CLI `--network`) and `docs/trace.md`. Verify: every documented command line parses with the CLI parser test.

## 5. Exports and editor project

- [x] 5.1 DCF export per network (`<network>/node_<id>.dcf`, `--network`, the network's bit rate). Verify: dcfexport tests for the two scenarios; v1 outputs unchanged.
- [x] 5.2 DBC export per network (`<stem>_<network>.dbc`, `--network`). Verify: dbcexport tests; existing `tests/data/dbc/*.dbc` unchanged.
- [x] 5.3 Declarations and editor template with network-prefixed names when there are several networks. Verify: declare/editorproject tests; single-network output unchanged.
- [x] 5.4 Update `docs/deploy.md` (export and template sections). Verify: documented commands run in the tests.

## 6. Configurator

- [x] 6.1 In-memory model as a network list; load converts v1, save writes the lowest version per the contract spec. Verify: server tests for one-network round trip (byte-identical v1), add network (v2), remove back to one (v1).
- [x] 6.2 Network bar (tabs, add, rename, remove with confirmation) wrapping Bus and master and the node list; Online access shown once. Verify: page tests for each configurator scenario, screenshots in light and dark mode.
- [x] 6.3 Address suggestions and validation across networks. Verify: page test for the suggested-address scenario and the clash messages.
- [x] 6.4 Network picker in online view, scan, OD browser, parameters and trace; endpoints pass `network`. Verify: page tests against a two-network fake runtime.
- [x] 6.5 DCF and DBC export buttons per open tab / all networks. Verify: page test of exported file names.
- [x] 6.6 Update `docs/configurator.md`. Verify: screenshots and text match the page.

## Workflow follow-up

- Archive the change on the implementation branch once CI is green, before asking for the merge.
- Bump the deploy tool version and note in the release notes that a v2 config needs the updated plugin.
