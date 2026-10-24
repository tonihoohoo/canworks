## 1. Spikes (Mac, OpenPLC Editor, before the files are final)

- [ ] 1.1 Editor: `openplc-cli create`, add the canworks files with `--into-project`, add a hand-written `devices/servers/opcua.json`, open and save in the editor; check it keeps the entry, how a node of the `canworks` global list is addressed (`pouName`/`variablePath`), and that **Build** succeeds
- [ ] 1.2 Runtime v4.3.1 in Docker with the project uploaded: OPC UA endpoint answers on 4840, namespace index of `urn:openplc:opcua:namespace`, anonymous `operator` can write `limit` but not `temp1`, values follow the 20 ms task at a 100 ms cycle

## 2. Example files

- [ ] 2.1 `examples/openplc-fuxa/`: editor project skeleton from 1.1 (target Runtime v4, task `T#20ms`); `canworks/` with `canworks.json` (node-red-dashboard networks, OpenPLC connection, PLC link, `127.0.0.1:1502`, no mailboxes) and byte-identical `rtd8.eds`, `dio16.eds`, `simulation.json`; generated canworks-owned files and stamp
- [ ] 2.2 `PLANT_LOGIC` function block and `main` (HMI variables, conversions, `ack` cleared after use, `dio_out0`/`dio_out1` written)
- [ ] 2.3 `devices/servers/opcua.json`: endpoint, insecure anonymous profile with role `operator`, cycle 100 ms, nodes and permissions as designed
- [ ] 2.4 `docker-compose.yml` (setup, bridge, runtime, fuxa; ports on 127.0.0.1; caps; volumes) and `fuxa/start.sh` (server start, OPC UA driver install, one-time project load with marker)
- [ ] 2.5 `fuxa/project.json`: OPC UA device, tags, Plant and I/O views drawn in FUXA against the running example and exported
- [ ] 2.6 `README.md` for the example (Docker route, upload, FUXA, ports shared with the local runtime, route without Docker, OPC UA security note, editor version)

## 3. Check

- [ ] 3.1 `tools/deploy/tests/test_openplc_fuxa_example.py` (plant files and networks, config check, regenerated canworks-owned files, FUXA tags against OPC UA nodes and write rights, `main` variables, runtime pin, compose/start script references)
- [ ] 3.2 CI time: wall and summed job time against the main baseline, in the PR description

## 4. Local run

- [ ] 4.1 In the cloud container: FUXA 1.3.5 with `start.sh` against the bridge and an OPC UA stand-in (asyncua) serving the example's nodes; the driver installs, the project loads once, both views show values and writes land. The upstream runtime image cannot be pulled here, so the full chain is the hand checks

## 5. Docs and version

- [ ] 5.1 README.md (OpenPLC line and examples), `docs/modbus-bridge.md` OpenPLC section link, `docs/local-runtime.md` note on shared ports
- [ ] 5.2 Version bump: not needed (no tools code changes)

## 6. Hand checks (no Pi)

- [ ] 6.1 Mac (Colima with the docker-compose plugin): `docker compose up` on the released images, open and upload from the OpenPLC Editor, FUXA Plant and I/O views: values, trend, alarm and Ack (no clear while over the limit), limit change, running light loop back, manual outputs with the light off, restart keeps a FUXA edit
- [ ] 6.2 Windows with Docker Desktop: the same, with the editor on Windows
