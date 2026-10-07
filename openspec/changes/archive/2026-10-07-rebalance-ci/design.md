# Design

## Context

Timings from the Actions API for the 105 completed CI runs between the merge of `shard-ci-tests` (2026-10-06) and 2026-10-07 18:00 UTC.

| Period | Normal wall time | Longest job |
|---|---|---|
| after `shard-ci-tests` | 2.9-3.4 min | vcan, about 1.1 min of tests |
| after the device simulator | 3.9-4.8 min | vcan (2/2), 2.1 min |
| after the slave role | 4.5-5.2 min | vcan (2/2), 2.6 min |
| after PC-direct commissioning | about 5 min | vcan (2/2), 3.1 min |
| after raw frames and bit rate detection | 5.6-6.7 min | vcan (2/2), 4.0 min |

Spikes (13 of 105 runs had one install step over 2.5 min): build action 321-527 s (normal 70-120 s), `tshark` 155-327 s (normal 6-10 s), Chromium 132-518 s (normal 21-35 s).

Other parts grew too but are not the longest job yet: the `tools` tests 133 to 310 s summed over three shards, the page tests 180 to 305 s, `plugin` ctest 44 to 68 s plus 26 s of CiA 402 ST tests.

## Decisions

### Three vcan runners, split by measured time

Test step times on `main` (2026-10-07 17:24 UTC run), and the proposed groups:

| Group | Tests | About |
|---|---|---|
| 1 | link setup, ping-pong, two networks, PLC-cycle SYNC, LSS, bus state, RTD module, parameters, fixed PDOs | 105 s |
| 2 | raw frames and bit rate, standalone device simulator | 115 s |
| 3 | bus trace, slcan adapter, master and its own slave, PLC SDO blocks, PC-direct commissioning | 125 s |

Each runner pays the build (about 70-120 s), so a third runner is cheaper than the 2.4 minutes it takes off the longest vcan job. Tests that need `vcan1` or `can-gw` set them up themselves as today, so any test can move between groups.

The groups stay written out per step (`matrix.group == N`), as now: a script-driven list would hide the test names from the Actions page. A comment above the vcan job holds the table of step times, and the README's CI section says to put a new vcan test on the lightest group and update the times. Considered: a balancer that reads times from earlier runs. Rejected for now: it needs the Actions API and a stored history, for nine minutes of vcan tests.

### Bounded, retried package installs

One helper, used by the build action, the `tshark` step and the page tests' system libraries:

- Skip packages that `dpkg -s` reports installed; with nothing missing, exit without `apt-get update`.
- `apt-get` with `-o Acquire::http::Timeout=20 -o Acquire::Retries=3`, each `apt-get` call under `timeout 120`, retried up to twice.
- The .deb files apt downloads are kept in a directory that `actions/cache` saves, keyed by runner image (`ImageOS`, `ImageVersion`), kernel and package set. A later job with the same key installs them with `dpkg -i` and never contacts the mirror; if that fails it falls back to apt.
- The step also gets `timeout-minutes`, so a hang that slips past both still ends the job in minutes rather than at the 20-minute job limit.

The stalls are on the mirror connection (no output, then everything unpacks in seconds), so a retry with a fresh connection is what helps; larger timeouts would not. The first run of this change confirmed it: one vcan job's install hit the limit, and the retry finished in 65 s. Retrying still costs the time limit, which is why the cache matters: a warm run skips the mirror entirely, and the image changes about weekly.

### `tshark` only where it is used

`test_bustrace` is a single test class, so it runs on one `tools` shard. The workflow installs `tshark` only on that shard (the shard is found with `test_shard.py --list`, so moving the class does not break it) and sets `CANOPEN_REQUIRE_TSHARK=1` there, so the decode test fails rather than skipping if the install is lost.

### Cached Chromium

`actions/cache` on `~/.cache/ms-playwright`, keyed by the Playwright version. `playwright install chromium` then finds the browser; `playwright install-deps chromium` goes through the bounded helper (it is skipped when the image already has the libraries).

### Build only the needed targets

The build action gets a `targets` input (default: all). `tools` sets `canopen_check`. `plugin` and `vcan` keep the full build.

## Risks

- A vcan test moved to another runner might depend on state an earlier test left (for example group 2 brings `vcan0` up itself because group 1's link test leaves it up). Each group keeps an explicit "bring vcan0 up" step, and every moved test is checked green in its new group.
- Caching Chromium can hide a broken download until the key changes. The key includes the Playwright version, which is what decides the browser build.
