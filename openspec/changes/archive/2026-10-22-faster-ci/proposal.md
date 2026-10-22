# Proposal

## Why

A code change waits about 6 minutes for CI, and a merged version bump waits another 12 minutes for the PC tools run before it is released. Measured from the GitHub API job start and end times of the green runs on 2026-10-21 and 2026-10-22:

| Workflow (green runs) | Wall time, median | p90 | Summed job time, median |
|---|---|---|---|
| CI, full code run (80 runs, push and pull request) | 350 s (5.8 min) | 375 s on `main` | 2610 s (43.5 min), 15 jobs |
| PC tools on `main` (27 runs, about one per merge) | 743 s (12.4 min) | 831 s | 2517 s (42 min), 4 jobs |

Where the CI time goes (median job time, test step in brackets):

| Job | Runners | Each | Test step | Ends the run |
|---|---|---|---|---|
| configurator-page | 4 | 286–313 s | ~270 s | 71 of 80 runs |
| tools | 3 | 214–264 s | ~195 s | 3 |
| vcan | 3 | 158–182 s | 97–125 s | 4 |
| plugin | 1 | 160 s | ctest 88 s, CiA 402 24 s | 2 |
| changes, spec-check, banned-words, ci-ok | 1 each | 3–11 s | | |

The Python tests are 1630 of the 2610 summed seconds, and the page tests decide the wall time. Each runner has 4 CPUs, but every shard runs its tests one at a time, and the tests mostly wait: the browser, the configurator server, fixed waits, timers. On a 4-CPU machine, measured on this change's branch:

- 4 page-test shards of the 16-way split, one after another: 424 s. The same 4 at the same time: 159 s (2.7x), every test passing.
- The whole deploy tool test suite in one process: 667 s. In 4 processes at the same time: 176 s (3.8x). One test failed because two processes opened the same virtual adapter name; nothing else clashed.

Three smaller problems showed up on the way:

- The largest page classes no longer fit any split: `Probes` takes 117 s, `Layout` and `Page` 83 s each. A shard can't finish before its largest class does.
- `.github/ci/page-test-times.json` adds up to 711 s, but the page tests now take about 1170 s. New classes counted as the median, so the shards only stayed balanced by luck.
- `test_trace_decoding_page.py` is a Playwright test, but its file name doesn't match the page jobs' `test_configurator_*page.py` pattern. The tools jobs pick it up and have no browser, so it is skipped on every run.

The PC tools workflow runs the same deploy tool suite in one process on each system: 540–657 s of its 583–743 s jobs. Every version-bump merge waits for the Windows job before the release.

## What Changes

- **Test workers inside a job.** `.github/scripts/test_shard.py` gets `--jobs N` (default: the machine's CPU count). It splits its shard over N worker processes by recorded time, runs them at the same time, prints each worker's whole log when it ends, merges the "class times:" line, and fails when any worker fails or dies. Each worker has its own temporary folder and its number in `CANWORKS_TEST_WORKER`.
- **Large classes split by test.** A class whose recorded time is over `--split-over` seconds (default 30) is cut into parts of whole test methods, so it can run on several workers or runners. Each part runs the class's `setUpClass` again; that costs a few seconds and keeps tests independent.
- **Fewer, faster runners in CI.** The page tests use 3 runners with 4 workers each instead of 4 single-process runners. The tools tests use 2 runners with 4 workers each instead of 3. vcan and plugin stay as they are; they become the longest jobs, at about 3 minutes.
- **PC tools in parallel.** The PC tools workflow runs the suite through `test_shard.py --shard 1/1 --jobs auto` on Windows, macOS and both Linux runners, instead of `unittest discover` in one process. A `--serial REGEX` option runs the matching classes alone after the pool, for a test that proves too timing-sensitive on a busy runner (empty at first).
- **Tests that can run side by side.** Virtual adapter channel names in the tests include the process ID, so two workers never take the same adapter lock. Any other shared name found while applying gets the same fix.
- **Every page test in the page jobs.** The page jobs select `*_page.py` and `test_configurator_layout.py`, and the tools jobs leave out every `*_page.py`, so `test_trace_decoding_page.py` runs with a browser.
- **Current class times.** Both timing files are refreshed from this change's own CI run. `docs/development.md` explains workers, `--split-over` and the refresh.

### Expected effect (to be measured on the change's pull request)

| | Now (median) | Expected |
|---|---|---|
| CI wall time, full code run | 350 s | about 190 s (3.2 min), set by vcan and plugin |
| CI summed job time | 2610 s | about 1500 s (12 jobs instead of 15) |
| PC tools wall time | 743 s | about 300–330 s (Windows) |
| PC tools summed job time | 2517 s | about 1050 s |
| Merge of a version bump to release | ~12.5 min | ~5.5 min |

Page jobs go from ~297 s to ~170 s each and tools jobs from ~242 s to ~130 s. The estimates use the measured 2.7x (page) and 3.8x (tools) speed-ups, minus about 10% for GitHub runners being slower than the measuring machine. Windows and macOS (3 CPUs) are estimated at 3x and 2.5x.

### Non-goals

- vcan tests in parallel. They share `vcan0` and bus timing. Running them on separate interfaces side by side could take another ~40 s off the wall time, but it touches every vcan script. That would be a separate change.
- Caching more. Lely, ccache, Chromium, the apt packages and uv are already cached. Their restore steps take 2–7 s each in the measured runs.
- Moving tests to other workflows, skipping tests or dropping coverage.
- The other pull request workflows (Integration, Local runtime, Browser, bridge image). `ci-ok` is the only required check, so they don't delay a merge.

## Capabilities

### Modified Capabilities

- `canopen-ci`: "Parallel test jobs": test workers inside a job, classes split by test, page tests selected by `*_page.py`, and the new wall-time target.
- `canopen-pc-install`: "Tested on Windows, macOS and Linux": the suite runs in parallel workers.

## Impact

- `.github/scripts/test_shard.py`: `--jobs`, `--split-over` and `--serial`, worker processes, merged class times.
- `test/ci/` tests for the runner: the same tests run once across workers, a failing worker fails the run, a crashed worker is reported, the class split is deterministic.
- `.github/workflows/ci.yml` (page and tools matrices, patterns) and `.github/workflows/pc-tools.yml` (test step).
- `.github/ci/page-test-times.json` and `.github/ci/tool-test-times.json` refreshed.
- `tools/deploy/tests/test_localbus.py` (and any other shared test resource names).
- `docs/development.md`. README: the local test command can use `--jobs`.
