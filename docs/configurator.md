# Configuring CANopen in a browser: `openplc-canopen-config`

`openplc-canopen-config` edits the CANopen config of an OpenPLC editor project in a local web page: the CAN adapter, the master, the nodes with their supervision settings, the PDO mapping to PLC addresses, and the startup SDO writes. It writes the project's `canopen/` folder, which the editor's own **Build and upload** carries to a runtime with the [editor hook](install-stock.md#the-editors-build-and-upload). The stock editor itself is not changed: it has no extension point for a new kind of remote device.

It runs on the engineering PC, next to the editor, and needs Python 3.8 or newer and a browser. It listens only on `127.0.0.1` and loads nothing from the network. The only connection it makes is to the runtime you name for [online access](#online-access), and only while the **Online** view or **Scan the bus** is open or a [trace](#trace) is recording.

## Install

It comes with the deploy tool, in the same package. Install it without Python using uv (Windows and macOS steps in [install-pc.md](install-pc.md)), or with `pipx install ./tools/deploy`.

Without installing: `PYTHONPATH=tools/deploy python3 -m openplc_canopen_deploy.configurator.server --help` (needs `python3 -m pip install jsonschema`).

## Start

```sh
openplc-canopen-config                                   # start page
openplc-canopen-config ~/Documents/workspace/rtd-monitor # open a project directly
```

The command prints a URL such as `http://127.0.0.1:53412/?token=…` and opens it in the default browser (`--no-browser` only prints it). The token in the URL is the session key: the page cannot be used without it, so open the printed URL rather than typing the address. Press Ctrl-C in the terminal, or close the terminal, to stop.

The start page offers three ways in:

- **Open editor project**: a folder with `project.json`. The config is `<project>/canopen/canopen.json`, and every address is checked against the rest of the project.
- **Open standalone config**: a plain folder with `canopen.json` and its EDS files, for a bus set up before its editor project exists. The checks against a project are skipped, and the page says so.
- **New standalone config**: an empty config in a new or empty folder, created when you first save.

The folder browser and the list of recent folders are on the same page. A path given on the command line opens directly: as a project when it has `project.json`, as a standalone config otherwise.

## Bus and master

**Bus and master** holds the CAN adapter: its type ("SocketCAN" for a CAN HAT, a candleLight CANable, PEAK or vcan; "CANable / serial (slcan)" for a CANable with its stock firmware or a Lawicel CANUSB), the interface on the PLC and the bit rate from the CiA 301 list, then for SocketCAN whether the plugin sets up the link and the bus-off restart delay, and for slcan the serial device (`/dev/serial/by-id/...` on the PLC) and the optional serial speed. Switching type keeps the interface and bit rate and drops the other type's settings. Then come the master (node ID, SYNC source, SYNC period, master heartbeat, EDS lint; an empty SYNC period means no SYNC, and **Check** then names every PDO that still has a synchronous transmission type; **SYNC source** "PLC cycle" replaces the period with "Every N PLC cycles", see [config.md](config.md#sync-from-the-plc-cycle)), and the optional diagnostic inputs (bus state, TX and RX error counters, bus-off count, the master's own NMT state), each with **Suggest** for a free `%IB` byte or `%IW` word. A file that still uses the old top-level `interface` and `bitrate` keys is shown as an adapter with "sets up the link" off, and is saved in the `adapter` form. **EDS lint** chooses which of `dcfgen`'s EDS lint findings stop the PLC: **Communication objects** (the default, saved as no field) stops only on findings in 0x1000-0x1FFF that are not only about limits, **Every object** on any finding, **Off** on none ([config.md](config.md#eds-lint)). A file with the old `strict_eds` is shown as **Every object** (`true`) or **Off** (`false`), and is saved as `eds_lint`. See [config.md](config.md) for what each field does on the PLC.

A field left empty uses the slave's EDS default or the plugin's default, and the page shows that default in the field and in the hint under it. For the PDO transmission type and the heartbeat period, empty means nothing is written to the slave: it keeps the value from its EDS. Some defaults are worked out from other values: a PDO's COB-ID (CiA 301, for PDOs 1 to 4) from the node ID and PDO number, and the heartbeat timeout as 3 × the heartbeat period. Settings with a fixed set of values, such as the adapter type, bit rate, supervision method and PDO transmission type, are dropdowns that explain each choice.

## Add a node from its EDS

**Add node from EDS…** imports the device's EDS file. It must be a CiA 306 EDS (objects 0x1000 and 0x1018). It is stored in the config folder as UTF-8, converted from CP1252/Latin-1 when needed, because the editor sends project files as UTF-8 text. If a different EDS with the same name is already there, you choose between replacing it and keeping both. The import also runs the checks the PLC runs before `dcfgen`, under the current EDS lint setting: the banner says the file is readable, lists the corrections the PLC will make in its copy (a REAL value rewritten, an OCTET_STRING value Lely cannot read cleared, with its old text), and shows accepted lint findings as a collapsed list grouped by object. A file the PLC could not read, or with a finding that would stop it, is refused with the reason and no node is added. **Check** and saving rerun the lint for every node with its real node ID. The new node gets the first free node ID. Set its ID and name, pick the supervision method (EDS default, heartbeat or node guarding; only that method's fields are shown) the status bit, the state byte and the boot error byte, and under **Emergency (EMCY)** the EMCY code word and the error register byte; **Suggest** picks a free `%IX` bit, `%IB` byte or `%IW` word.

