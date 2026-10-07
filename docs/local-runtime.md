# Local simulator runtime: `openplc-canopen-sim-runtime`

The OpenPLC Editor's own **OpenPLC Simulator** emulates a small microcontroller board and runs only the PLC program: runtime plugins such as CANopen cannot run in it. The local simulator runtime takes its place on the engineering PC: the stock OpenPLC Runtime v4 with the CANopen plugin, in a container on Windows, macOS or Linux, with every CANopen network running simulated. A project with CANopen nodes then runs on the PC with no Raspberry Pi, no CAN adapter and no devices: upload it from the editor, watch it in the editor's debugger, and use the configurator's online, trace and simulation views against it.

`openplc-canopen-sim-runtime` comes with the PC tools ([install-pc.md](install-pc.md)). It needs a container engine; Docker Desktop is not needed.

## Container engine (once per PC)

The image is published for amd64 and arm64, so it runs natively on Intel and AMD PCs and on M-series Macs.

**Windows 10 22H2 or Windows 11:** a Linux distribution in WSL2 with Docker Engine or Podman inside it. The tools and the editor stay on Windows; `openplc-canopen-sim-runtime` finds the engine through `wsl` by itself.

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

`openplc-canopen-sim-runtime` tries `docker`, then `podman`, and on Windows `docker` and `podman` inside the default WSL distribution. `--engine docker|podman|wsl-docker|wsl-podman` (or `OPENPLC_CANOPEN_ENGINE`) picks one.

## Start

```sh
openplc-canopen-sim-runtime start
```

The first start downloads the image matching the tools' version (several hundred MB), creates the container `openplc-canopen-sim-runtime` with its data volume, creates a runtime user `openplc` with a random password, and saves the address, user, password and the runtime's certificate fingerprint in `local-runtime.json` in the tools' settings folder (`%APPDATA%\openplc-canopen`, `~/Library/Application Support/openplc-canopen`, `~/.config/openplc-canopen`), readable only by you. It prints how to connect:

```
Connect the OpenPLC Editor to it: target OpenPLC Runtime v4, address localhost:8443, user openplc, password ....
Deploy with:   openplc-canopen-deploy --runtime local ...
Diagnostics:   openplc-canopen-diag --runtime local status   (configurator: host "local")
Every CANopen network runs simulated here: no CAN interface is used.
```

The container restarts with the engine (unless stopped) and listens only on this PC (`127.0.0.1`): the runtime on port 8443 and the CANopen diagnostics on port 7531. `--port` and `--diag-port` choose others; the diagnostics port is published as the same number inside the container, so a config for `--diag-port 7532` sets `master.diagnostics.port` to 7532.

## Use it

