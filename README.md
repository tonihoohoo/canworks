<h1><picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/logo-dark.svg">
  <img alt="canworks" src="docs/images/logo-light.svg" height="120">
</picture></h1>

An open CAN toolkit: configure, commission, diagnose, trace and simulate **CANopen**, **J1939** and plain **CAN** networks. `canworks-bridge` runs the networks on a Linux device and serves their values as **Modbus TCP** registers, so any PLC, SCADA system or program with a Modbus client can use them. PC tools for Windows, macOS and Linux configure it and work on the bus directly.

> **Experimental.** All code, tests and documentation in this repository were written by Claude (Anthropic's AI model), directed and tested by a person. Treat everything here as experimental: it has run on a test bench, not in production, and comes with no warranty (see [LICENSE](LICENSE)). Do not use it to control machinery where a fault could hurt people or damage equipment.

canworks has two halves:

- **`canworks-bridge`** on a Linux device with SocketCAN runs CANopen master, slave and gateway networks, J1939 ECUs and plain CAN messages, and serves them over Modbus TCP. It is built on [Lely CANopen](https://gitlab.com/lely_industries/lely-core) and the Linux kernel's J1939 stack.
- **PC tools**: a configurator in the browser, a deploy tool, command-line diagnostics, a bus trace, device simulators and a local runtime in a container. They work through the bridge or straight through a USB CAN adapter on the PC.

## Targets

Every config has one target, what runs the CAN networks, picked in **New config…** and changeable later on the Project page ([docs/configurator.md](docs/configurator.md#project-target)):

| Target | Who runs the bus | How the program sees it |
|---|---|---|
| **Modbus bridge** | `canworks-bridge` | Modbus TCP registers and coils, for each of the config's connections |
| **CODESYS** | CODESYS's own CANopen Manager, which canworks configures | I/O channels named after each PDO entry |

### Modbus bridge

The config is a normal `canworks.json` with a `bridge` object. Its `%I`/`%Q` locations become input and holding registers, discrete inputs and coils by one fixed rule. A watchdog stops or holds the outputs when the client goes away, and status, control, live list and SDO request registers give the client what function blocks would. `canworks-deploy --bridge HOST` uploads a new config to a running bridge ([docs/modbus-bridge.md](docs/modbus-bridge.md)). [`examples/modbus-bridge`](examples/modbus-bridge/canworks.json) is a simulated example.

The programs and tools that use the registers are the config's **connections**, listed first on the configurator's **Modbus bridge** page, each with the files it needs from **Download** and who may write following them ([docs/modbus-bridge.md](docs/modbus-bridge.md#connections)):

- **OpenPLC:** the bridge runs next to an unmodified [OpenPLC Runtime v4](https://github.com/Autonomy-Logic/openplc-runtime), and saving the config in an OpenPLC Editor project writes the Modbus settings and a `canworks` variable list, so the program uses named values such as `canworks.dio_door_open` and the `canworks` function blocks ([docs/modbus-bridge.md](docs/modbus-bridge.md#openplc), [docs/plc-library.md](docs/plc-library.md)).
- **truST and other PLCs:** the variables, copy programs and function blocks as PLCopen XML (`--export-plcopen`, [docs/plcopen.md](docs/plcopen.md)), or the PLC link as ST ([docs/plc-library.md](docs/plc-library.md#on-another-modbus-plc)).
- **Node-RED:** the canworks node package, whose nodes read and write every value by name over one Modbus connection and run the function blocks' jobs (SDO, NMT, CAN, J1939, EMCY), and a flow that sets it up for the config (`--export-nodered-package`, `--export-nodered`, [docs/node-red.md](docs/node-red.md)).
- **HMI, SCADA or script:** the register map as CSV, JSON or IEC 61131-3 ST (`--export-modbus-map`).

### CODESYS

canworks puts the CANopen master networks of a config into a CODESYS project: **Build into CODESYS project…** runs CODESYS headless on the PC, and **Download for CODESYS** gives the DCFs and an import script ([docs/codesys.md](docs/codesys.md)). Slave, gateway, J1939 and plain CAN networks need the bridge.

## Bridge or native CAN

A PLC with its own CAN interface (such as the CODESYS target) runs the bus inside its cycle. Through `canworks-bridge` the bus runs on the bridge's device, and the PLC reads and writes it as Modbus registers. That works for any Modbus client, at this cost (numbers for a 10 ms poll; a client that polls slower is slower by the same factor):

| | PLC on its own CAN | PLC through the bridge |
|---|---|---|
| Delay of a value | Same PLC cycle | Up to one poll more each way (10 ms) |
| Values from the same moment | Yes, SYNC follows the PLC cycle | Not always: two PDOs can come from different polls, and SYNC runs on the bridge's own timer |
| Configured messages (PDOs, CAN and J1939 messages) | The latest value at each PLC cycle | The latest value at each poll |
| Can a CAN message go unseen? | Only when a newer frame of the same message comes within one PLC cycle | Only when a newer frame of the same message comes within one poll. A lone frame is always seen: its value stays until the next one. CAN messages can count their frames (`counter_location`); PDOs and J1939 PGNs can't |
| Receiving any CAN frame in the program | Every frame | Every frame, queued, at up to about 450 frames/s, about 1050 with two receive blocks (needs mailboxes). A full queue drops frames and says so (`DROPPED`, `OVERFLOW`) |
| Sending from the program | Every cycle | Configured messages on change, on a trigger bit or periodic; free frames about 50/s per request mailbox, up to 4 (needs mailboxes) |
| SDO from the program | The bus round trip | Plus about two polls (20–30 ms); over 4 bytes needs mailboxes |
| Node supervision, NMT, live list | In the PLC | In the bridge; the program reads the live list and status and sends NMT commands |
| PLC stops or the network drops | Outputs follow the PLC | The bridge's watchdog stops, zeroes or holds the outputs after a set time |
| Extra load on the PLC | None | A few Modbus requests every poll (about 5 for a small map, 2 more with mailboxes) |

The bridge's mailboxes carry what the program decides at run time. They are off unless the program uses a block that needs them:

| The program wants to | Without mailboxes | With mailboxes |
|---|---|---|
| Read and write values, send NMT commands, see which nodes are alive | Yes | Yes |
| Read or write an SDO of up to 4 bytes on any node | Yes | Yes |
| Read or write a longer SDO (strings, names, domains) | No (SDO variables in the config cover numbers up to 64 bits) | Yes |
| Send or receive a CAN id that is not in the config | No | Yes |
| See every EMCY | Only the latest code per node | Yes |
| Request any J1939 PGN, read DM2, clear DM3/DM11, find an ECU | Only the config's PGNs and DM1 | Yes |
| Read bus load and error counters | Only the bus state | Yes |

Rule of thumb: put everything you know when configuring into the config, and use the mailbox blocks only for what the program decides at run time ([docs/plc-library.md](docs/plc-library.md), [docs/modbus-bridge.md](docs/modbus-bridge.md#limits)).

## How it works

You describe the network in one JSON file (`canworks.json`, usually written by the configurator): the nodes, their EDS files, and which PDO entry goes to which location (`%IX`, `%IB`, `%IW`, `%ID`, `%IL` and the `%Q` equivalents), or for CODESYS which variable name. At every start, and for every new config it gets, the bridge checks the file against the EDS files, generates the device configuration with Lely's `dcfgen`, configures every node over SDO and then exchanges PDOs. A node that is missing or drops off the bus never stops the others, and a config with errors is refused with the errors in the bridge's log.

## Quick start

**Install the PC tools** with one line ([docs/install-pc.md](docs/install-pc.md)); run it again to update.

Windows (PowerShell):

```powershell
$f = "$env:TEMP\install-pc.ps1"; irm https://github.com/tonihoohoo/canworks/releases/latest/download/install-pc.ps1 -OutFile $f; powershell -NoProfile -ExecutionPolicy RemoteSigned -File $f
```

macOS and Linux (Terminal):

```sh
curl -LsSf https://github.com/tonihoohoo/canworks/releases/latest/download/install-pc.sh | sh
```

Then open the configurator from the **canworks configurator** shortcut, or run `canworks-config` ([docs/configurator.md](docs/configurator.md)).

**Install the bridge** on the Linux device, from the configurator's **Devices** page over SSH ([docs/devices.md](docs/devices.md)), or by hand on the device ([docs/modbus-bridge.md](docs/modbus-bridge.md#install)):

```sh
curl -LsSf https://github.com/tonihoohoo/canworks/releases/latest/download/install-bridge.sh | sudo bash -s -- --instance line1 --config ./line1
```

Add `--with-openplc` to also install OpenPLC Runtime, or use `--ssh admin@plc.local` from a PC. For CODESYS nothing is installed on the controller.

**Try it without hardware.** [docs/tour.md](docs/tour.md) walks through [`examples/virtual-plant`](examples/virtual-plant/README.md) with simulated networks on a PC.

## Features

### CANopen networks

On the Modbus bridge; CODESYS gets the master network settings it can take ([CODESYS](#codesys)). Every field is described in [docs/config.md](docs/config.md).

- **Networks and adapters:** up to 8 CAN networks from one bridge, each with its own adapter, master, bit rate, SYNC and nodes; a network that fails does not stop the others. Any SocketCAN interface works (CAN HAT, candleLight/gs_usb, PEAK, vcan), as do serial `slcan` adapters such as a CANable, driven directly without `slcand` and picked up again after a replug.
- **PDOs:** mapping from the config, or the device's own fixed or default mapping. Transmission type, inhibit time, event timer and SYNC start value default to the EDS's own values.
- **Bit channels:** single bits of a byte or word PDO entry (an I/O module's inputs, a drive's statusword) become BOOL variables with names of their own, defaulting to the device notes' bit names; the names reach the bus trace, DBC and HTML exports, CODESYS channels and Modbus map ([docs/config.md](docs/config.md#bit-channels)).
- **SYNC:** from the master's timer, or none for event-driven PDOs only.
- **PDO links:** one node's TPDO feeds other nodes' RPDOs directly (CiA 301 producer/consumer), checked against both EDS files, optionally running on while the PLC is stopped; nodes can watch each other's heartbeat (`heartbeat_watch`). See [`examples/pdo-link`](examples/pdo-link/README.md).
- **Node bring-up:** startup SDO writes, identity check (0x1018), mandatory nodes, heartbeat or node guarding (a node without either is refused unless the config says so), configurable SDO timeouts, and an opt-in configuration check (0x1020) that skips an unchanged download. Saving to the device's non-volatile memory (0x1010) only happens when a node asks for it: a startup write to 0x1010 or 0x1011 is refused. PDOs on the SYNC, TIME, EMCY, SDO, heartbeat or LSS identifiers are refused too.
- **LSS:** devices without DIP switches get their node ID from their serial number at every start and after a replacement.
- **EDS checks:** every EDS goes through Lely's CiA 306 lint, and every PDO entry and SDO is checked for type and access before anything is sent.
- **Safe stops:** when the Modbus client goes away or the PLC stops, the bridge stops or holds the outputs (`on_client_loss`) and the nodes go PRE-OPERATIONAL (or STOPPED, or stay as they are: `on_plc_stop`); a node that comes back gets the current outputs at once. A `stop_all_nodes` stop and node holds last through link drops and node resets.
- **Status for the program:** a status bit and state byte per node, bus state and error counters, the last EMCY per node (and the device's own error history 0x1003 in the diagnostics), the EMCY COB-ID read from each device after its boot, and an optional receive timeout per input PDO.
- **From the program:** SDO variables, NMT commands, and the blocks of the [`canworks` function block library](docs/plc-library.md) over the bridge's registers: `CO_SDO_READ` and `CO_SDO_WRITE` read or write any object of up to 4 bytes of any node when the program decides, `CO_NMT` commands any node (a node the program holds is never sent NMT START, also when it boots again; autostart off with `master.start: false`), and `CO_NODE_LIVE` reads the live list. Through the bridge's mailboxes, `CO_SDO_READ_BYTES`, `_STRING` and `_REAL` and their write blocks move objects of any size, and `CO_RECV_EMCY` gets every EMCY.
- **Everything `dcfgen` can set**, plus a TIME producer that sends the bridge host's clock.
- **Slave:** the bridge becomes a node on a network another master runs, with a generated EDS for that master's tool ([docs/slave.md](docs/slave.md)).
- **Gateway:** a slave network above master networks, with routes that copy values between them without the PLC program (held through upper master loss, gateway resets and field bus restarts), plus node status, EMCY forwarding and an SDO bridge ([docs/gateway.md](docs/gateway.md)).
- **Online diagnostics:** an opt-in channel for the PC tools, encrypted with TLS; the token never crosses the network, and SDO writes, NMT commands and scans on a running network need an explicit force.
- **CiA 309-3 gateway:** opt-in standard CiA 309-3 text commands (SDO, NMT, PDO read, LSS, EMCY and boot-up notifications) for SCADA systems, test benches and scripts, on a loopback port of the bridge's device and from other machines through the encrypted diagnostics channel (`canworks-diag gateway`), with the same guards as the diagnostics channel ([docs/cia309-gateway.md](docs/cia309-gateway.md)).
- **Remote access:** the device shows up by name in the configurator on the local network, over a direct cable, USB-C or its Wi-Fi hotspot, and with the remote link from any other network, behind NAT or on a mobile connection, with no account, VPN or router port. A PC pairs once with the diagnostics token on the local network; internet access is a tick box ([docs/remote-access.md](docs/remote-access.md)).

### J1939 networks

On the Modbus bridge. A network with `"protocol": "j1939"` makes the bridge an ECU ([docs/j1939.md](docs/j1939.md)): its own NAME and address claim, received PGNs on `%I` locations with not-available (J1939-71 ranges) and timeout bits that drop when the bus is lost, sent PGNs from `%Q` locations periodically or on change, request handling, and messages up to 1785 bytes through the kernel's transport protocol. Trouble codes work both ways: other ECUs' DM1 codes and lamps reach `%I` locations, and the bridge broadcasts its own codes switched by `%Q` bits, answers DM2, DM3 and DM11 from service tools and follows DM13. ST functions in the library pack signals, NAMEs and trouble codes; `J1939_SEND`, `J1939_RECEIVE`, `J1939_REQUEST` and the trouble code blocks send, receive and request any PGN from the program through the bridge's mailboxes ([docs/j1939.md](docs/j1939.md#program-blocks)). Signal scaling lives in a DBC file the tools use. J1939 and CANopen networks run side by side in one config.

### Raw CAN messages

On the Modbus bridge. Plain CAN messages run on any network, next to CANopen or J1939, or on a plain CAN network (`"protocol": "none"`, optionally listen-only) that carries nothing else ([docs/raw-can.md](docs/raw-can.md)). Received messages put DBC-style signals on `%I` locations with a timeout bit, counter and last frame; sent ones come from `%Q` locations periodically, on change or on a trigger bit. Multiplexed messages (simple and extended DBC multiplexing) work on raw and J1939 networks: received pages update their own signals with a valid bit each, and sent pages are picked by the program, sent all each period or in turn. Identifiers the protocol uses need an explicit override. Inputs go invalid at once when the adapter is gone, and sent messages stop with the outputs. ST bit and byte helpers in the `canworks` library pack and unpack frames; `CAN_SEND`, `CAN_SEND_CYCLIC` and `CAN_RECEIVE` send and receive any frame from the program through the bridge's mailboxes ([docs/raw-can.md](docs/raw-can.md#frame-blocks)). [`examples/raw-can`](examples/raw-can/canworks.json) is a plain network with its DBC file and simulated devices.

### Simulation

[docs/simulator.md](docs/simulator.md) starts with a table of what each simulator covers and where it runs.

- **CANopen devices** ([docs/simulator.md](docs/simulator.md)): any node, or a whole network, can be simulated from its EDS, so a project and its program run without the real devices or CAN hardware. Values can follow waveforms, formulas or recorded CSV data; faults (EMCY, lost heartbeat, power loss, SDO aborts, wrong identity, ...) come on command or from timed scenarios that test the program's reaction.
- **J1939 ECUs:** `canworks-j1939-sim` plays the other ECUs of a J1939 network from its DBC file on the PC, with a SocketCAN interface or a USB adapter ([docs/j1939.md](docs/j1939.md#simulator)). J1939 networks do not run on the simulated bus or in the local runtime.
- **Local runtime:** `canworks-local-runtime` runs the pinned upstream OpenPLC Runtime and `canworks-bridge` in two containers on the PC, every network simulated, so the editor uploads to `localhost` and debugs there ([docs/local-runtime.md](docs/local-runtime.md)).

### PC tools

Five commands in one package, for Windows, macOS and Linux ([docs/install-pc.md](docs/install-pc.md)). They reach the bus through the bridge, or straight through a USB adapter on the PC with no PLC at all ([docs/pc-adapter.md](docs/pc-adapter.md)):

- **slcan** adapters (such as a CANable) on every system.
- **gs_usb / candleLight** adapters on Windows with nothing else to install (the tools bring the driver and libusb), and on macOS after `brew install libusb`.
- **SocketCAN** interfaces on Linux.
- **An adapter on another machine:** `canworks-diag adapter-serve` on a Linux machine at the bus serves its adapter, with a token and encryption, to the configurator and `canworks-diag --adapter remote:HOST` on your PC ([docs/pc-adapter.md](docs/pc-adapter.md#an-adapter-on-another-machine)).

The configurator says when a newer release is out and updates itself with one click (**Update now**, or **Update when I quit**); `canworks-config --update` does the same from a terminal, and Settings turns the daily check off ([docs/install-pc.md](docs/install-pc.md#from-the-configurator)).

Finding runtimes and adapter servers on the local network listens on no port, so Windows Defender Firewall does not ask for it; pairing for the remote link may ask once per Python, and Cancel is fine ([docs/install-pc.md](docs/install-pc.md#windows-asks-to-allow-python)).

Every connection checks the bit rate first and refuses a wrong one, so a single device can be commissioned on the bench or as a guest on another master's bus, read-only until changes are allowed. Writes, NMT commands, scans and restores need `--force` while another master or a running node is on the bus.

| Command | What it does |
| --- | --- |
| `canworks-config` | The configurator, a local web page: build the network, commission devices, trace the bus, run simulations ([docs/configurator.md](docs/configurator.md)). |
| `canworks-deploy` | Writes the config and the editor files into an editor project, uploads the config to a bridge, checks configs offline, creates editor projects, installs the `canworks` function block library, and exports DCF, DBC, HTML network documentation, CODESYS projects, Modbus register maps, Node-RED flows, the Node-RED package and PLCopen XML ([docs/deploy.md](docs/deploy.md)). |
| `canworks-diag` | The online functions from a terminal: parameter backup, compare and restore, LSS, raw frames, trace and replay, simulator control, `explain` for a frame bit by bit, the CiA 309-3 `gateway`, and `discover` and `link` for runtimes on other networks ([docs/diagnostics.md](docs/diagnostics.md)). |
| `canworks-local-runtime` | The local runtime: the upstream OpenPLC Runtime and `canworks-bridge` in containers on the PC, every network simulated (Docker Engine, Podman or Colima; amd64 and arm64) ([docs/local-runtime.md](docs/local-runtime.md)). Not a device simulator. |
| `canworks-canopen-sim` | **CANopen** simulator, on the bridge's Linux device (installed with the bridge): plays CANopen and plain CAN devices from their EDS on a SocketCAN interface for any master, with a `test` mode that writes a JUnit report ([docs/simulator.md](docs/simulator.md#canworks-canopen-sim)). |
| `canworks-j1939-sim` | **J1939** simulator, on the PC: plays one node of a J1939 DBC file on a SocketCAN interface or USB adapter, with address claim, cycle times, ramps and scenarios ([docs/j1939.md](docs/j1939.md#simulator)). |

On the bridge's device, `canworks-link` is the remote link's service ([docs/remote-access.md](docs/remote-access.md)). Which simulator does what: [docs/simulator.md](docs/simulator.md).

### Configurator

`canworks-config` opens in the browser with three workspaces, a connection bar that always shows what the page is connected to, and a status bar that lists running jobs with Cancel ([docs/configurator.md](docs/configurator.md)).

- **Configure** edits the config from a network tree, with problem badges on every entry and simulated nodes marked. **+ Add node…** opens a dialog: the project's EDS files, the EDS library or Browse…, the node ID and name, and the EDS's default PDOs mapped to free PLC addresses in one step. Each node opens in tabs: General, PDOs, SDOs, Supervision, Simulated device, Notes and Advanced. PDO entries are mapped to byte addresses of the bridge's register image; an entry without an address says so, with Suggest. Settings a device's EDS cannot back (EMCY without 0x1014, the heartbeat consumer without 0x1016, LSS, the configuration check) are off with the reason in grey, and turn amber with a Remove link only when the config still has them. Slave, gateway, J1939 and plain CAN networks are set up here too, with **Import DBC…** for CAN messages (the DBC file is kept in the config folder).
- **Connect…** in the connection bar is the one place to connect: to a runtime, the CANopen simulator, a USB adapter or an adapter on another machine, with recent connections one click away.
- **Commission** opens on a Nodes table of the live network. **Scan the bus** compares the bus with the config (Match, Missing, Not in config, Identity differs) and adds a found device to the config in one click. The table shows when each node was last heard, and an EMCY 0x0000 clears its error mark. A node opens on its own page with a one-line header (state, last heard, ← Nodes back). Each node has Status, Object dictionary, Parameters, Notes and Log tabs (states, EMCY, error history, SDO, NMT, LSS, parameter backup and restore), and simulated devices take faults and value overrides from their Status tab.
- **Devices** installs what the project needs on a Linux device over SSH ([docs/devices.md](docs/devices.md)), and from the start page's **Install on a device** without any config, where you pick what the device runs (the Modbus bridge, or OpenPLC with the bridge). The device list is one for the PC, each device tagged with what it is to which project (**Runtime of line3**): it checks the device read-only and shows, per part, what it has and what the project needs, with one main action such as **Update 0.93.4 → 0.98.0**, **Switch runtime to v4.3.1**, **Install OpenPLC Runtime and the bridge** on a fresh device or **Install and start this project's bridge**. The remote link and the local-network advertisement have their own **Turn on…** / **Turn off…** there, and turning the link off keeps its paired PCs. The install runs on the device by itself, so a closed laptop or a restarted configurator does not stop it, and the page shows its steps and log. Host keys are trusted only after you saw them, and no SSH, sudo or runtime password is kept.
- **Commission a CANopen device** works on a USB adapter without any project. The Nodes table names every heard device without a scan (from 0x1008, a matching EDS or its profile) and matches devices against an EDS library folder picked with **Choose folder…**. Every EDS is picked from one list (matches for the device first, the project's files, the EDS library, Browse…), and a device notes file next to a picked EDS comes with it. **Change EDS…** swaps or clears a node's EDS, and a node without one gets the standard CiA 301/401/402 object dictionary. LSS and the PDO test run from here, and **Add to a config…** puts a device into a config.
- **Trace** records and decodes the bus ([docs/trace.md](docs/trace.md)). The By identifier view marks the bytes that change, a transmit list per network sends frames by hand, and **Decoding** adds DBC files that decode their messages. PDOs decode without a config, from the layout set on the bus, read from the device or taken from the node's EDS (marked assumed); a read names any PDO it could not make usable and why. The frame inspector (closed with ✕ or Esc, layers that fold) and **Frame lab** (result beside its Examples, Build and Arbitration tabs) explain every bit of a frame ([docs/frame-inspector.md](docs/frame-inspector.md)). The trace opens in a window of its own to watch the bus while sending from the main window; the graph zooms with the mouse wheel and the lists and graph lanes resize.
- **Project target** Modbus bridge or CODESYS on the **Project** page (the tree's first entry, with Online access): the page shows only what the target uses, in the target's own words; a setting the config has but the target does not use stays hidden and is left out on save (the save message says how many). A switch asks nothing: it removes the rest in one undo step, with **Undo** in its message ([docs/configurator.md](docs/configurator.md#project-target)).
- **Connections** on the **Modbus bridge** page: OpenPLC, truST, other PLCs, Node-RED and HMIs, each with its **Download** (register map, ST, PLCopen XML, Node-RED flow, with the Node-RED package next to it) and a mark when the map moved since ([docs/configurator.md](docs/configurator.md#connections)).
- **Exports** from the **Export** menu: DCF files, a DBC file and an offline HTML document of the networks ([docs/network-docs.md](docs/network-docs.md)), and on a CODESYS config the CODESYS download ([docs/codesys.md](docs/codesys.md)); a slave network's page has **Export EDS** for the other master's tool.
- **Device notes** explain objects: text, unit, scale, value meanings and bit names. CiA 301, 401 and 402 notes are built in, and a device's notes can replace or hide any built-in field. For anything else, each node's **Notes** tab shows your own notes first and is where you add (click an object's row), import and export them, also while commissioning a single device, where notes are written at once next to the EDS. Notes show in the object dictionary, the SDO lists and object pickers (unit and named values too), the HTML docs and the DBC export.
- **Save and problems:** Save always saves, also with errors; the steps that hand the config over (the CODESYS build and download, the bridge on a device, the editor files) refuse it until Problems has no errors. New config writes its folder at once (an existing empty folder can become an editor project), a new node starts supervised, and the supervision problem has quick fixes ([docs/configurator.md](docs/configurator.md#checks-and-saving)).
- **Lists:** a clicked or focused row is highlighted the same way in every list and table, and the object pickers and other list boxes have a resize bar that keeps its height ([docs/configurator.md](docs/configurator.md#the-page)).
- **Any window size:** a 1920×1080 laptop at 150 % (1280×720) keeps most of the height for the work area: compact header, a Simulated chip instead of a banner, the problems list as a one-line strip while it is empty, and the connection bar in the tab row. Between 800 and 1100 pixels wide the network tree is a rail of node IDs with their state; wide screens get two columns on the Bus page ([docs/configurator.md](docs/configurator.md#the-page)).
- **Small things done once:** **Suggest all** fills a node's PLC signals, the folder dialog tags OpenPLC projects and canworks configs, the device-changing restores are named for what they do, and a device that does not answer says what to check ([docs/configurator.md](docs/configurator.md)).
- **Messages:** information, done, warning and error bars look the same everywhere and sit at the top of what they are about: the page, a view, a section or a dialog ([docs/configurator.md](docs/configurator.md#message-bars)).
- **Access:** states have their own icon shape as well as their colour, the same on every view and in both themes, and every task works from the keyboard alone ([docs/configurator.md](docs/configurator.md#colours-and-icons)).

### Device notes from a datasheet with Claude

The repository has a [Claude](https://claude.ai/code) skill, `canworks-datasheet-notes` ([`.claude/skills/canworks-datasheet-notes`](.claude/skills/canworks-datasheet-notes/SKILL.md)), that writes a device's notes file from its datasheet or manual (PDF, DOCX, ODT, HTML, spreadsheets or text) and its EDS. It shows every place where the datasheet and the EDS disagree in one table, each row set to follow the EDS until you change it, and checks its result with `canworks-deploy notes check`. The same `notes skeleton` (with `--all`, every object with its EDS default, limits and PDO mapping), `builtin` and `check` commands help when you write notes by hand ([docs/configurator.md](docs/configurator.md#notes-from-a-datasheet)). Notes stay on the PC and never reach a device.

## Requirements and limits

- **Linux device:** Linux with SocketCAN (`slcan` adapters need Linux 6.0 or later) for `canworks-bridge`, as a systemd service (it restarts itself after a crash or a hang) or a container. For OpenPLC, the runtime runs next to it unmodified, as upstream's managed Docker install or a native install. canworks is pinned to OpenPLC runtime **v4.3.1** (`docker/local-runtime/runtime-version`): installs put a managed Docker device on it, CI tests it, and a device the OpenPLC Editor moved to another version gets **Switch runtime to v4.3.1** on the Devices page ([docs/devices.md](docs/devices.md)).
- **CANopen:** master and slave roles, one role per CAN interface; no CiA 402 motion control, flying master, MPDO or SRDO, and no program download as a slave.
- **Raw CAN:** classic CAN only (no CAN FD), raw integer signals.
- **Remote link:** device on Linux aarch64 or x86_64, PC on Windows x64, macOS on Apple silicon or Linux (no iroh package for Intel Macs); for diagnostics, commissioning and uploads, not for control traffic ([docs/remote-access.md](docs/remote-access.md#what-the-remote-link-is-for-and-what-not)).
- **Modbus bridge:** Linux with SocketCAN, Modbus TCP server only (no RTU), one config per bridge process, and one bridge per CAN interface. Function blocks share at most 4 request mailboxes, 32 receivers and 16 cyclic jobs ([Bridge or native CAN](#bridge-or-native-can), [docs/modbus-bridge.md](docs/modbus-bridge.md#limits)).
- **CODESYS target:** CANopen master networks only (slave, J1939 and plain CAN networks stay with canworks), CODESYS V3.5 with CANopen support on Windows for the import, tested with V3.5 SP22 ([docs/codesys.md](docs/codesys.md#requirements-and-limits)).
- **J1939:** one ECU per interface, raw integer signals, diagnostic messages DM1, DM2, DM3, DM11, DM13 and DM22 only (no freeze frames or emissions DMs) ([docs/j1939.md](docs/j1939.md#limits)).

## Documentation

| Topic | Page |
| --- | --- |
| Guided tour without hardware | [tour.md](docs/tour.md) |
| Installing the bridge (and OpenPLC) on a Linux device | [devices.md](docs/devices.md), [modbus-bridge.md](docs/modbus-bridge.md#install) |
| Installing the PC tools | [install-pc.md](docs/install-pc.md) |
| The config file | [config.md](docs/config.md) |
| Configurator | [configurator.md](docs/configurator.md) |
| Device notes, by hand or from a datasheet with Claude | [configurator.md](docs/configurator.md#device-notes) |
| Deploy tool and exports | [deploy.md](docs/deploy.md), [network-docs.md](docs/network-docs.md) |
| Diagnostics and USB adapters on the PC | [diagnostics.md](docs/diagnostics.md), [pc-adapter.md](docs/pc-adapter.md) |
| CiA 309-3 gateway for SCADA, test benches and scripts | [cia309-gateway.md](docs/cia309-gateway.md) |
| Reaching the PLC from other networks, or with no network | [remote-access.md](docs/remote-access.md) |
| Bus trace and frame inspector | [trace.md](docs/trace.md), [frame-inspector.md](docs/frame-inspector.md) |
| Function blocks for the program (CANopen, CAN, J1939) | [plc-library.md](docs/plc-library.md) |
| Slave and gateway | [slave.md](docs/slave.md), [gateway.md](docs/gateway.md) |
| J1939 | [j1939.md](docs/j1939.md) |
| Raw CAN messages and frame blocks | [raw-can.md](docs/raw-can.md) |
| Modbus TCP bridge for any PLC or program | [modbus-bridge.md](docs/modbus-bridge.md) |
| Node-RED through the Modbus bridge (canworks nodes) | [node-red.md](docs/node-red.md) |
| CODESYS, truST and other PLCs through PLCopen XML | [plcopen.md](docs/plcopen.md) |
| CANopen networks in CODESYS | [codesys.md](docs/codesys.md) |
| Simulation and the local runtime | [simulator.md](docs/simulator.md), [local-runtime.md](docs/local-runtime.md) |
| CANopen standards: what canworks follows, where it departs, how it is checked | [standards.md](docs/standards.md) |
| Building, testing, CI and the repository layout | [development.md](docs/development.md) |

## Development

Security issues: see [SECURITY.md](SECURITY.md). [docs/development.md](docs/development.md) covers the development build, the test suites, CI and the repository layout. The configurator's page tests drive it in Chromium, and a separate browser workflow runs it against the real bridge on its simulated bus, with no CAN hardware or vcan. The behaviour is specified with [OpenSpec](https://github.com/Fission-AI/OpenSpec) in `openspec/specs/`, one folder per capability; new work starts as a change under `openspec/changes/` and is archived into the specs once merged.

### PC tools on Windows, macOS and Linux

`.github/workflows/pc-tools.yml` installs the PC tools with the one-line installer (`scripts/install-pc.sh`, `install-pc.ps1`; uv underneath) on Windows, macOS and Linux (x86_64 and ARM64) on version bumps on `main` (the release waits for it), on `deploy-v<version>` tags and on "Run workflow" (start it on a pull request's branch when a change needs those systems checked). On your own PC, from a checkout (bash; Git Bash on Windows):

```sh
uv export --project tools/deploy --frozen --no-hashes --no-emit-project --no-dev --format requirements-txt -q -o constraints.txt
uv build --wheel --out-dir dist tools/deploy && sh scripts/install-pc.sh --wheel dist/*.whl --constraints constraints.txt
uv run --no-project --python 3.14 --with-requirements constraints.txt python .github/scripts/test_shard.py --shard 1/1 --start tools/deploy/tests --top tools/deploy  # one worker per CPU; --jobs 1 for one process
uv run --no-project --python 3.14 python test/pc-tools/smoke.py "$(sed -n 's/^version = "\(.*\)"/\1/p' tools/deploy/pyproject.toml)"
```

The tools' dependency versions are locked in `tools/deploy/uv.lock` (run `uv lock --project tools/deploy` after changing a dependency; CI checks it). Dependabot proposes one update of the lock a month. A monthly workflow opens an issue when upstream releases a newer OpenPLC runtime than CI tests with, and the configurator's **Devices** page notes devices that run one.

A `deploy-v<version>` release publishes the tools as a wheel on GitHub (with `canworks-<version>-constraints.txt`, its locked dependency versions) and the Modbus bridge image `ghcr.io/tonihoohoo/canworks-bridge:<version>` (`release-deploy.yml`). Its notes are `tools/deploy/release-notes.md` plus what each pull request since the previous release changed, and only the newest four releases are kept ([docs/install-pc.md](docs/install-pc.md#releases)).

## License

Apache License 2.0, see [LICENSE](LICENSE). Bundled third-party code keeps its own license: Lely's `dcf` package in `tools/deploy/canworks/_lely_dcf/` (Apache 2.0, with its NOTICE) and uPlot in `tools/deploy/canworks/configurator/static/uplot/` (MIT). The ping-pong slave's EDS follows the [Lely CANopen C++ tutorial](https://opensource.lely.com/canopen/docs/cpp-tutorial/). Every other EDS file in this repository describes a made-up device written for the tests.
