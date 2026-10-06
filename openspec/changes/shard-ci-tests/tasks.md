# Tasks

## 1. Sharding

- [x] 1.1 Add `.github/scripts/test_shard.py` (discover like `unittest discover`, `--pattern` repeatable, `--exclude` module regex, whole classes per shard, deterministic split, empty shard fails) with tests in `test/ci/test_shard.py`. Verify: the two `tools` shards and three page shards together run 354 + 59 = 413 tests, each once.

## 2. Workflow

- [x] 2.1 Move the vcan scripts from `plugin` into a `vcan` job with matrix groups 1 and 2. Verify: every vcan step runs in exactly one group.
- [x] 2.2 Run `tools` as two shards and `configurator-page` as three with `test_shard.py`; keep `CANOPEN_REQUIRE_PARITY` / `CANOPEN_REQUIRE_BROWSER`.
- [x] 2.3 Add the `kernel-modules` input to the build action and set it to `"false"` in `plugin`, `tools` and `stock`.
- [x] 2.4 Add `timeout-minutes` to every CI job.

## 3. Measure

- [ ] 3.1 Record the wall time and the per-job times of this PR's run in the PR description. Verify: about 3 minutes with the Lely cache warm.