- **Editor:** type the address `localhost:8443` with the printed user and password (the device settings' search does not list the local runtime, since it scans the network rather than this PC; typing the address connects), then **Build and Upload** a project with a `canopen/` folder ([install-stock.md](install-stock.md)). The runtime log shows the CANopen start, and the debugger shows the values of the simulated devices. Simulated values follow the project's simulation file ([simulator.md](simulator.md)).
- **Deploy tool:** `openplc-canopen-deploy --runtime local --config canopen/canopen.json --project .` reads the address, user, password and fingerprint from `local-runtime.json`; `--user`/`--password` still win. It skips the question about uploading a non-simulated config, since nothing real is driven here.
- **Diagnostics and configurator:** `openplc-canopen-diag --runtime local status`, and in the configurator's online access the **Local simulator runtime** button (host `local`). The project's config needs `master.diagnostics` with a token as for any runtime ([diagnostics.md](diagnostics.md)); the plugin's default `bind` (`0.0.0.0`) and port (7531) fit the container.

Other commands:

```sh
openplc-canopen-sim-runtime status [--show-password]   # container, image, PLC state and the last CANopen log lines
openplc-canopen-sim-runtime logs [-f]                  # the runtime's log
openplc-canopen-sim-runtime stop                       # start brings it back with the same program
openplc-canopen-sim-runtime update                     # the image for the installed tools' version, same data
openplc-canopen-sim-runtime remove [--data]            # delete the container; --data also the volume and saved credentials
```

`update` pulls the image that matches the installed tools (after a tools update), replaces the container and keeps the data volume, so the user, password and certificate stay the same. The new container has no program running: upload it again. `--image` runs another image, for example one built from a checkout (below).

## Renamed in 0.31.0

Tools 0.30.x called the command, image, container and volume `openplc-canopen-runtime`. From 0.31.0 they are `openplc-canopen-sim-runtime`, so the name says that everything in it runs simulated. A local runtime started with 0.30.x is taken over by the next `start` or `update`: the old container is replaced by `openplc-canopen-sim-runtime` on the same data volume (`openplc-canopen-runtime-data`), and the program data, user, password and certificate fingerprint stay. `openplc-canopen-runtime` still works in 0.31.x, with a one-line notice; the release after removes it. New images are published as `ghcr.io/tonihoohoo/openplc-canopen-sim-runtime`; the 0.30.x images stay under the old name.

## Limits

- Every CANopen network runs simulated, whatever `adapter.simulate` and the adapter settings say: the image sets `CANOPEN_FORCE_SIMULATE=1`, and the runtime log, `openplc-canopen-diag status` and the configurator's online view say so. A real CAN adapter cannot be reached from a container on Windows or macOS anyway.
- A simulated device behaves like a real one when it fails: a fault that stops its heartbeat (the ping-pong example's `device-hangs` scenario) makes the master report the node lost and boot it again, which resets the device's objects to their EDS defaults. A program that feeds a device's value back to it, like the ping-pong program, can then carry two counts at once (the value seems to jump between them) until the PLC is stopped and started.
- No real-time timing: the PLC cycle and the simulated bus run at the speed of a PC container, which is fine for logic and I/O but says nothing about jitter on the real target.
- On a Linux PC with a SocketCAN interface, experts can run the image with `-e CANOPEN_FORCE_SIMULATE=0 --network host` and the interface's capabilities; `openplc-canopen-sim-runtime` does not do this.

## Troubleshooting

- **"no container engine is running"**: start it (`colima start`, `podman machine start`, `sudo systemctl start docker`, or open the WSL distribution once). The message lists what was tried.
- **"port 8443 or 7531 is already in use"**: another runtime or program uses it; `openplc-canopen-sim-runtime update --port 8444 --diag-port 7532` moves this one (then set the config's diagnostics `port` to 7532 as well).
- **Lost credentials** (`local-runtime.json` deleted, or another PC user): they cannot be recovered. `openplc-canopen-sim-runtime remove --data` and `start` again create new ones; the uploaded program goes with the data.
- **Windows: localhost does not reach the runtime**: WSL2's localhost forwarding is off in `%USERPROFILE%\.wslconfig` (`localhostForwarding=false`); remove that line, or use `networkingMode=mirrored`, and run `wsl --shutdown`.
- **The engine refuses the extra capabilities** (some rootless setups): the runtime then starts without them, with a note; it works, with less precise PLC timing.
- **`mlockall failed: Cannot allocate memory`** in the runtime log at each PLC start: the runtime could not lock its memory. The container is started with an unlimited memlock limit, which rootless Podman cannot grant beyond the host user's own limit; the PLC runs normally, with less precise timing. A container made by tools before 0.31.1 has no such limit: `openplc-canopen-sim-runtime update` recreates it.

## Building the image from a checkout

```sh
docker build -f docker/local-runtime/Dockerfile \
  --build-arg RUNTIME_IMAGE=ghcr.io/autonomy-logic/openplc-runtime:$(cat docker/local-runtime/runtime-version) \
  --build-arg TOOLS_VERSION=dev -t openplc-canopen-sim-runtime:dev .
openplc-canopen-sim-runtime update --image openplc-canopen-sim-runtime:dev
```

`test/local-runtime/run.sh --image openplc-canopen-sim-runtime:dev --strucpp <strucpp>` runs the end-to-end check CI runs: start, a deploy of the ping-pong config with a compiled PLC program, the simulated node operational, diagnostics through the published port, stop, start, update and remove. Each tools release publishes `ghcr.io/tonihoohoo/openplc-canopen-sim-runtime:<version>` and `:latest` for amd64 and arm64.