## Advanced settings

The master and each node have a collapsed **Advanced** section with the options `dcfgen` offers. It opens by itself when one of its fields is set, and its title counts them.

- **Master**: start-up (whether the master and the nodes go operational, start all nodes with one command, reset or stop all nodes when a mandatory node is lost, boot time), heartbeat consumer and timeout factor, the master's own identity, SYNC window and counter, TIME COB-ID and TIME period, EMCY and NMT inhibit times, and error behavior.
- **Node**: mandatory, boot and configure, reset communication, guarding retries, the expected revision and serial number, node ID by serial number (LSS), whether the node watches the master's heartbeat, its TIME COB-ID, restore configuration, error behavior, and the program file and version for a program download.

**TIME period (ms)** (`master.time_period_ms`, 100-3600000) makes the master send the runtime's time of day (CiA 301 TIME) at that period and at once when the bus comes up; the field shows the COB-ID it goes out on (0x100, or the master's TIME COB-ID). Empty saves nothing and sends no TIME. Nodes that should use it need their TIME COB-ID with bit 31 (0x80000000) set; without such a node the check shows a warning. Keep the runtime's clock right (NTP), because TIME carries it as it is.

Node-side fields (heartbeat consumer, TIME COB-ID, restore, error behavior) left empty write nothing, so the node keeps its EDS value, which the field shows as its placeholder. Error behavior is typed as `sub=value` pairs, for example `1=0, 3=2`. A program file must be in the config folder; the editor's project upload corrupts binary files, so deploy one with `openplc-canopen-deploy --runtime`. See [config.md](config.md#node-options) for what each setting does.

**Node ID by serial number (LSS)**: for devices without DIP switches. **Assign node ID by serial number (LSS)** (`lss.assign`) makes the master find the device by the vendor ID and product code of its EDS and the node's **Serial number**, and give it the node's ID at every start, before the network boots; the serial number is then required, and **Reset communication before boot** stays on (the new ID becomes active only on a communication reset). **Store node ID in the device** (`lss.store`) also saves the ID in the device's memory, only when the master had to change it; it is off by default and needs the first box. Unticked boxes are left out of the file. An EDS that does not say `LSS_Supported=1` shows a warning; the box can still be ticked. See [config.md](config.md#lss).

## CiA 402 axis

