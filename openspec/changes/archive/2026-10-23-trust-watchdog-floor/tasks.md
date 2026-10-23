## 1. Export check

- [x] 1.1 `plcopen_targets.check` for `trust`: refuse when `0 < watchdog_ms < 500` (the effective value from `bridgecheck.link_settings`, so the OpenPLC default of 50 ms counts), with the fix `"watchdog_ms": 500` or more
- [x] 1.2 Tests: the OpenPLC default (50 ms) and 499 ms are refused; 500 ms, 1000 ms (the PLC link default) and 0 pass; CODESYS and generic exports are not affected; the configurator's PLCopen export shows the refusal in Problems

## 2. Docs and release

- [x] 2.1 docs/plcopen.md truST section: scan time with the library (about 100–125 ms on a Pi 5) and the 500 ms floor; README unchanged
- [x] 2.2 Tools patch version bump
- [ ] 2.3 State CI wall time and summed job time against the baseline in the PR

## 3. Hardware

- [x] 3.1 On the Linux device with node 23: a config with `watchdog_ms` 500 run with truST for 60 s gives no watchdog off/on lines in the bridge log while truST runs, and outputs off once when it stops (2026-10-23: 60 s with truST 0.24.75 and node 23: one outputs-on at the first write, no watchdog off while truST ran (472 with 50 ms), one off when it stopped; about 123 ms per scan; SDO and string reads 170 each)
