# Design

## Measurements behind the choices

Baseline: the 80 green full-code CI runs and 27 green PC tools runs from 2026-10-21 08:30Z to 2026-10-22 17:00Z. Job and step times come from the Actions API (`started_at`, `completed_at`), and class times from the shards' "class times:" lines of the `main` run for #234. Wall time is from the first job's start to the last job's end. There was no queueing: the slowest job of a run started at most 3 s after the run was created.

Local check on a 4-CPU Linux container with Chromium headless (Playwright 1.56):

| What | One process | 4 processes at once |
|---|---|---|
| Page shards 1–4 of 16 (117 tests) | 424 s | 159 s, all pass |
| Deploy tool suite without page tests (1852 tests) | 667 s | 176 s; 1 failure, the shared adapter name |

Each worker ran about 10–20% slower than it did alone. That is the cost of sharing 4 CPUs, and it is far smaller than the waiting the parallel runs remove.

## Worker processes, not threads or pytest-xdist

The suites are `unittest` with class fixtures (a browser per class, servers, fake runtimes), and several tests change process state: environment, current folder, signal handlers. Separate processes keep that isolated without changing the tests, and need no new dependency. The parent process:

1. computes the shard as today (same split on every runner);
2. splits the shard's units over N workers with the same largest-first rule;
3. starts `python test_shard.py --worker FILE` for each, where FILE lists the test ids, with `TMPDIR` set to a folder of the worker's own and `CANWORKS_TEST_WORKER=k`;
4. waits for all workers and prints each worker's whole log as it ends, under a `== worker k/N ==` header, so the CI log stays readable;
5. merges the workers' class times into one "class times:" line, and exits non-zero when any worker failed, errored, found no tests or exited without a result file.

`--jobs 1` runs in-process as today. Local runs default to the CPU count; `--jobs 1` gives the old behaviour for debugging.

## Splitting large classes

The split unit is a class, except that a class whose recorded time is over `--split-over` seconds (default 30) becomes ⌈time / 30⌉ parts of consecutive test methods with equal test counts. Each part is a unit with an equal share of the time. A part runs `setUpClass` and `tearDownClass` itself. For the page classes that means one more browser start per part, about 1–2 s. The order of methods within a part is the usual alphabetical one.

The `--together` units, the parity classes, are never split.

With the current times this makes `Probes` 4 parts, `Layout` and `Page` 3 each, and `EndToEnd`, `ParamsPage`, `OnlinePage` and `Files` 2 each. The longest unit is then about 35 s. The longest single test, `test_every_view_fits`, takes 35 s on its own.

## CI layout

- `configurator-page`: 3 runners × 4 workers. About 1170 s of page tests / 3 runners / ~2.4x ≈ 160 s of tests, plus ~25 s of setup.
- `tools`: 2 runners × 4 workers. About 600 s / 2 / ~3.4x ≈ 90 s, plus ~45 s of setup (and the `canopen_check` build on the parity runner).
- `plugin` (160 s) and `vcan` (158–182 s) are unchanged and set the new floor of about 3 minutes.

Fewer runners lower the summed time too, because each runner pays checkout, Python and dependency setup (~20–45 s).

## PC tools workflow

`unittest discover` becomes `python .github/scripts/test_shard.py --shard 1/1 --jobs auto --start tools/deploy/tests --top tools/deploy`, under the same `uv run` with the locked versions. The runner's Python has no Playwright, so the page tests skip as they do now. The GitHub runners have 4 CPUs on Windows and both Linux images, and 3 on `macos-14`.

macOS runners oversleep short timed waits (60–170 ms for a 20 ms wait), and a busy runner makes that worse. The tests already allow for it. If one still fails only under load, `--serial REGEX` runs the matching classes alone after the pool, and the class goes in the workflow's serial list with a comment. A flaky test does not get a retry.

## Shared resources between workers

- **Adapter locks.** `canworks.localbus.adapter._Lock` is machine-wide by adapter name. `tests/test_localbus.channel()` names `localbus-test-N` with a per-process counter, so two workers used the same name. The name gets the process ID.
- **Ports.** The servers in the tests bind port 0 (the local runs passed). Any fixed port found during apply moves to port 0 or is offset by `CANWORKS_TEST_WORKER`.
- **Home and config folders.** The tests already use temporary folders. Each worker's own `TMPDIR` keeps `tempfile` users apart.

## Risks

- A hidden order dependency between tests can surface once the order changes. The local runs found only the adapter name. Any other one is fixed in the test.
- A worker that hangs stops the job at its time limit, as a hung test does today. The parent prints which workers had not finished.
- A faster run can make a slow test the new floor. The runner prints the longest units, so the split can be adjusted.

## Measuring the result

The change's pull request states the CI wall and summed time of its own run next to the median of the last five green `main` runs (the "CI time kept" rule). After merge, the first PC tools run on `main` gives the new PC tools numbers.
