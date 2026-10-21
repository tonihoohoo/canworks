## Context

Python versions today (main 0078838, tools 0.94.x):

| Where | Python | Ours to change |
|---|---|---|
| One-line installers, docs, release notes | uv-managed 3.12 | yes |
| CI (all `setup-python` and `uv run --python`) | 3.12 | yes |
| `tools/deploy` `requires-python` | `>=3.10` | yes |
| Runtime image v4.2.4 (`debian:bookworm-slim`): `/opt/canworks/venv` (dcfgen, EDS lint), editor hook in the runtime venv | 3.11 | no (upstream image) |
| `install-bridge.sh`, `install-link.sh` on a host | host `python3` | no |
| `docker/bridge` | bookworm 3.11 | yes, not needed |
| CODESYS import script | IronPython 2.7 | no |

Measured 2026-10-21 on Linux x86_64: the deploy tool suite (2139 tests) passes on 3.10, 3.11, 3.12, 3.14, 3.15 in 618-693 s; the release wheel installs with the installer's command and passes `smoke.py` on 3.12, 3.14, 3.15; start time is the same within 30 ms. Native wheels for cp314: rpds-py, zeroconf, pywin32, numpy, bitstruct, msgpack, wrapt; for cp315 all but wrapt.

## Goals / Non-Goals

**Goals:** PCs on a fully supported Python; the code the runtime runs tested on the runtime's Python; a floor that resolves on every platform; no added CI time.

**Non-Goals:** shipping our own Python into the runtime image; changing the bridge image's Debian release; using 3.12+ language features (the same package runs on the runtime's 3.11).

## Decisions

- **3.14 now, 3.15 later.** 3.15.0 is 12 days old and `wrapt` has no cp315 wheel yet. The installers keep `--python` / `-Python`, so a user can pick 3.15 today; the default moves in a later one-line change (around 3.15.2).
- **Floor 3.11, not 3.12.** The deploy tool is installed into the runtime image's 3.11 venv (EDS lint, link service), so the package must keep running there. 3.11 is also what makes uv's universal resolution of `libusb>=1.0.30` (needs >=3.11) succeed.
- **CI split by where the code runs, not a matrix.** A matrix would double jobs; instead each existing job picks one version: `plugin` (CiA 402 ST tests use the deploy tool), `vcan`, `tools` shards and `integration` on 3.11; `configurator-page`, `browser`, `local-runtime` and `pc-tools.yml` on 3.14. Both versions are in the runners' tool cache, so no download time.
- **Skip check compares the Python.** `uv tool list --show-python` prints `canworks v0.94.2 [CPython 3.12.15]`. The installer skips only when the version matches and, when `--python` is a version (`3.14`), the environment's `major.minor` matches it; a path given to `--python` keeps today's version-only check. Without this, existing PCs would stay on 3.12 until the next release.
- **uv minimum.** uv learned 3.14.0 in 0.9.0. When `uv --version` is older, the installers run `uv self update`; when that fails (uv from a package manager), they stop and say to update uv with that package manager. The minimum is a constant next to the default Python, so moving to 3.15 updates both.

## Risks / Trade-offs

- A dependency drops 3.11 before the runtime image moves on → the tools CI shards fail on 3.11 first; pin the dependency's floor or ask upstream. rpds-py already requires >=3.11.
- Existing installs reinstall once on the next line run (about a minute on Windows with bytecode compile) → said in the release notes.
- Windows desktop shortcuts point into the tools' environment, which uv recreates → the installer recreates the shortcut on every install (unchanged behavior); covered by the desktop check.
