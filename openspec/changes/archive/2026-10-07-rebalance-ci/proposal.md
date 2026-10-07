# Proposal

## Why

After `shard-ci-tests` a code change's CI run took about 3 minutes. A day later a normal run takes about 6 minutes, and about one run in eight takes 9 to 11 minutes. Measured over the 105 CI runs since then:

- **One vcan runner carries the new tests.** Which runner a vcan test uses is fixed in the workflow, and every vcan test added since the split went to group 2 (raw frames and bit rate 53 s, standalone device simulator 60 s, PC-direct commissioning 32 s, master and its own slave 29 s). Group 2 now runs about 4.0 min of tests, group 1 about 1.6 min, so every run waits for group 2.
- **Package installs sometimes stall.** The shared build action (six jobs per run), the `tshark` step (three `tools` shards) and `playwright install --with-deps` (three `configurator-page` shards) all install from the Ubuntu mirror. Normally that takes seconds; in about one run in eight one of them waits 3 to 8 minutes with no output. In one log, `apt-get update` plus six small packages took 7 min 45 s while the build itself took under a minute.
- **The `tools` shards build every target** (plugin, simulator, every test binary) although their tests only run `build/canopen_check` for the DCF parity check.

## What Changes

- The vcan tests run on three runners instead of two, split by their measured time so each runner has about the same amount (about 2 minutes). The workflow names each test's runner as now; the split and the times it is based on are written down in the workflow so the next test goes onto the lightest runner.
- Package installs get a time limit and one retry, and apt gets short network timeouts with retries, so a stalled mirror costs about a minute instead of up to eight. Packages the runner already has are not installed again, and when nothing is missing, `apt-get update` is skipped.
- `tshark` is installed only in the `tools` shard that runs the Wireshark decode test; the decode test is required there (fails instead of skipping without `tshark`), so the coverage stays.
- The Chromium download for the page tests is cached between runs; its system libraries are still installed when missing.
- The shared build action takes a list of build targets; the `tools` shards build only `canopen_check`.
- Same coverage: every test still runs once per change.
- Expected: a normal code change's run goes from about 6 minutes back to about 3.5 to 4, and a slow mirror adds about a minute instead of 3 to 8.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `canopen-ci`: the parallel test jobs requirement spreads the vcan tests by time over three runners, lets jobs build only the targets they need and updates the expected wall time; a new requirement bounds package installs.

## Impact

- `.github/workflows/ci.yml`, `.github/actions/build-plugin/action.yml`, possibly a small install helper under `.github/scripts/`.
- `tools/deploy/tests/test_bustrace.py`: the Wireshark decode test fails instead of skipping when `CANOPEN_REQUIRE_TSHARK=1` is set.
- Check names: `vcan (1/2)` and `vcan (2/2)` become `vcan (1/3)` to `vcan (3/3)`. The ruleset requires only `ci-ok`, so nothing to change there.
- No change to the plugin, the tools or what their tests check.
