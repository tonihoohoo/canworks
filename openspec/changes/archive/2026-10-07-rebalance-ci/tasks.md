# Tasks

## 1. Package installs

- [x] 1.1 Add an install helper (skip installed packages, no `apt-get update` when nothing is missing, `Acquire::http::Timeout=20`, `Acquire::Retries=3`, `timeout 120` per call with up to two retries) with tests in `test/ci/`. Verify: a call with only installed packages makes no network request.
- [x] 1.2 Use it in the build action, the `tshark` step, the `can-utils` install in the slave test step and for the page tests' Chromium libraries; give each install step `timeout-minutes`.
- [x] 1.3 Install `tshark` only on the `tools` shard that runs `test_bustrace` (found with `test_shard.py`); set `CANOPEN_REQUIRE_TSHARK=1` there and make the decode test fail without `tshark` when it is set.
- [x] 1.4 Cache `~/.cache/ms-playwright` keyed by the Playwright version.
- [x] 1.5 Cache the downloaded .deb files per runner image (build action, `tshark`, Chromium libraries) and install them with `dpkg -i` before trying apt. Verify: a second run on the same image logs the cached files installed and no apt attempt.

## 2. Builds

- [x] 2.1 Add a `targets` input to the build action (default all); `tools` builds only `canopen_check`. Verify: the DCF parity tests still run (not skipped) with `CANOPEN_REQUIRE_PARITY=1`.

## 3. vcan split

- [x] 3.1 Three vcan groups as in the design (`vcan (1/3)` … `vcan (3/3)`), each group bringing `vcan0` up itself where needed; the step-time table as a comment above the job.
- [x] 3.2 README CI section: put a new vcan test on the lightest group and update the table.

## 4. Measure

- [x] 4.1 Record the PR run's wall time and per-job times in the PR description. Verify: about 4 minutes or less, and the longest vcan group's tests at most about 1.5 times the shortest's.
  Result: run on 55864bf (package caches warm) took 3 min 53 s (was about 6, spikes to 10.7): plugin 3.1 min, vcan 3.0 / 3.7 / 3.4 min (tests 105 / 113 / 121 s), tools 2.0-2.7 min, configurator-page 2.0-3.1 min, then ci-ok. Build action 58-98 s (was 223-316 s on the cold runs of this PR, where the first apt attempt stalled twice and the retry finished in 65-80 s). The integration workflow (stock, Docker) passed.
