## 1. Spike on the bench (gate)

- [ ] 1.1 Plugin spike build: give `libcanopen_plugin.so` the SONAME and export a minimal `canopen_plc_api` that answers a version probe and one blocking-free 0x1018 subindex 1 read through a slot
- [ ] 1.2 Editor library spike: a library project with one C++ block that finds the plugin with `dlopen("libcanopen_plugin.so", RTLD_NOW | RTLD_NOLOAD)` and reads 0x1018 subindex 1 with the EXECUTE/BUSY/DONE handshake; build the `.stlib` in OpenPLC Editor 4.3.2, install it, use it in a project
- [ ] 1.3 Run it on the Pi runtime (native and Docker) against a real node; also check a `STRING` output and an `ARRAY[0..1023] OF BYTE` in-out pin, the pin-name `#define`s next to the shared header, and whether the `.stlib` can be built headless
- [ ] 1.4 Record the result in design.md; if the plugin cannot be reached, stop and propose the located-variable mailbox instead

## 2. Plugin API

- [ ] 2.1 `plugin/src/plc_api.h/.cpp`: v1 table, request/result structs, 64 slots with 1024-byte buffers, generation handles, mutex, wake eventfd
- [ ] 2.2 Export `canopen_plc_api(version)`, log once on an unknown version, SONAME in `plugin/CMakeLists.txt`
- [ ] 2.3 `Network`: program queue per node, availability rules, turns with SDO variables, unconfigured node IDs via the default Client-SDO, size 0 from the EDS by data kind
- [ ] 2.4 Results: decode errors to ERROR_ID, abort code, reply size; 10 s collection limit; cancel on `stop_loop` and run generation bump
- [ ] 2.5 Logging: aborts deduplicated per node, object and code; warning once per run for objects the plugin configures
- [ ] 2.6 Unit tests for slots, handles, generations, limits and size resolution

## 3. Library

- [ ] 3.1 `library/openplc_canopen/`: `library.json`, shared header, the eight blocks
- [ ] 3.2 Build the `.stlib` (CI or committed with a source check, per the spike)
- [ ] 3.3 Host test: compile the block sources the way the editor does, load them into a process that loaded the plugin `RTLD_LOCAL`, run against a Lely slave on vcan: integer read/write, signed values, REAL32/REAL64, string, bytes, size from EDS, abort, timeout, unconfigured node, node lost, two blocks on one node, 65 at once, PLC stop during a transfer, version mismatch
- [ ] 3.4 Add the test to the vcan CI job

## 4. Tools

- [ ] 4.1 Deploy wheel carries the `.stlib`; `openplc-canopen-deploy library --out DIR`; release workflow attaches it
- [ ] 4.2 `--new-project ... --sdo-blocks` enables the library in `project.json`; message when the editor lacks it
- [ ] 4.3 Configurator: "Enable CANopen SDO blocks" in the New editor project dialog
- [ ] 4.4 Configurator: "Copy as ST call" in the object dictionary tab and the any-entry row
- [ ] 4.5 Tests for the subcommand, the project option and the configurator actions; bump the deploy package version

## 5. Docs

- [ ] 5.1 `docs/plc-sdo.md`: install the library once, one example per data kind, the handshake, error IDs, limits, relation to `sdo_variables`
- [ ] 5.2 README and `docs/configurator.md`, `docs/deploy.md` links

## 6. Hardware check

- [ ] 6.1 On the Pi with a real node: read 0x1008 as a string, write and read back a parameter with `SIZE := 0`, provoke an abort, unplug the node during a read, stop the PLC during a transfer
