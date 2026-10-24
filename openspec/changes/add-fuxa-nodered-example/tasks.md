## 1. Example files

- [ ] 1.1 `examples/fuxa-node-red/`: copy `canworks.json`, `rtd8.eds`, `dio16.eds`, `simulation.json` from `examples/node-red-dashboard`
- [ ] 1.2 `plant.json`: canworks in → plant logic (copied) → canworks out, 500 ms tick, start inject with get-tag reads, **to FUXA** function (`global.get("fuxa").setTag`), get-tag-change for `limit`, `run`, `ack`, `manual_out1`, ack release, `manual_out1` → switch messages
- [ ] 1.3 Tag ids: check add-openplc-fuxa-example's tag ids at apply time and use the same ones
- [ ] 1.4 `fuxa/project.json`: no devices, Server tags (ids = names, `limit`/`run`/`manual_out1` with DAQ restore, `polling` 200), views **Plant** and **I/O** drawn in FUXA's editor and exported (or reused from add-openplc-fuxa-example when it already has them)
- [ ] 1.5 `docker-compose.yml` (setup, bridge publishing 127.0.0.1:1881, fuxa 1.3.5 with `network_mode: service:bridge`) and `start.sh` (mysettings, offline package install on version change, flow once, project once)
- [ ] 1.6 `README.md`: Docker route, URLs, port shared with the OpenPLC + FUXA example, restart behaviour, security; then installed bridge + own FUXA

## 2. Check

- [ ] 2.1 `tools/deploy/tests/test_fuxa_nodered_example.py` (plant files, plant logic text, bridge id, topics, tag ids in flow and views, compose and start script references)
- [ ] 2.2 CI time: wall and summed job time against the main baseline, in the PR description

## 3. Local run

- [ ] 3.1 In the cloud container: bridge built from the branch with the example config, FUXA 1.3.5 started through `start.sh`; values reach the tags, limit/Ack/running light/manual outputs work, project save keeps the limit; screenshots of both views with Playwright for the PR

## 4. Docs and version

- [ ] 4.1 README.md (examples) and `docs/node-red.md` (a "FUXA example" section)
- [ ] 4.2 Version bump: not needed (no tools code changes)

## 5. Hand checks (no Pi)

- [ ] 5.1 Mac (Colima + compose plugin): `docker compose up` on the released image, both views work, flow editor opens at `/nodered/`
- [ ] 5.2 Windows with Docker Desktop: the same
