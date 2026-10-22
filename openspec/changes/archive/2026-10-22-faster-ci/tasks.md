## 1. Test runner

- [x] 1.1 `test_shard.py --jobs N|auto`: worker processes with their own `TMPDIR` and `CANWORKS_TEST_WORKER`, logs printed whole per worker, merged "class times:", non-zero exit on any failed, empty or crashed worker; `--jobs 1` runs in-process as today
- [x] 1.2 `--split-over SECONDS` (default 30): split a large class into parts of whole test methods; `--together` units never split
- [x] 1.3 `--serial REGEX`: matching classes run alone after the pool
- [x] 1.4 Tests in `test/ci/`: every test runs exactly once across shards × workers, a failing worker fails the run, a killed worker is reported, the split is the same on every call, a split class runs `setUpClass` per part

## 2. Tests that run side by side

- [x] 2.1 `tests/test_localbus.channel()` names include the process ID
- [x] 2.2 Full deploy tool suite with `--jobs 4` locally, three times, with no failure; fix any other shared name, port or file found
  - 3 of 3 runs green, 1864 tests in 169–172 s (one process: 667 s). The adapter lock lives in the temporary folder, so each worker's own `TMPDIR` already keeps the workers apart; `test_j1939_sim` channel names got the process ID too.
  - The page suite in 4 workers (458 s locally) showed two races that a busy machine exposes: `DevicesPage` read the job log before it arrived, and `trace_page.Live` expected the stop to be the last request although a status poll can follow it. Both now wait for or look for the right thing.

## 3. CI workflow

- [x] 3.1 `configurator-page`: 3 shards, `--jobs auto`, patterns `*_page.py` and `test_configurator_layout.py`
- [x] 3.2 `tools`: 2 shards, `--jobs auto`, exclude every `_page` module and `test_configurator_layout`
- [x] 3.3 Refresh `.github/ci/page-test-times.json` and `.github/ci/tool-test-times.json` from this change's local 4-worker runs, scaled to the CI totals (page ~1170 s, tools ~600 s)
- [x] 3.4 `test_trace_decoding_page.py` runs (not skipped) in a page job
  - Its tests pass in page shards 2/3 and 3/3, none skipped.

## 4. PC tools workflow

- [x] 4.1 Test step through `test_shard.py --shard 1/1 --jobs auto` with the locked versions
- [x] 4.2 Run PC tools by hand on the branch: Windows, macOS and both Linux jobs green; note their times
  - Windows 316 s, macOS 259 s, Linux arm 201 s, Linux x64 166–221 s; wall 316 s, summed 942 s (was 743 s and 2517 s).
  - Running side by side showed three real races, all fixed in the code rather than the tests: the configurator answered a denied POST without reading its body (Windows then resets the connection and the client sees no 403), `adapter-serve` logged its start line before the Ctrl-C handler was in place (exit 130), and `/api/online/status` read the hello twice (null when another request closed the connection in between). Two Windows-only runner details also came up: workers get an absolute `--top`, and stdin as a closed pipe, since `NUL` claims to be a terminal.

## 5. Docs

- [x] 5.1 `docs/development.md`: workers, `--split-over`, `--serial`, refreshing the timing files
- [x] 5.2 README: the local test command with `--jobs`

## 6. CI time

- [x] 6.1 Pull request description: this run's CI wall and summed job time next to the median of the last five green `main` runs (baseline 350 s and 2610 s on 2026-10-22); PC tools run time next to 743 s and 2517 s
  - CI on the branch: wall 210–244 s (median 219 s over four runs), summed 1593 s and 1474 s on the last two, 13 jobs instead of 15.
- [ ] 6.2 After merge: the first green `main` CI and PC tools runs' times, compared with the expected ~190 s / ~1500 s and ~310 s / ~1050 s
