# CANopen on a stock OpenPLC Runtime v4

The plugin is installed next to an unmodified runtime, native or [Docker](#docker-installs), and either [`canworks-deploy`](deploy.md) or, with the [editor hook](#the-editors-build-and-upload), the editor's own **Build and upload** switches it on with each program upload.

This page covers native installs (`./install.sh --native`) first; for upstream's managed Docker install see [Docker installs](#docker-installs).

## Install (on the device)

```sh
git clone https://github.com/tonihoohoo/canworks
cd canworks
sudo scripts/install-stock.sh                       # runtime found from the openplc-runtime service
sudo scripts/install-stock.sh --runtime-dir /path/to/openplc-runtime   # or name it
sudo systemctl restart openplc-runtime              # once, so the runtime loads the plugin
```

The script:

- installs build dependencies (apt; `--no-deps` skips this), and builds Lely CANopen and `dcfgen` into `/opt/canworks` (`--prefix` changes it), at the Lely commit the deploy tool's copy of Lely's `dcf` package comes from (`--lely-ref` changes it);
- installs the deploy tool into `/opt/canworks/venv`: the plugin runs its EDS lint at every load ([config.md](config.md#eds-lint));
- builds `libcanworks_plugin.so` against the runtime checkout's headers and installs it to `/opt/canworks/lib/`, outside the runtime's `build/` tree, so rebuilding or reinstalling the runtime does not delete it;
- builds the standalone device simulator `canworks-sim` ([simulator.md](simulator.md)) from the same sources, installs it to `/opt/canworks/lib/` and links it as `/usr/local/bin/canworks-sim`; `canworks-sim --version` prints the plugin's version;
- adds one disabled line to the runtime's `plugins.conf`:

  ```
  canworks,/opt/canworks/lib/libcanworks_plugin.so,0,1,/opt/canworks/lib/canworks.json,
  ```

- loads the kernel module `can-j1939` for [J1939 networks](j1939.md) and lists it in `/etc/modules-load.d/canworks-j1939.conf` so it loads at every boot (in Docker mode on the host); a kernel without it only gets a warning, and CANopen works as before;
- installs the [editor hook](#the-editors-build-and-upload): the hook's checks go into `/opt/canworks/venv` next to the deploy tool, the hook to `/opt/canworks/lib/python/`, and one file, `canworks_hook.pth`, into the runtime's Python environment (`venvs/runtime`). `--no-editor-hook` leaves it out (and removes it if it was installed);
- advertises the device on the local network (`/etc/avahi/services/canworks.service`, `_canworks._tcp`) so the configurator lists it by name; `--without-discovery` leaves it out;
- with `--with-link`, installs the [remote link](remote-access.md) (`scripts/install-link.sh`): `canworks-link.service`, `/usr/local/bin/canworks-link`, a venv in `/opt/canworks-link` and `/etc/canworks-link/`. It reads the deployed config from `/opt/canworks/lib/canworks.json`, also in Docker mode, and stays off the internet until the config turns it on.

Both protocols are built by default. `--without-j1939` builds CANopen only (no kernel module). `--without-canopen` builds J1939 only: no Lely, `dcfgen`, deploy tool venv lint or `canworks-sim`; the venv then only holds the editor hook. A config with a network of a protocol that is not built in is refused at load.

It changes no file the runtime's git checkout tracks (`plugins.conf` is the runtime's own untracked, runtime-managed file). Running it again rebuilds the plugin and still leaves exactly one `canworks` line. It records the runtime commit it built against in `/opt/canworks/lib/runtime-commit` and warns when the runtime has changed since: the plugin interface is not versioned, so re-run the script after updating the runtime. When the runtime runs in Docker it installs in [Docker mode](#docker-installs) instead.

The line survives runtime updates as long as `plugins.conf` is kept: the runtime only recreates it from `plugins_default.conf` when it is missing.

## Docker installs

Upstream's recommended install (`curl -fsSL https://runtime.getedge.me | sudo bash`) runs the runtime in a container that a second container, the bootloader, starts and can move to another runtime version from the editor. The same script detects it (by the bootloader's `/var/lib/openplc-bootloader/runtime-spec.json`) and installs in Docker mode:

```sh
git clone https://github.com/tonihoohoo/canworks
cd canworks
sudo scripts/install-stock.sh
```

It:

- builds Lely CANopen, `dcfgen`, the deploy tool, the plugin and the editor hook **inside the runtime image the bootloader runs**, in a throwaway container, into `/opt/canworks` on the host. A plugin built on the host would not load in the image (the image is Debian bookworm with its own C library and Python). On a Raspberry Pi this takes a while;
- records the runtime version it built for in `/opt/canworks/lib/runtime-version`;
- builds `canworks-sim` for the image too, to `/opt/canworks/lib/canworks-sim`, with no host link: it needs the image's libraries, so run it inside the container (`docker exec -it openplc-runtime /opt/canworks/lib/canworks-sim ...`);
- adds two entries to the bootloader's runtime spec, through the same `extraBinds`/`extraEnv` keys upstream's installer writes for `--mount`/`--env`, and leaves every other entry as it was:
  - `extraBinds`: `/opt/canworks:/opt/canworks`
  - `extraEnv`: `PYTHONPATH=/opt/canworks/lib/sitecustomize` (loads the editor hook in the runtime's webserver)
- recreates the runtime container (`docker rm -f openplc-runtime`, `docker restart openplc-bootloader`) so the bootloader applies them. **The PLC stops, and the new container has no program**: it comes back with the PLC empty until you upload the program again (the deploy tool starts the PLC after the upload).

Then upload as on a native install (the runtime's certificate is new with each new container, so a pinned `--fingerprint` changes too): `canworks-deploy`, or the editor's **Build and upload** with a `canworks/` folder in the project. The CAN side needs nothing Docker-specific: upstream runs the runtime container privileged, on the host network, with `/dev` mounted, so `can0`, an slcan adapter's serial device, the plugin's link setup and the diagnostics port 7531 work as on a native install.

What differs from a native install:

- **Restarts keep everything.** A reboot or `docker restart openplc-runtime` keeps the container, so the program, `plugins.conf` and CANopen come back as they were.
- **New runtime containers lose the program.** The compiled program and `plugins.conf` live inside the container, so a new one (this script, a version change or a repair) starts with the PLC empty and `plugins.conf` from the runtime's defaults. The editor hook records the `canworks` line after each upload in `/opt/canworks/lib/plugins-line` and puts it back when the webserver starts (before the first upload it adds the line disabled), but the program itself has to be uploaded again. Each new container also makes a new self-signed certificate.
- **Runtime version changes.** The plugin interface is not versioned, so after the editor or the bootloader moves the device to another runtime version CANopen stays **off** and the PLC runs without it. The runtime log says so:

  ```
  [canworks editor hook] ERROR: the CANopen plugin was built for runtime v4.2.4 but the runtime is v4.2.5; re-run scripts/install-stock.sh to rebuild it; CANopen stays off
  ```

  Run `sudo scripts/install-stock.sh` again (it rebuilds in the new image), then upload the program again. The plugin makes the same check when it starts, in case the hook did not run. An upload to the mismatched runtime fails in `canworks-deploy` with the same message.
- `--no-editor-hook` is not available: the hook is what keeps the `canworks` line across containers.

`sudo scripts/install-stock.sh --uninstall` removes the two spec entries, recreates the runtime container and removes `/opt/canworks/lib/` (`--purge`: all of `/opt/canworks`).

### A runtime container you run yourself

Without the bootloader (a `docker run` or compose file as in upstream's `docs/DOCKER.md`), build for your image and add the printed flags to the container:

```sh
sudo scripts/install-stock.sh --docker-image ghcr.io/autonomy-logic/openplc-runtime:v4.2.4
# ==> ... -v /opt/canworks:/opt/canworks -e PYTHONPATH=/opt/canworks/lib/sitecustomize
```

The container also needs upstream's `--privileged --network host -v /dev:/dev` for CAN access. Run the script again whenever you change the image. Without a bootloader spec the plain `sudo scripts/install-stock.sh` refuses (it finds the `openplc-runtime` container) and prints this command.

## How uploads switch it

On every program upload the runtime extracts the zip to `core/generated/` and looks at `core/generated/conf/*.json`:

- an upload made with `canworks-deploy` carries `conf/canworks.json`: the runtime enables `canworks` and copies the config to `/opt/canworks/lib/canworks.json`. The plugin finds the EDS files the upload carried under `core/generated/conf/canworks/eds/` and logs the path it used;
- an upload without it makes the runtime disable `canworks`, unless the [editor hook](#the-editors-build-and-upload) finds a config in the project. The PLC then runs without CANopen, and the runtime log says the plugin was disabled because no config was found.

CI runs the upstream runtime's own upload code (`analyze_zip`, `safe_extract`, `update_plugin_configurations` from `development`) on a deployed bundle and on a plain one to check both cases (`test/stock/run.sh`).

The CAN interface is configured from the config's `adapter` (bit rate, link up): see [config.md](config.md#adapter).

## The editor's Build and upload

The editor (4.3 and later) sends the whole project folder with every **Build and upload** as a project snapshot. With the editor hook installed, a project can carry its CANopen config in a `canworks/` folder and the editor's own upload keeps CANopen on. Put a config into a project once (on the PC with the editor):

```sh
canworks-deploy --config config/rtd-sensor/canopen_config.json --into-project ~/Documents/workspace/rtd-monitor
```

This runs the deploy tool's checks and writes `canworks/canworks.json` and the EDS files to the project (`--force` replaces an existing `canworks/`). EDS files are stored as UTF-8, because the editor sends project files as UTF-8 text; one in CP1252/Latin-1 is converted. Then press **Build and upload** in the editor as usual. After a successful build, before the runtime reports success, the hook copies the config to `core/generated/conf/` and the runtime enables `canworks` by its own rules. The build log says `CANopen: config taken from the project snapshot (canworks/canworks.json, 1 EDS file)`. A [simulation file](simulator.md#the-simulation-file) `canworks/simulation.json` travels too, with its extra devices' EDS files and its CSV files, checked against the config and written in the deploy tool's layout; a bad one rejects the whole config like any other check, and the build log warns when the config simulates devices.

- A project without `canworks/` switches CANopen off, as without the hook.
- An upload made with `canworks-deploy` wins: its `conf/canworks.json` is used and the project's is ignored. The runtime then drops the project snapshot it kept from the editor's last upload, so the editor cannot read the project back from the device until its next **Build and upload**.
- A config in the project that fails a check (bad JSON, schema, a missing or non-UTF-8 EDS, a path outside `canworks/`) is ignored with a warning in the build log naming the file and the problem, and CANopen is switched off. The build itself still succeeds.
- If a runtime update changes what the hook relies on, the runtime log shows one `[canworks editor hook] ERROR: inactive, ...` line at start and uploads behave as without the hook. When it works, the log shows `[canworks editor hook] INFO: active: ...` (`journalctl -u openplc-runtime | grep 'editor hook'`).
- Reinstalling the runtime recreates `venvs/runtime` without the hook: re-run `install-stock.sh` afterwards, as for the `plugins.conf` line.

CI runs the hook against the upstream runtime's own `update_plugin_configurations` and `run_compile` with a stub compiler, for editor uploads with and without `canworks/`, deploy-tool uploads, uploads without a snapshot and failed builds (`test/stock/editor_hook.py`).

## Uninstall

```sh
sudo scripts/install-stock.sh --uninstall           # removes the canworks line, the editor hook, the simulator link, the modules-load.d entry, /opt/canworks/lib, the advertisement and the remote link
sudo scripts/install-stock.sh --uninstall --purge   # also removes Lely and dcfgen (all of /opt/canworks) and the link's key and paired PCs
sudo systemctl restart openplc-runtime
```

Nothing else in the runtime changes.
