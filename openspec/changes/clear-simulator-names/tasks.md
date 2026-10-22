## 1. Names in code and build

- [ ] 1.1 Rename the CMake target and binary `canworks-sim` to `canworks-canopen-sim` (`plugin/CMakeLists.txt`, `tools/sim/*` usage, help and log texts, `test/sim`, `test/simulator/run.sh`, `test/stock/run.sh`, `test/docker/run.sh`, `test/commissioning/run.sh`, `ci.yml` build targets)
- [ ] 1.2 `scripts/install-stock.sh`: install `canworks-canopen-sim` and its link; remove an old `canworks-sim` binary and a `/usr/local/bin/canworks-sim` link into this install, printing one line; same on uninstall
- [ ] 1.3 Rename the PC tools entry point `canworks-sim-runtime` to `canworks-local-runtime` (`pyproject.toml`, `localruntime.py` container and image names, messages), and update `tests/test_localruntime.py`
- [ ] 1.4 Image: `docker/local-runtime/Dockerfile` labels, `local-runtime.yml` tags, `release-deploy.yml` image `ghcr.io/<owner>/canworks-local-runtime`, `test/local-runtime/run.sh`, `test/virtual-example/run.sh`
- [ ] 1.5 Python clients that name the binary (`simcli.py`, `simclient.py`, `diag.py`, `simfile.py`, `configurator/simulation.py`) and their tests and fakes (`fake_sim.py`, `fake_sim_page.py`, `test_configurator_sim.py`, `test_contract.py`)
- [ ] 1.6 Plugin texts that name the binary (`sim_engine.h`, `sim_config.h`)

## 2. Name check

- [ ] 2.1 `scripts/rename_to_canworks.py`: map `openplc-canopen-sim-runtime` to `canworks-local-runtime`; add the retired-name list (`canworks-sim-runtime`, bare `canworks-sim` but not `canworks-sim.v1`/`.v2`) to `--check`, skipping archived changes
- [ ] 2.2 `test/ci/test_rename.py`: cases for the new mapping, an old command in a doc (reported) and a schema link (not reported)

## 3. Configurator

- [ ] 3.1 Connect panel target and connection bar: "Standalone simulator" becomes "CANopen simulator" (`connection.js`, `sim.js`, labels, recent-connection text, page tests)
- [ ] 3.2 Simulation tab on a J1939 network: keep the tab and show the one-line note with the copyable `canworks-j1939-sim --dbc <dbc> --node NAME --interface IF` and a doc link (`shell.js`, `app.js`, `sim.js`); keep Simulated device and Simulation file hidden; page test

## 4. Docs

- [ ] 4.1 `docs/simulator.md`: title "Simulation", overview table (what, tool or setting, protocols, runs on, doc), "Why two simulators" paragraph, existing content under "CANopen and plain CAN devices", `canworks-canopen-sim` section
- [ ] 4.2 README: command table rows for `canworks-local-runtime`, `canworks-canopen-sim` and `canworks-j1939-sim` with protocols; Simulation section links the overview; drop the separate runtime-host simulator sentence
- [ ] 4.3 Replace the old names and the "standalone simulator" / "simulator runtime" wording in local-runtime.md, j1939.md, install-stock.md, install-pc.md, configurator.md (incl. J1939 Simulation note), diagnostics.md, development.md, tour.md, raw-can.md, codesys.md, deploy.md, SECURITY.md, tools/deploy/README.md
- [ ] 4.4 Release notes entry in `tools/deploy/release-notes.md`; tools version 0.108.0 and plugin version bump

## 5. Checks

- [ ] 5.1 `rename_to_canworks.py --check`, the PC tools tests, page tests and the plugin build pass locally; CI green
- [ ] 5.2 Local runtime workflow builds `canworks-local-runtime:ci` and runs the virtual example in it

## 6. Bench (needs the Pi and a PC)

- [ ] 6.1 Pi: install the plugin from the branch; `canworks-canopen-sim --version` matches the plugin, `/usr/local/bin/canworks-sim` is gone, and a clean PLC start works
- [ ] 6.2 Mac or Windows: `canworks-local-runtime start` runs a container named `canworks-local-runtime`; remove any old `canworks-sim-runtime` container by hand
- [ ] 6.3 Update the project's Windows real-devices guide (outside the repo) to the new names
