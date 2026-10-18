# Design: pc-tools-speedups

## Context

Measured on Linux x86_64, tools 0.81.2 (details in the project research note `standalone-executables-2026-10-17.md`):

| Build | deploy --version | config to page | 200k-frame CSV convert |
|---|---|---|---|
| uv install (python-build-standalone 3.12) | 151 ms | ~210 ms | 4.8-5.0 s |
| uv install, first run without bytecode | 619 ms | | |
| PyInstaller folder | 195-225 ms | 270 ms | 6.0-7.1 s |
| PyInstaller single file | 849 ms | 923 ms | 7.8 s |
| Nuitka standalone (LTO) | 176 ms | 217 ms | 5.9 s |
| Portable Python bundle | 161 ms | 227 ms | 5.3 s |

The configurator already imports python-can, cantools, j1939, zeroconf and iroh lazily. What is left at start is ~150 ms of imports, of which `jsonschema` (with `attrs`, `referencing`, `rpds`) is ~55 ms.

## Goals / Non-Goals

**Goals:** faster first start after install and update; faster configurator and deploy tool start; faster trace CSV export; keep it that way with a test.

**Non-Goals:** standalone executables, installers or code signing (measured slower, and they would add release build jobs); a Python version change (3.14 was ~5 % faster on decoding but slower to start); a wider performance hunt in the trace decoder.

## Decisions

### Keep uv; no frozen executables

The uv install is the fastest measured form, needs no signing for our own files, and costs no extra CI. Frozen builds would add four release jobs and AV/Gatekeeper friction for a slower result. If people without internet at install time ever need the tools, the portable Python bundle (python.org's signed embeddable Python on Windows) is the form to revisit, not PyInstaller or Nuitka.

### `--compile-bytecode` in every documented uv install

`uv tool install --compile-bytecode` compiles all `.pyc` at install (a few seconds, once). It is added to the install and update commands in `install-pc.md`, the README, `tools/deploy/README.md`, `docs/deploy.md` and the release notes template, and to the `pc-tools.yml` install step so CI installs as the docs say. The "straight from GitHub" and "from its commit" commands get it too. A user who already installed without it gets bytecode on the next update.

### Lazy `jsonschema`

Each of the five modules that import `jsonschema` at the top gets the import inside the functions that validate. `contract.Validator`, today built at import time, becomes `contract.validator_class()`, which builds the extended validator once and caches it; its two callers (`contract.py`, `simfile.py`) use it. `best_match` is imported at its call sites. Alternative considered: a module `__getattr__` proxy; rejected as harder to read for the same effect.

A unit test starts a fresh interpreter (`sys.executable -c`), imports `canworks.configurator.server`, `canworks.cli` and `canworks.diag`, and fails when any of `jsonschema`, `can`, `cantools`, `j1939`, `zeroconf`, `iroh` is in `sys.modules`. It costs well under a second, so it fits the existing tools shards.

### CSV quoting with a regex

`_csv_cell` uses a module-level `re.compile(r'[,"\n\r]').search` and skips `str()` for strings. Same quoting rules, so existing CSV tests and output stay as they are; a test pins the quoting of a comma, a quote, CR and LF.

## Risks / Trade-offs

- A lazy import moves an `ImportError` from start to first use. The dependency is required by the package, so this only matters in a broken install; the smoke run still validates a config.
- `--compile-bytecode` makes install a few seconds longer. Acceptable for one-off installs.
- CI time: two small unit tests in the existing tools shards; `pc-tools.yml` runs only on version bumps. The PR states the CI wall and summed time against the baseline.