**Use as a CiA 402 axis**, under the node's **CiA 402 axis**, makes the node a PLCopen axis for the editor's motion blocks (`axis` in the file) and shows its three scaling fields. **Map CiA 402 objects** puts the drive's standard objects that are not mapped yet (controlword, statusword, modes, target and actual position, velocity and torque) into its PDOs with suggested locations: into the PDO whose EDS default mapping has the object where that PDO keeps the device's mapping or is not in the config yet, otherwise into a PDO the master can write, and it suggests a status bit when the node has none. It lists what it mapped and what it could not, with the reason (not in the EDS, not mappable that way, no free PDO, no fixed mapping that has it). Transmission types stay at the EDS values. The page notes an EDS whose device type is not profile 402, and a missing status bit, which an axis needs. **Variable declarations** then also gives the axis, its bridge and the bridge call. See [cia402.md](cia402.md).

## Map PDO entries

**Map an object** lists only the objects the node's EDS marks as PDO-mappable. Objects the slave sends are inputs (TPDOs, `%I`), and objects it receives are outputs (RPDOs, `%Q`). For an `rw` object you choose the direction. **Add** puts the entry in the last PDO of its direction while it has room (8 entries, 64 bits), otherwise in the next PDO the EDS defines. The entry's type comes from the EDS, and its PLC location is the lowest free one of the right size from 100 up, skipping addresses the CANopen config or the editor project already uses (Modbus remote devices, EtherCAT channels, pin mapping, located variables). You can type any other location, set a PDO's number, COB-ID (a number, or `auto`; the page shows what `auto` resolves to) and transmission type, and move an entry to another PDO.

Under each PDO, **Mapping** says who sets its mapping. When the EDS makes it read-only, it reads **Set by the device** and lists the device's mapping, the objects the config uses in bold; **Map an object** then offers, for a direction whose PDOs are all fixed, only the objects of those mappings, and **Add** puts each in the PDO that carries it. **Map all** adds every object of the mapping that is not mapped yet, with suggested locations. When the master may write the mapping, you choose **Write from this config** (the default) or **Use device mapping**, which saves `"mapping": "device"`: the node keeps its EDS mapping, and an entry outside it is shown as an error. See [Devices with a fixed PDO mapping](config.md#devices-with-a-fixed-pdo-mapping).

Under each PDO, **Timing** shows the communication settings the node's EDS defines for that PDO: for a TPDO the inhibit time (in ms, stored in µs), the event timer and, with a synchronous transmission type, the SYNC start value; for an RPDO the deadline (event timer). A setting the EDS does not define is not shown. One it marks read-only shows the EDS value and cannot be changed, and so does a read-only transmission type. Empty fields show the EDS value and write nothing.

## Startup SDO writes

Each node has an ordered list of SDO writes that the plugin performs every time the node is configured at boot, after the PDO parameters. Pick an object from the node's writable EDS objects, or type its index and subindex.

By default the list shows only settings. It hides process signals (PDO-mappable objects, which belong in a PDO), the communication objects the plugin writes itself from the node's settings (0x1005-0x1007, 0x100C, 0x100D, 0x1014-0x1017, 0x1400-0x1BFF, 0x1F80), and objects already in the list. A line under the list says how many it hid and why. **Show all writable objects** lists everything. A write to an object the plugin also sets is accepted with a warning, because it runs last and overrides that setting. Objects the EDS does not define, or marks read-only or const, are refused, because the plugin would refuse them too. Values are checked against the type's range. Use ↑ and ↓ to change the order.

## SDO variables

