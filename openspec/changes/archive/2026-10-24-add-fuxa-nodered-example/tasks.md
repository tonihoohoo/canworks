## 1. Example files

- [x] 1.1 `examples/fuxa-node-red/`: copy `canworks.json`, `rtd8.eds`, `dio16.eds`, `simulation.json` from `examples/node-red-dashboard`
- [x] 1.2 `plant.json`: canworks in → plant logic (copied) → canworks out, 500 ms tick, start inject with get-tag reads, **to FUXA tags** function (`global.get("fuxa")`, writes what the tag does not hold), get-tag-change for `limit`, `run`, `ack`, `manual_out0`, `manual_out1`, ack release, run and manual bytes → switch messages
- [x] 1.3 Tag ids = names, agreed with add-openplc-fuxa-example (2026-10-24: `manual_out0`, `bus_ok` added; `bridge_state` only here)
- [x] 1.4 `fuxa/project.json`: the FUXA Server device in `devices["0"]` and `server` (needed for name lookup in Node-RED and for writes from views), tags (ids = names, `polling` 200), views **Plant** and **I/O**, chart of both temperatures and the limit. No DAQ restore: it left tags empty on a first start
- [x] 1.5 `docker-compose.yml` (setup, bridge publishing 127.0.0.1:1881, fuxa 1.3.5 with `network_mode: service:bridge`, volumes for `_appdata` and `_db`) and `start.sh` (mysettings, offline package install on version change, flow once, project once)
- [x] 1.6 `README.md`: Docker route, URLs, port shared with the OpenPLC + FUXA example, restart behaviour, security; then installed bridge + own FUXA

## 2. Check

- [x] 2.1 `tools/deploy/tests/test_fuxa_nodered_example.py` (plant files, plant logic text, bridge id, topics, wires, tag ids in flow, views and chart, compose and start script references); timing entry in `.github/ci/tool-test-times.json`
- [x] 2.2 CI time: PR run wall 242 s, summed 1693 s; baseline median 287 s / 1743 s (in the PR description)

## 3. Local run

- [x] 3.1 In the cloud container: bridge built from main with the example config, FUXA 1.3.5 started through `start.sh` (first start: package install, flow, project load; second start: both kept; stop is immediate). From the browser (Playwright): limit 15 raised the alarm and output bit 0 came back on `dio_in0`, limit 30 + Ack cleared it, Ack while too hot kept it, the running light switched off, manual bit 3 of `dio_out1` came back on `dio_in1`, `manual_out0` bits 1-2 reached `dio_out0`. A project save reset the limit to 25 and refilled every Node-RED tag. Screenshot of the Plant view in `docs/images/fuxa-node-red-plant.png`

## 4. Docs and version

- [x] 4.1 README.md (Node-RED line) and `docs/node-red.md` ("FUXA example" section)
- [x] 4.2 Version bump: not needed (no tools code changes)

## 5. Hand checks (no Pi)

- [x] 5.1 Mac (Colima + compose plugin): `docker compose up` on the released image, both views work, flow editor opens at `/nodered/`. Passed 2026-10-24 on main 38398fd with canworks-bridge 0.137.2 and FUXA 1.3.5: HMI answered 4 s after `up` (images pulled before), package installed, flow and project loaded, no errors; live tags; limit 15 → alarm and `dio_in0` bit 0, Ack while too hot kept it, limit 30 + Ack cleared it, running light off + `manual_out1` 8 → `dio_in1` 8, light walks again; both views in a browser; `down -v` removed only this example
- [x] 5.2 Windows with Docker Desktop: the same. Passed 2026-10-24 (Windows 11, Docker 29.8.2, same images): pull 64 s, HMI 12 s after `up`, every item as 5.1, no errors. A copy made with `git archive` from a clone with `core.autocrlf=true` had CRLF in `start.sh`; `.gitattributes` now keeps `*.sh` LF on every checkout
