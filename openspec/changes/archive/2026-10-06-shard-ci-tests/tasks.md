# Tasks

## 1. Sharding

- [x] 1.1 Add `.github/scripts/test_shard.py` (discover like `unittest discover`, `--pattern` repeatable, `--exclude` module regex, whole classes per shard, deterministic split, empty shard fails) with tests in `test/ci/test_shard.py`. Verify: the three `tools` shards and three page shards together run 354 + 59 = 413 tests, each once.

## 2. Workflow

- [x] 2.1 Move the vcan scripts from `plugin` into a `vcan` job with matrix groups 1 and 2. Verify: every vcan step runs in exactly one group.
- [x] 2.2 Run `tools` as three shards and `configurator-page` as three with `test_shard.py`; keep `CANOPEN_REQUIRE_PARITY` / `CANOPEN_REQUIRE_BROWSER`.
- [x] 2.3 Add the `kernel-modules` input to the build action and set it to `"false"` in `plugin`, `tools` and `stock`.
- [x] 2.4 Add `timeout-minutes` to every CI job.
- [x] 2.6 Move `stock` and `docker` to `integration.yml` (weekly, by hand, install-route pull requests); keep the stub-`docker` unit tests in CI.
- [x] 2.7 Run PC tools only on version bumps on `main`, release tags and by hand.
- [x] 2.8 README: local commands for the integration tests and the PC tools checks.
- [x] 2.5 Add the `ci-ok` job (needs every job, `if: always()`, fails on a failed or cancelled job).

## 3. Measure

- [x] 3.1 Record the wall time and the per-job times of this PR's run in the PR description. Verify: about 3 minutes with the Lely cache warm.
  Result: run on 4122692 took 3 min 0 s (was 4 min 50 s): plugin 1 min 40 s, vcan 2 min 31 s and 2 min 41 s, tools 1 min 46 s to 2 min 7 s, configurator-page 1 min 11 s to 1 min 46 s, then ci-ok. The integration workflow (stock, Docker) passed on e2ecfe7, which touches the build action.