**SDO variables** lists the objects the program reads or writes over SDO while the network runs (see [SDO variables](config.md#sdo-variables)). Choose **Read** or **Write** above the picker: it lists the EDS objects that allow that direction (a write never lists `ro` or `const` objects), or type an index and subindex. Objects the EDS does not define are refused. **Add** takes the type from the EDS and suggests a free value location of the right area and size. Each variable is a block: the object, the name, the type, the direction and the remove button on the first line; the value location, the period (read entries), the trigger bit, the status byte, the abort code and the timeout below it, each location with a **Suggest** button. A write to an object the plugin configures itself (marked "set by the plugin" in the picker) is accepted with the plugin's warning.

The node's **NMT command** field, next to the state byte, takes an output byte (`%QB`) for [NMT commands from the program](config.md#nmt-commands-from-the-program); its hint lists the codes.

## Checks and saving

Every change is checked as you type, with the same checks the deploy tool and the plugin run: the JSON Schema, the EDS type and access checks, node ID uniqueness, overlapping locations and SDO value ranges. Errors appear next to their field and in **Problems**, named by node, PDO, object or SDO variable; clicking one goes to its field. **Save** stays disabled while there are errors.

In a project, a CANopen location that a Modbus device, an EtherCAT channel or the pin mapping also uses is an error that names the other file. **Allow overlap** appears in **Problems** under such errors; tick it to save anyway, as with the deploy tool's `--allow-clash` (the Save button then reads "Save (overlaps allowed)"). It is not saved and is off again when the config is reopened. A located variable at exactly a CANopen entry's location is not a clash: the entry shows that it is declared under that name.

Saving writes only `canopen.json` and the imported EDS files, in the config folder. Fields the configurator does not know are kept. EDS files no longer used are listed and left in place. If `canopen.json` changed on disk after the page loaded it, saving asks whether to reload it or overwrite it.

Messages about what you did (saved, sent, copied) show in a bar under the header and close by themselves after a few seconds; errors stay until you close them (✕). Switching to another view clears the bar.

In a window narrower than about 1100 px, **Problems** becomes a strip under the header with the problem count (click it to open the list), and the node list a bar above the page.

**Light / Dark / Auto** in the header picks the page's colours; **Auto** (the default) follows the operating system. The choice is kept in `ui.json` in the configurator's settings folder (the same folder as `online.json`, see [Online access](#online-access)), so it survives restarts; it is never written to the project.

## Export DCF files

**Export DCF** on a node in the node list (shown when the node is selected or under the pointer) downloads `node_<id>.dcf`, that node as a CiA 306 Device Configuration File; **Export all DCFs** in the header downloads every node's file in `<folder>_dcf.zip`. Both export the config as the page shows it, saved or not, and write nothing into the project.

Each file is the node's EDS with a `ParameterValue` on every object the master writes to it at boot, a `[DeviceComissioning]` section (node ID, name, bit rate) and updated `[FileInfo]`, checked with Lely's CiA 306 lint before it is offered. If the config has an error or a DCF fails a check, nothing is downloaded and **Problems** names the node, the DCF section and the key. What goes into the file and which checks run: [deploy.md](deploy.md#export-the-nodes-as-dcf-files) (`openplc-canopen-deploy --export-dcf` writes the same files).

## Export a DBC file

**Export DBC** in the header downloads `<folder>.dbc`, the network as a DBC file for CAN bus tools such as SavvyCAN, Wireshark or `python -m cantools monitor`: every configured PDO, each node's heartbeat and EMCY, NMT and, when the master produces SYNC, SYNC. The list next to it picks the SDO frames: **No SDO frames** (the default), **SDO: configured objects** (the config's SDO variables and startup SDOs) or **SDO: all EDS objects**; the choice is kept in `ui.json` with the theme. It exports the config as the page shows it, saved or not, and writes nothing into the project. In an editor project, a signal whose address has exactly one located variable is named after it; otherwise signals carry the object's name from the EDS. If the config has an error, nothing is downloaded and **Problems** says why; warnings (a startup SDO rewriting a PDO's settings) appear there after the download. What goes into the file: [deploy.md](deploy.md#export-the-network-as-a-dbc-file) (`openplc-canopen-deploy --export-dbc` writes the same file).

To watch the bus on a PC with a CAN adapter, open the file in SavvyCAN or Wireshark, or run `python -m cantools monitor -c can0 bus.dbc` (cantools 39 or newer; `pip install cantools`).

## Variable declarations

**Variable declarations** lists a name, location and IEC type for every mapped entry, status bit (`BOOL`), state and boot error bytes (`USINT`), EMCY code (`WORD`) and error register (`BYTE`), NMT command byte (`<node>_nmt`, `USINT`), SDO variable (the value with the object's IEC type, and `_trig` `BOOL`, `_status` `USINT` and `_abort` `UDINT`), and the bus diagnostic inputs (`can_bus_state`, `can_tx_errors` and `can_rx_errors` as `USINT`, `can_bus_offs` as `UINT`), and gives them as a `VAR ... END_VAR` block to paste into the `VAR` block of the program that uses them. Do not put them in a global variable list (GVL): with editor 4.3.2 (STruC++ 0.7.0) located variables declared there do not reach the runtime, which logs `[image_tables] 0 located var(s)` and the values stay 0. Entries the project already declares at the same location are left out of the block. With a CiA 402 axis, the block also has the axis and bridge declarations and the lines to put first in the program body ([cia402.md](cia402.md#the-generated-program)).

```
VAR
  rtd_ok           AT %IX10.0 : BOOL;
  rtd_AI0_Input_PV AT %IW100 : INT;
  ...
END_VAR
```

## Online access

**Bus and master → Online access** turns on the plugin's diagnostics channel (`master.diagnostics`, see [config.md](config.md#online-diagnostics) and [diagnostics.md](diagnostics.md)). Turning it on generates a random access token, writes only its SHA-256 into the config, and keeps the token itself in the configurator's settings on this PC (`online.json` in the settings folder: `~/Library/Application Support/openplc-canopen` on a Mac, `%APPDATA%\openplc-canopen` on Windows, `~/.config/openplc-canopen` on Linux), per project folder. It is never written to the project. The section also sets the port, the bind address and **Allow changes** (off by default; turning it on warns that anyone with the token can then write parameters and stop nodes), and the **Runtime host** (`plc.local`, or `HOST:PORT`), which is kept with the token.

- **Copy token** copies it, for `openplc-canopen-diag` or another PC.
- **Enter token…** takes a token from another PC; it is accepted only if its SHA-256 matches the config.
- **New token** replaces it; the old one works until the new config is uploaded.

Save and upload the program as usual: the runtime opens the port when the PLC starts.

On a PC without the host or token yet (a fresh install, another PC), **Online** and **Scan the bus** show a **Connect** box: enter the runtime host and press **Connect**. It asks for the token when this PC has none or one that does not match the config, and says what is missing instead of doing nothing.

## Online view

**Online** connects to the runtime and refreshes about twice a second: the bus state and error counters, the master's state, and per node its NMT state, status bit, boot result (with the CiA 302 error letter and Lely's text, and whether a retry is pending), hold (STOPPED or PRE-OPERATIONAL, by the program or by an operator), last EMCY with its CiA 301 class, and SDO variable values. A connection problem is shown with its reason (host unreachable, port closed, wrong token) and retried. When the runtime runs another config than the saved `canopen.json` (saved but not uploaded yet), the view says so.

Click a node for:

- **NMT**: Start, Stop, Pre-operational, Reset node, Reset communication; stop and the resets ask first. Stop and pre-operational hold the node until you start it or the program changes its NMT command byte.
- **SDO**: pick any object of the node's EDS (or type index and subindex), **Read** it, and see the value decoded with its type (numbers in decimal and hex, VISIBLE_STRING as text, the rest as hex bytes) or the abort code with its CiA 301 text. **Write** encodes a value with the type after a range check, and asks first when the plugin configures that object itself at boot, a startup SDO writes it, or an SDO variable of the program writes it: those win again at the next boot or write.
- **Emergency history**: the node's last 16 EMCY messages, newest first, with time, code, class, error register and manufacturer bytes.

Each node has three tabs: **Overview** (the parts above), **Object dictionary** and **Parameters**.

**Object dictionary** shows the node's EDS as a tree, grouped as communication (0x1000-0x1FFF), manufacturer (0x2000-0x5FFF) and device profile (0x6000-0x9FFF). Groups and objects start folded: a plain object is one row, an ARRAY or RECORD object is a row with ▸ that unfolds its sub-entries, each shown by its own name. Each row has the type, access and EDS default; long names wrap, so the buttons stay in view. The tab takes the room of the Problems pane, as the trace does.

- **Search** on index or name unfolds what matches. The filters next to it narrow the tree further: **Changed from default**, **Writable**, **Set by config or SDO variable**, **In a PDO**, **Not readable**, and after a compare **Different in last compare**.
- **Read all** reads every readable entry one at a time, with progress and **Cancel**; it stops by itself when the node does not answer three times in a row. **Read** on an object reads all its sub-entries; on an entry, that entry. An object row counts its entries that differ from the EDS default or could not be read.
- Marks: **≠ default** (the value differs from the EDS default), **set by config** (the configuration writes it at boot), the SDO variable's name, and the PDO that carries the entry with its bits and PLC location, such as **TPDO1 bits 0-15, %IW100**. Values of PDO-mapped entries are still read over SDO.
- Numbers show in decimal; the small **dec/hex/bin** list switches one entry to hex or binary (two's complement for INTEGER types). **Bits** names the set bits of the error register (0x1001), the manufacturer status register (0x1002) and, on a CiA 402 drive (0x1000 says 402), the controlword (0x6040) and statusword (0x6041); 0x6060/0x6061 show the mode's name.
- **Edit** writes a value in place, with the SDO panel's checks and questions, and reads it back. It shows the EDS LowLimit and HighLimit and asks before writing a value outside them (vendor EDS limits are sometimes wrong; the device has the last word). After a write on a configured node, **Keep in configuration** adds a startup SDO with the value to the node, or changes the node's startup SDO for that entry, so the node gets it at every boot without storing it on the device; save the configuration and upload to use it. It is not offered for entries an SDO variable writes, objects the plugin sets itself (for example 0x1017 from the heartbeat setting, the PDO objects), entries another setting writes, and non-numeric types.
- **Read or write any entry** reads or writes an index and subindex the EDS does not list; without a type the value shows as hex bytes. Its **Copy as ST call** copies a call of the SDO function block for it.
- **ST** on an entry copies Structured Text for the PLC program: a declaration and call of the matching SDO function block (`CO_SDO_READ`, `CO_SDO_READ_STRING`, ...) with node, index and subindex filled in, and the conversion for its type. For a read-write entry it asks whether to copy the read or the write. See [plc-sdo.md](plc-sdo.md).
- **Copy** puts the shown rows on the clipboard (tab separated); **Save CSV** saves them. Folded rows are included, rows hidden by the search or filters are not.
- After **Compare** on the Parameters tab, the tree marks each compared entry (**= backup**, **≠ backup: value**, and so on) until you press **Clear**, reload the page or compare again.
- Tick **Watch** on up to 32 entries to read them again every 0.5, 1, 2 or 5 seconds. The watch list is kept on this PC per project and node (in `online.json`, not in the project) and comes back when you open the project again. It shows each value's age, marks a value that just changed, and keeps the minimum and maximum since watching started (**Reset min/max**). It says how long a round of reads takes and when that is longer than the period, and warns when the node has SDO variables the program reads periodically: watch reads go before them on the bus. **Graph** plots the watched numeric entries over the last 10 minutes; click a name in the legend to hide or show its line.

Without **Allow changes** the tab is read-only and says why.

**Parameters**:

- **Back up** reads every readable entry and downloads a DCF (`node5-rtd-20261005-143000.dcf`): the node's EDS with each value as `ParameterValue`, which other CANopen tools open too. The page asks first when the node has not booted, because the master may not have configured it yet.
- **Compare** reads the node and lists the entries against a backup file, the configuration (what the plugin writes at boot) or the EDS defaults: differences first, then entries that could not be read. Read-only entries are left out unless ticked.
- **Restore…** takes a backup file, reads the device and shows what it would write: only manufacturer and profile entries (communication objects when ticked) that differ from the backup, never PDO objects, the store/restore commands or what the configuration writes at boot, each left-out entry with its reason. A backup of another product (vendor ID or product code) needs **Restore to a different product anyway**; a different revision is only a warning. **Hold the node in PRE-OPERATIONAL while writing** is for devices that refuse writes while operational (abort 0x08000022); the node is started again afterwards, also after a failure or **Cancel**. Restored values are not stored on the device.
- **Store on device…** writes "save" to 0x1010 (the subindex chosen: all, communication, application or manufacturer parameters), so the device keeps its current values over a power cycle. It is only offered when the EDS has 0x1010, always asks first, and is never part of a restore, because each store wears the device's flash memory.

Read all, backup, compare and restore run in the configurator, not in the page: reloading the page or switching tabs does not stop them, and the tab shows a running one again. One runs at a time.

With **Allow changes** off, the write, NMT, restore and store buttons are disabled and say why; reading, backup and compare still work.

**Unconfigured devices (LSS)** commissions devices without DIP switches (needs **Allow changes**; otherwise the panel is disabled and says why). **Find a device without node ID** searches the bus with LSS fastscan, up to about 15 seconds, and shows the one device it found: vendor ID (with the vendor name from a matching EDS), product code, revision, serial number and a matching EDS from the project or the EDS library, as on the scan page. Then:

- **Set node ID…** suggests the lowest node ID that is neither configured nor the master's. A device that had no node ID starts with the new one at once; one that had another keeps it until it is reset or power-cycled. Afterwards the page offers to add the device as a node with that ID and EDS, its serial number and **Assign node ID by serial number** ticked, so the master gives it the ID at every start; nothing is written to the project until you save.
- **Set bit rate…** sets the device's bit rate for its next power cycle; the rest of the bus keeps its rate, so change the adapter bit rate under **Bus and master** once every device is set.

Both dialogs have **Store in the device**, unticked every time a dialog opens: without it, a power cycle undoes the change. Find the next device after setting one.

## Scan the bus

**Scan the bus** asks the runtime to read the identity (0x1018), device type (0x1000) and name (0x1008) of every node ID 1-127; it takes about 2 seconds, reads only, and PDOs keep running. A device that is STOPPED does not answer SDO and is not found. Each found device shows its node ID, vendor ID (with the vendor name from a matching EDS), product code, revision, serial number, device name, and its match against the config: configured, configured but a different device (the config's and the device's values side by side), not configured, configured but no answer, or booting.

For a device that is not configured, the page looks for EDS files with the same VendorNumber and ProductNumber in the project's `canopen/` folder and in the **EDS library folder** set on this page (a folder of vendor EDS files, searched with its subfolders), and offers them, an exact RevisionNumber first. **Add as node** imports the chosen EDS as **Add node from EDS…** would and adds the node with the scanned node ID; tick **also check revision and serial number** to set the node's identity check from the scanned values. Without a matching EDS, **Pick EDS file…** takes one from disk. **Object dictionary** opens the device in the online view with the chosen EDS, without adding it, for reading, backup and compare. Nothing is written until you save; map the new node's PDOs on its page first.

A found device with a serial number also offers **Use for node…**, listing the configured nodes whose EDS has the same vendor ID and product code: for example a replacement valve that came with another node ID or serial number. Picking a node sets its serial number to the device's and ticks its LSS assignment, and the device becomes that node at the next PLC start, after you save and upload.

A config with no nodes and online access on is a valid scan-only config: upload it to see what is on a new bus before configuring anything.

## Trace

**Trace** records the bus through the runtime, or shows a trace file, decoded as CANopen ([trace.md](trace.md)). Opening, viewing and exporting files works without a runtime; recording needs [online access](#online-access) for the project, and the view says so when it is missing. Frames are decoded with the saved `canopen.json`: PDO signals by their names (in an editor project, the PLC variables at their locations), SDO objects by their EDS names.

- **Start** begins a new trace (the one shown is replaced, so save it first), **Stop** ends it, **Clear** empties it. **Capture filters** (ID and mask) and **Record error frames** apply from the next Start. When the runtime's plugin is older than this feature, Start says the plugin is too old for traces and to update it with `install-stock.sh` and upload again.
- **Open file…** opens a pcapng, candump log or Vector ASC file. **Save** writes the trace in the chosen format to the `traces` folder in the configurator's settings folder and shows where; **Export** downloads it instead (pcapng, candump log, ASC, BLF, TRC, CSV, or the chosen graph series as a signals CSV). Both take the whole trace, the graph's zoom, or the time between cursors A and B.
- The line under the buttons counts the frames, the duration, the frame rate and estimated bus load while recording, error frames, and frames lost on the way or dropped by the PLC's kernel.
- **Frames** lists the decoded trace, newest at the bottom; **Follow** keeps the newest frames in view while recording, and scrolling up stops it. Display filters (nodes, frame kinds, an ID range, direction, and text in the decoded line) only change what is shown; recording goes on. Times are relative to the trace start or UTC. Even a trace of 2 million frames scrolls smoothly: the page only fetches the rows in view.
- **Identifiers** has one row per CAN ID: count, minimum, average and maximum cycle time, and the last data.
- **Graph** plots the chosen series: PDO signals, bus frame rate and estimated load, EMCY codes and SDO aborts, and while recording each node's NMT state and status bit, the bus state and error counters, and the SDO variables (read from the runtime twice a second). Series in the same lane share a chart; lanes share the time axis and the cursor. Drag to zoom, double-click or **Whole trace** to zoom out, ◀ ▶ to pan. A click sets cursor A, Shift+click cursor B; the table under the charts shows each series at A and B and the difference. **Show A in frames** selects the frame at cursor A in the list, **Back to graph** returns; a selected frame's **Show in graph** puts cursor A at it. Trigger hits and lost frames are marked in every chart.
- **Trigger** sets one condition, or two joined by AND or THEN, its count, single or normal mode, the pre- and post-trigger times, and auto-save of each hit's window ([trace.md](trace.md#triggers)). It applies to the next Start, and at once to a running recording. Hits are listed with buttons to show each in the frames or the graph.

The trace is kept by the configurator, not the page: reloading the page or switching views keeps it, and a recording goes on until Stop. The recording uses one of the plugin's 4 diagnostics client slots.

## From standalone to project

In a standalone config, **Move into project…** copies the saved config and its EDS files into an editor project's `canopen/` folder, after the same checks as `openplc-canopen-deploy --into-project`. It asks before replacing an existing `canopen/` folder. The page then switches to the project, and the address checks run against it.

## A new editor project from a standalone config

Starting without an editor project, **New editor project…** (standalone mode) creates one around the saved config. Give the folder to create it in, the project name and the task interval (default `T#20ms`). The configurator runs the editor's own `openplc-cli create` (so the project shows in the editor's recent projects), sets the target to OpenPLC Runtime v4, copies the config in as **Move into project…** does, and writes a program `main` that declares every CANopen location of the config, node by node with inputs before outputs and a description on each variable. If a runtime host is saved in the online settings, it becomes the project's runtime address. **Enable CANopen SDO blocks** (off by default) also enables the `openplc_canopen` library in the project and installs it into the editor if needed ([plc-sdo.md](plc-sdo.md)). The page then switches to the new project; open it in the editor with **Open Project**.

All CANopen I/O is declared in `main` because Editor 4.3.2 accepts located variables only in a program's VAR block. `main` is written once: locations added to the config later show under **Variable declarations** as not yet declared. An existing folder is refused, and the standalone folder is left as it was. This needs the editor's `openplc-cli` on the PATH (the editor installs it on first run, or run `openplc-cli install-cli`) or `$OPENPLC_CLI`; the same is available as `openplc-canopen-deploy --new-project` ([deploy.md](deploy.md#a-new-editor-project-from-the-config)).

## Then, in the editor

1. Paste the declarations, or declare the variables by hand.
2. **Build and upload** as usual. On a runtime with the editor hook, the upload carries `canopen/` and the runtime enables CANopen.

Without the editor hook, deploy with `openplc-canopen-deploy --config <project>/canopen/canopen.json --project <project> --runtime <pi>` instead; see [deploy.md](deploy.md).
