# Tasks

## 1. Package installs

- [x] 1.1 Add an install helper (skip installed packages, no `apt-get update` when nothing is missing, `Acquire::http::Timeout=20`, `Acquire::Retries=3`, `timeout 180` with one retry) with tests in `test/ci/`. Verify: a call with only installed packages makes no network request.
- [x] 1.2 Use it in the build action, the `tshark` step, the `can-utils` install in the slave test step and for the page tests' Chromium libraries; give each install step `timeout-minutes`.
- [x] 1.3 Install `tshark` only on the `tools` shard that runs `test_bustrace` (found with `test_shard.py`); set `CANOPEN_REQUIRE_TSHARK=1` there and make the decode test fail without `tshark` when it is set.
- [x] 1.4 Cache `~/.cache/ms-playwright` keyed by the Playwright version.

## 2. Builds

- [x] 2.1 Add a `targets` input to the build action (default all); `tools` builds only `canopen_check`. Verify: the DCF parity tests still run (not skipped) with `CANOPEN_REQUIRE_PARITY=1`.

## 3. vcan split

- [x] 3.1 Three vcan groups as in the design (`vcan (1/3)` … `vcan (3/3)`), each group bringing `vcan0` up itself where needed; the step-time table as a comment above the job.
- [x] 3.2 README CI section: put a new vcan test on the lightest group and update the table.

## 4. Measure

- [ ] 4.1 Record the PR run's wall time and per-job times in the PR description. Verify: about 4 minutes or less, and the longest vcan group's tests at most about 1.5 times the shortest's.
