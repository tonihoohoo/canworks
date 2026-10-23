# Local runtime: `canworks-local-runtime`

The OpenPLC Editor's own **OpenPLC Simulator** emulates a small microcontroller board and runs only the PLC program, with no Modbus master to reach canworks. The local runtime takes its place on the engineering PC: upstream's OpenPLC Runtime v4 at the pinned version, unchanged, and canworks-bridge next to it, in two containers on Windows, macOS or Linux, with every network running simulated. An [OpenPLC project](modbus-bridge.md#openplc) with CANopen nodes then runs on the PC with no Linux device, no CAN adapter and no devices: upload it from the editor, watch it in the editor's debugger, and use the configurator's online, trace and simulation views against it.

`canworks-local-runtime` comes with the PC tools ([install-pc.md](install-pc.md)). It needs a container engine; Docker Desktop is not needed.

## Container engine (once per PC)

The images are published for amd64 and arm64, so it runs natively on Intel and AMD PCs and on M-series Macs.

**Windows 10 22H2 or Windows 11:** a Linux distribution in WSL2 with Docker Engine or Podman inside it. The tools and the editor stay on Windows; `canworks-local-runtime` finds the engine through `wsl` by itself.

```powershell
wsl --install -d Ubuntu          # once; restart if asked, then open Ubuntu and create its user
```

In the Ubuntu window, either Docker Engine:

```sh
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER    # then close the window and run `wsl --shutdown` in PowerShell
```

or Podman: `sudo apt install podman`. Ports published inside WSL2 are reachable as `localhost` from Windows.

**macOS (M-series or Intel):** Colima with the Docker command line, from [Homebrew](https://brew.sh):

```sh
brew install colima docker
colima start                     # after every restart of the Mac, or: brew services start colima
```

Podman works too: `brew install podman`, `podman machine init`, `podman machine start`.

**Linux:** Docker Engine (`curl -fsSL https://get.docker.com | sudo sh`, then add yourself to the `docker` group) or Podman, rootless included.

`canworks-local-runtime` tries `docker`, then `podman`, and on Windows `docker` and `podman` inside the default WSL distribution. `--engine docker|podman|wsl-docker|wsl-podman` (or `CANWORKS_ENGINE`) picks one.

## Start

```sh
canworks-local-runtime start
```

The first start downloads upstream's runtime image at the pinned version and the bridge image matching the tools' version (several hundred MB), creates the container `canworks-local-runtime` with its data volume and the container `canworks-local-bridge` in its network (so the runtime's Modbus master reaches the bridge at `127.0.0.1:1502`) with a volume for its config, creates a runtime user `openplc` with a random password, and saves the address, user, password and the runtime's certificate fingerprint in `local-runtime.json` in the tools' settings folder (`%APPDATA%\canworks`, `~/Library/Application Support/canworks`, `~/.config/canworks`), readable only by you. It prints how to connect:

```
Connect the OpenPLC Editor to it: target OpenPLC Runtime v4, address localhost:8443, user openplc, password from `canworks-local-runtime status --show-password`.
Put the project's config on its bridge:   canworks-deploy --config canworks/canworks.json --bridge local
Diagnostics:   canworks-diag --runtime local status   (configurator: host "local")
Every network runs simulated here: no CAN interface is used.
```

The password is printed only by `canworks-local-runtime status --show-password`.

The saved certificate fingerprint changes only when `start` or `update` has just created the container itself. At any other time, a runtime that answers on the port with another certificate is refused before the password is sent: `start` and `status` stop and say the certificate changed. Another program may be holding the port; when you recreated the container yourself, `canworks-local-runtime remove` and `start` pin the new certificate (the data volume, user and password stay).

The container restarts with the engine (unless stopped) and listens only on this PC (`127.0.0.1`): the runtime on port 8443 and the bridge's diagnostics on port 7531. `--port` and `--diag-port` choose others; the diagnostics port is published as the same number inside the container, so a config for `--diag-port 7532` sets `master.diagnostics.port` (in a version 2 file, the top-level `diagnostics.port`) to 7532.

## Use it

[tour.md](tour.md) takes you through [`examples/virtual-plant`](../examples/virtual-plant/README.md) on the local runtime step by step: every feature that does not need hardware, in one project.

- **Editor:** type the address `localhost:8443` with the printed user and the password from `status --show-password` (the device settings' search does not list the local runtime, since it scans the network rather than this PC; typing the address connects), then **Build and Upload** the project. Its remote device reads and writes the bridge, and the debugger shows the values of the simulated devices in the `canworks` variable list. Simulated values follow the project's simulation file ([simulator.md](simulator.md)).
- **The config:** `canworks-deploy --config canworks/canworks.json --bridge local` (or the configurator's **Devices** page) puts the config on the local bridge, which restarts on it. It skips the question about uploading a non-simulated config, since nothing real is driven here. The bridge log shows the networks start.
- **Diagnostics and configurator:** `canworks-diag --runtime local status`, and in the configurator's online access the **Local runtime** button (host `local`). The config needs `diagnostics` with a token as for any bridge ([diagnostics.md](diagnostics.md)); the default `bind` (`0.0.0.0`) and port (7531) fit the container.

Other commands:

```sh
canworks-local-runtime status [--show-password]   # containers, images and PLC state
canworks-local-runtime logs [--runtime] [-f]      # the bridge's log (--runtime: the runtime's)
canworks-local-runtime stop                       # start brings it back with the same program and config
canworks-local-runtime update                     # the images for the installed tools' version, same data
canworks-local-runtime remove [--data]            # delete the containers; --data also the volumes and saved credentials
```

`update` pulls the images that match the installed tools (after a tools update), replaces the containers and keeps the volumes, so the user, password, certificate and the bridge's config stay the same. The new runtime container has no program running: upload it again. `--image` runs another bridge image, for example one built from a checkout (below), and `--runtime-image` another runtime image.

## Limits

- Every network runs simulated, whatever `adapter.simulate` and the adapter settings say: the bridge container gets `CANWORKS_FORCE_SIMULATE=1`, and the bridge log, `canworks-diag status` and the configurator's online view say so. A real CAN adapter cannot be reached from a container on Windows or macOS anyway.
- J1939 networks do not run here: they need the Linux kernel's J1939 support, and the bridge refuses a J1939 network on the forced simulated bus. Run them on a Linux device, on a CAN or `vcan` interface, with `canworks-j1939-sim` playing the other ECUs ([j1939.md](j1939.md#simulator)).
- A simulated device behaves like a real one when it fails: a fault that stops its heartbeat (the ping-pong example's `device-hangs` scenario) makes the master report the node lost and boot it again, which resets the device's objects to their EDS defaults. A program that feeds a device's value back to it, like the ping-pong program, can then carry two counts at once (the value seems to jump between them) until the PLC is stopped and started.
- No real-time timing: the PLC cycle and the simulated bus run at the speed of a PC container, which is fine for logic and I/O but says nothing about jitter on the real target.
- On a Linux PC with a SocketCAN interface, install the bridge itself instead ([modbus-bridge.md](modbus-bridge.md#install)); `canworks-local-runtime` always simulates.

## Troubleshooting

- **"no container engine is running"**: start it (`colima start`, `podman machine start`, `sudo systemctl start docker`, or open the WSL distribution once). The message lists what was tried.
- **"port 8443 or 7531 is already in use"**: another runtime or program uses it; `canworks-local-runtime update --port 8444 --diag-port 7532` moves this one (then set the config's diagnostics `port` to 7532 as well).
- **Lost credentials** (`local-runtime.json` deleted, or another PC user): they cannot be recovered. `canworks-local-runtime remove --data` and `start` again create new ones; the uploaded program goes with the data.
- **`remove --data` cannot remove a volume**: it names the volume and the engine's reason, for example `volume is in use` when a container of an older install still holds it, and keeps the saved settings. Remove that container (`docker ps -a`) and run `remove --data` again.
- **Windows: localhost does not reach the runtime**: WSL2's localhost forwarding is off in `%USERPROFILE%\.wslconfig` (`localhostForwarding=false`); remove that line, or use `networkingMode=mirrored`, and run `wsl --shutdown`.
- **The engine refuses the extra capabilities** (some rootless setups): the runtime then starts without them, with a note; it works, with less precise PLC timing.
- **`mlockall failed: Cannot allocate memory`** in the runtime log at each PLC start: the runtime could not lock its memory. The container is started with an unlimited memlock limit, which rootless Podman cannot grant beyond the host user's own limit; the PLC runs normally, with less precise timing. A container made by tools before 0.31.1 has no such limit: `canworks-local-runtime update` recreates it.

## Building the image from a checkout

```sh
docker build -f docker/bridge/Dockerfile --build-arg TOOLS_VERSION=dev -t canworks-bridge:dev .
canworks-local-runtime update --image canworks-bridge:dev
```

`test/local-runtime/run.sh --image canworks-bridge:dev --strucpp <strucpp>` runs the end-to-end check CI runs: start, the ping-pong config as an OpenPLC config put on the bridge with `--bridge local`, a compiled PLC program uploaded with the editor's Modbus master config, the round trip through the bridge, diagnostics through the published port, stop, start, update and remove. Each tools release publishes `ghcr.io/tonihoohoo/canworks-bridge:<version>` and `:latest` for amd64 and arm64.
