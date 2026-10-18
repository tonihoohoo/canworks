# Tasks

## 1. Install with bytecode

- [ ] 1.1 Add `--compile-bytecode` to every `uv tool install` command in `docs/install-pc.md` (install, update, from GitHub, from a commit), `docs/deploy.md`, `README.md` (install and the "same checks" line), `tools/deploy/README.md` and `tools/deploy/release-notes.md`; update `test/pc-tools/test_release_notes.py`.
- [ ] 1.2 `.github/workflows/pc-tools.yml`: install step uses `--compile-bytecode`.

## 2. Lazy jsonschema

- [ ] 2.1 Test: a fresh interpreter importing `canworks.configurator.server`, `canworks.cli` and `canworks.diag` has none of `jsonschema`, `can`, `cantools`, `j1939`, `zeroconf`, `iroh` in `sys.modules`. Fails on main (`jsonschema`).
- [ ] 2.2 Move the `jsonschema` imports in `contract.py`, `simfile.py`, `simmachine.py`, `notes.py` and `configurator/simulation.py` into the validating functions; `contract.Validator` becomes cached `contract.validator_class()`.
- [ ] 2.3 Measure `canworks-config --version` and time to first page before and after on Linux; note both in the PR.

## 3. CSV export

- [ ] 3.1 Test pinning `_csv_cell` quoting (comma, quote, CR, LF, plain text, numbers).
- [ ] 3.2 `_csv_cell` with a precompiled regex; measure the 200k-frame `canworks-diag convert ... .csv` before and after; output byte-identical.

## 4. Release

- [ ] 4.1 Patch bump of the tools package (`pyproject.toml` and `__version__`).
- [ ] 4.2 CI time: wall and summed job time against the baseline (median of the last 5 green `main` runs with code changes), stated in the PR.
