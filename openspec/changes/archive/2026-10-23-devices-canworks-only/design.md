## Context

The Devices workspace (`device-install`, PR #192) was built while canworks still had an OpenPLC plugin. It treated the OpenPLC Runtime as one of the device's parts: it probed for the runtime, installed it with upstream's installer (`install-bridge.sh --with-openplc`), switched it back to the pinned version (`--pinned-runtime`) and created its first user. The plugin was removed (#241), and OpenPLC is now one of the bridge's Modbus connections (#264). Nothing of canworks lives in the runtime any more, so the Devices page manages something canworks doesn't own.

The device list's tags came from two sources. **Runtime of X** came from the Online access host of every project folder in this PC's online settings. **Bridge of X** came from every folder under `/etc/canworks-bridge/` with a `canworks.json`. On the bench this lists 14 entries for one device. Ten of them are backup folders made by hand during hardware tests.

## Goals / Non-Goals

**Goals:**
- Devices shows and acts on canworks parts only: the bridge, its remote link, local network discovery, and the CAN interfaces the bridge uses.
- The device card says in one line what runs there.
- The probe never mistakes a backup folder for a bridge instance.

**Non-Goals:**
- Showing or installing Node-RED, an HMI or any other client program.
- Detecting the OpenPLC Runtime to warn about it. The bridge doesn't depend on it, and the Modbus connection's own checks cover the PLC side.
- Cleaning up folders on devices. The probe ignores them, and deleting is the user's job.
- Changing the local simulated runtime, which still uses the pinned runtime image.

## Decisions

**1. Drop the runtime from the probe instead of hiding the row.** The probe's runtime section takes about 50 lines. It reads Docker and the bootloader folder through `sudo -n`, and it is the only reason the probe runs `docker` at all. Keeping it only to hide the result would leave a read-only probe that still touches Docker. The `runtime` key leaves the JSON. A last probe of the old shape stored in `devices.json` still has the key, and the plan ignores it. *Alternative:* keep a read-only "OpenPLC Runtime: found" line for context. This was rejected because Toni wants only canworks parts.

**2. Instance names by the installer's rule.** The probe accepts a folder as an instance only when its name matches `^[A-Za-z0-9_-]+$`, the same rule `install-bridge.sh --instance` enforces, and the folder holds `canworks.json`. Everything `install_instance` can create passes the rule, and every `cp -a x x.bak-…` copy fails it. *Alternative:* list only folders with an enabled or active `canworks-bridge@` unit. This was rejected because a stopped, disabled instance (after **Stop**) would vanish from the page, and **Start this project's bridge** decides on exactly that state.

**3. One summary line on the card, computed in `service.view`.** `tags` becomes `summary`, a short string:
- `This project's bridge` when the open project's instance is on the device;
- otherwise the running instances joined by `, ` with `running`, and then `N stopped` when other instances exist (`line1 running · 1 stopped`);
- `N bridges stopped` when none runs;
- empty without the bridge.

The card's status line ("Up to date", the main action's label) stays as it is. `Runtime of …` goes: Online access hosts are a project setting and not what is on the device. `_device_projects` still returns the open project's own host, which is only used to list the project's devices first.

**4. One action set for every bridge project.** With the runtime gone, the OpenPLC project and the bridge project differ only in their connection, which the device doesn't see. So `plan()` treats `openplc_modbus` like `bridge`:
- **Install and start this project's bridge** when there is no bridge;
- **Update A → X** when the bridge is older;
- **Start this project's bridge** when the project's config isn't running.

With no config open, a device without the bridge gets **Install the bridge X**, with a one-line hint that a config's own Devices page starts it with that config. `roles`, `install_openplc_bridge` and `switch_runtime` are removed from the plan, the jobs and the page.

**5. Script options removed, not deprecated.** Nothing is in real use, so `--with-openplc` and `--pinned-runtime` go as a clean cut. An old command line fails with the script's usual "unknown option" message. The runtime install code goes with them: `have_runtime`, upstream's installer call, the 10-minute wait, the runtime image switch and the `runtime-install-failed` exit hint.

**6. The pin stays, in its last user.** `TESTED_RUNTIME` and `PINNED_BOOTLOADER` move to `localruntime.py`. The canopen-ci "One runtime pin" test reads them from there. `DOCKER_STOP` and `OPENPLC_INSTALLER` go.

## Risks / Trade-offs

- [A user expects canworks to set up OpenPLC on a fresh device] → `docs/devices.md` and `docs/modbus-bridge.md` link to upstream's installer in one line, and the OpenPLC connection's docs say the runtime comes from upstream.
- [An instance named outside the rule by hand, such as `line.1`, disappears from the page] → no supported path creates one, and the installer refuses such names.
- [Backup folders stay on disk] → not shown any more. Deleting them is the user's job.
