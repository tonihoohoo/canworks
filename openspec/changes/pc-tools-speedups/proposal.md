# Proposal: pc-tools-speedups

## Why

The standalone-executables explore (2026-10-17) built and timed PyInstaller (folder and single file), Nuitka and a portable Python bundle against today's uv install. None was faster: the uv install already runs the fastest interpreter measured (python-build-standalone, statically linked, PGO + LTO). Frozen builds started 30-70 ms slower (single file 0.65 s slower on every start) and ran CPU work 15-45 % slower. So the PC tools stay on uv, and no standalone executables are built.

The same measurements found three cheap speedups that apply to the uv install:

- **First start after install is 3x slower** (about 620 ms instead of 200 ms for `canworks-config --version` on Linux), because `uv tool install` does not compile bytecode unless asked, so the first run of every module compiles it.
- **`jsonschema` is a third of the configurator's start-up imports** (about 55 of 150 ms): five modules import it at the top, although nothing validates until a config is opened or checked.
- **Trace CSV export spends most of its time quoting cells**: `_csv_cell` runs a generator per cell. A precompiled regex made exporting 200 000 frames 15-20 % faster with byte-identical output.

## What Changes

- Documented install and update commands, the release notes template, the README and the PC tools CI job use `uv tool install --compile-bytecode`. The pip route gets nothing new (pip already compiles).
- `jsonschema` is imported when the first validation runs, not at module import. `canworks-config`, `canworks-deploy --version`/`--help` and `canworks-diag --help` start without importing `jsonschema`, `python-can`, `cantools`, `j1939`, `zeroconf` or `iroh`; a unit test keeps it that way.
- Trace CSV export quotes cells with a precompiled regex; the output is unchanged.
- The decision to keep uv and not ship frozen executables is recorded in the design, with the measurements.

No config, schema, page or command-line change.

## Capabilities

### Modified Capabilities
- `canopen-pc-install`: the documented install and update commands compile bytecode, and CI installs the same way; the tools start without importing their heavy libraries.

## Impact

- Docs: `docs/install-pc.md`, `docs/deploy.md`, `README.md`, `tools/deploy/README.md`, `tools/deploy/release-notes.md` (and `test/pc-tools/test_release_notes.py`, which checks the install line).
- CI: `.github/workflows/pc-tools.yml` install step gets `--compile-bytecode` (runs only on version bumps; adds a few seconds there). No PR CI change beyond two small unit tests.
- Code: `tools/deploy/canworks/contract.py`, `simfile.py`, `simmachine.py`, `notes.py`, `configurator/simulation.py` (lazy `jsonschema`), `bustrace/formats.py` (`_csv_cell`).
- Version: patch bump of the tools package.
- No hardware tests: nothing touches CAN or the runtime.
