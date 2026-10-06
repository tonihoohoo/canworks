# Proposal

## Why

A code change's CI run takes about 4 min 50 s (main, first run of the public repository). The long poles are three jobs that each run their tests one after another:

- `plugin` 4 min 37 s: build 1 min 37 s, ctest 42 s, then the eight vcan scripts 2 min 11 s in sequence.
- `tools` 4 min 12 s: build 1 min 46 s, deploy tool tests 2 min 8 s.
- `configurator-page` 3 min 37 s: Chromium 32 s, page and layout tests 2 min 57 s.

Of each build, about 27 s is installing `linux-modules-extra` (the vcan module), which only the vcan tests need. The first run in the new repository also built Lely (the cache was empty); later runs restore it.

The repository is public, so GitHub-hosted minutes are free and more parallel jobs cost nothing.

## What Changes

- `plugin` keeps the build and ctest; the vcan scripts move to a new `vcan` job run twice in parallel (matrix group 1: link setup, ping-pong, LSS, trace, bus state; group 2: slcan, RTD module, parameters, fixed PDOs), each on its own runner with its own `vcan0`.
- The deploy tool tests (`tools`) run as two shards and the configurator page and layout tests (`configurator-page`) as three, split by whole test class with `.github/scripts/test_shard.py` (largest class first onto the shard with the fewest tests, so every runner computes the same split). The small suites (release tag check, CI scripts, editor hook) run on one `tools` shard each.
- The shared build action takes `kernel-modules: "false"` to skip `linux-modules-extra` in jobs without vcan (`plugin`, `tools`, `stock`).
- Only what a merge needs stays in the pull request run. The stock runtime install (against upstream `development`) and the Docker route (against the published image) move to a new `integration.yml`: weekly, "Run workflow", and pull requests that touch the install routes. They mostly catch upstream drift, which a weekly run finds without slowing every pull request. The Docker job's fast stub-`docker` unit tests stay in CI (on a `tools` shard).
- The PC tools workflow (Windows, macOS) stops running on pull requests; it runs on version bumps on `main` (the release waits for it), release tags and "Run workflow".
- The README gives the local commands for the integration tests (Linux development machine) and the PC tools checks (Windows or Mac).
- Every CI job gets a time limit.
- A last job, `ci-ok`, passes only when every other job passed or was skipped, so a branch ruleset needs just that one check and job names can change freely.
- Same coverage: every test still runs once per change, `CANOPEN_REQUIRE_PARITY` and `CANOPEN_REQUIRE_BROWSER` stay where those tests run, and a shard with no tests fails instead of passing.
- Expected: a code change's run goes from about 4 min 50 s to about 3 min.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `canopen-ci`: the pull request suite without the two upstream install tests, which move to an integration workflow; the parallel test jobs requirement adds the vcan split, test sharding and the new wall time; a new requirement adds the single `ci-ok` check.
- `canopen-pc-install`: Windows and macOS tests on version bumps, tags and by hand, not on pull requests.

## Impact

- `.github/workflows/ci.yml`, new `.github/workflows/integration.yml`, `.github/workflows/pc-tools.yml`, `.github/actions/build-plugin/action.yml`, README.
- New `.github/scripts/test_shard.py` with tests in `test/ci/test_shard.py`.
- Check names change: `plugin` stays, `vcan (1/2)`, `vcan (2/2)`, `tools (1/2)`, `tools (2/2)`, `configurator-page (1/3)` … are new. A ruleset should require only `ci-ok`.
- No change to the plugin, the tools or their tests.
