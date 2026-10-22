## 1. PC-wide device list

- [ ] 1.1 `devices/store.py`: devices keyed by `host[:port]` in `devices.json`, not by project folder; old per-project file content ignored (clean cut)
- [ ] 1.2 `devices/service.py`: connections, running jobs and job follow keyed by device only
- [ ] 1.3 Project tags derived per request: "Runtime of <project>" from the online settings' runtime hosts of Recent projects, "Bridge of <instance>" from the last probe's bridge instances

## 2. Devices with no config

- [ ] 2.1 `server.py` `_devices`: works with no open session (target `None`, no instance, no saved config); bridge start actions keep needing a saved config; still refused in Commission a device
- [ ] 2.2 `devices/plan.py`: target `None` gives no needs column; role `openplc`/`bridge` from the request picks the main action for a device with neither plugin nor bridge; installed parts pick it otherwise; new action `install_bridge_only` (no `--instance/--config`)
- [ ] 2.3 After a job with no config: no runtime host change; bridge-only end text

## 3. Page

- [ ] 3.1 `index.html` / `app.js` start page: **Install on a device** link, fourth first-run choice "Set up a Linux device", purpose line
- [ ] 3.2 `shell.js`: Devices mode with no config (mode "Devices · no config", no workspace switch, Close to the start page)
- [ ] 3.3 `devices.js`: project tags in the list, own project's devices first and others muted, no needs column without a config, **What should this device run?** choice
- [ ] 3.4 `devices.js` wording: "Linux device", "SSH is on in the device."; no board brand

## 4. Tests

- [ ] 4.1 `tests/test_devices*.py`: shared list across projects and without a config; tags; plan with target `None` and both roles; bridge-only job args
- [ ] 4.2 `tests/test_configurator_devices_page.py`: run from the start page with no config (fake SSH device, role choice, install job), then the same device listed in a config
- [ ] 4.3 Start page tests: link and fourth first-run choice

## 5. Docs

- [ ] 5.1 `docs/devices.md`: start page entry, PC-wide list and tags, no-config role choice, wording
- [ ] 5.2 README (configurator / Devices lines), PC tools release notes, version bump

## 6. Hardware

- [ ] 6.1 From the start page with no config: add the bench Linux device, check it, see its project tag; run Update or Install (plugin) and see it end; open the OpenPLC project and see the same device listed first
