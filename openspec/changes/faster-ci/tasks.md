## 1. Test runner

- [ ] 1.1 `test_shard.py --jobs N|auto`: worker processes with their own `TMPDIR` and `CANWORKS_TEST_WORKER`, logs printed whole per worker, merged "class times:", non-zero exit on any failed, empty or crashed worker; `--jobs 1` runs in-process as today
- [ ] 1.2 `--split-over SECONDS` (default 30): split a large class into parts of whole test methods; `--together` units never split
- [ ] 1.3 `--serial REGEX`: matching classes run alone after the pool
- [ ] 1.4 Tests in `test/ci/`: every test runs exactly once across shards × workers, a failing worker fails the run, a killed worker is reported, the split is the same on every call, a split class runs `setUpClass` per part

## 2. Tests that run side by side

- [ ] 2.1 `tests/test_localbus.channel()` names include the process ID
- [ ] 2.2 Full deploy tool suite with `--jobs 4` locally, three times, with no failure; fix any other shared name, port or file found

## 3. CI workflow

- [ ] 3.1 `configurator-page`: 3 shards, `--jobs auto`, patterns `*_page.py` and `test_configurator_layout.py`
- [ ] 3.2 `tools`: 2 shards, `--jobs auto`, exclude every `_page` module and `test_configurator_layout`
- [ ] 3.3 Refresh `.github/ci/page-test-times.json` and `.github/ci/tool-test-times.json` from this change's run
- [ ] 3.4 `test_trace_decoding_page.py` runs (not skipped) in a page job

## 4. PC tools workflow

- [ ] 4.1 Test step through `test_shard.py --shard 1/1 --jobs auto` with the locked versions
- [ ] 4.2 Run PC tools by hand on the branch: Windows, macOS and both Linux jobs green; note their times

## 5. Docs

- [ ] 5.1 `docs/development.md`: workers, `--split-over`, `--serial`, refreshing the timing files
- [ ] 5.2 README: the local test command with `--jobs`

## 6. CI time

- [ ] 6.1 Pull request description: this run's CI wall and summed job time next to the median of the last five green `main` runs (baseline 350 s and 2610 s on 2026-10-22); PC tools run time next to 743 s and 2517 s
- [ ] 6.2 After merge: the first green `main` CI and PC tools runs' times, compared with the expected ~190 s / ~1500 s and ~310 s / ~1050 s
