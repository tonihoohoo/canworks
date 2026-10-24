## 1. Example files

- [x] 1.1 `examples/node-red-dashboard/`: copy `rtd8.eds`, `dio16.eds`, `simulation.json` from `examples/modbus-bridge`; `canworks.json` with the same networks, PDO entry names (`temp1`, `temp2`, `in0`, `in1`, `out0`, `out1`), bridge on `127.0.0.1:1502`, writers `127.0.0.1`, status/control blocks, SDO registers with writes, mailboxes
- [x] 1.2 `dashboard.json`: Dashboard 2.0 config nodes, Plant / I/O / Service pages, canworks in/out, nmt, sdo, emcy nodes on the `plant` export's bridge id; plant logic function node (PLANT_LOGIC behaviour) with the 500 ms tick
- [x] 1.3 `docker-compose.yml` (setup, bridge, node-red with `network_mode: service:bridge`, `CANWORKS_VERSION`) and `start.sh` (package install on version change, pinned `@flowfuse/node-red-dashboard`, flows file join on first start)
- [x] 1.4 `README.md` for the example: Docker route first, then installed bridge + local Node-RED

## 2. Check

- [x] 2.1 `tools/deploy/tests/test_nodered_example.py` (plant files identical, config check, bridge id, topics read/written, compose and start script references)
- [x] 2.2 CI time: wall and summed job time against the main baseline, in the PR description

## 3. Local run

- [x] 3.1 In the cloud container: bridge built from the branch with the example config, Node-RED 4.1 with the package and Dashboard 2.0, joined flow loaded; values arrive, switches loop back, alarm and Ack, device name, NMT; screenshots of the three pages with Playwright for the PR. Also `docker compose up` with a bridge image built locally from the branch (host network for the bridge, because the cloud container has no outside DNS for containers)

## 4. Docs and version

- [x] 4.1 README.md (Node-RED line and examples), `docs/node-red.md` "Dashboard example" section
- [x] 4.2 Version bump: not needed (no tools code changes; the example runs on the current release image)

## 5. Hand checks (no Pi)

- [x] 5.1 Mac with Docker Desktop: `docker compose up` on the released image, dashboard opens, the three pages work. Passed 2026-10-24 on the Mac with Colima plus the docker-compose plugin (no Docker Desktop there; Compose 5.6.1), tools 0.133.2: first start 63 s with image pulls, values, trend, alarm and Ack (no clear while over the limit), running light loop back, manual output with the light off, device name RTD-8, NMT stop and start; no log errors
- [x] 5.2 Windows with Docker Desktop: the same. Passed 2026-10-24 (Docker 29.8.2, Compose 5.5.1, tools 0.133.2): first start 109 s with image pulls (Node-RED container 26 s), every item as 5.1, no log errors
