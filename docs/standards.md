# CANopen standards

Which CiA standards canworks follows, which parts the Lely CANopen stack does and which canworks does itself, where it departs from a standard on purpose, what it does not do, and how conformance is checked. canworks is not certified by CiA.

## At a glance

| Standard | What it covers | canworks |
|---|---|---|
| CiA 301 | Communication profile: NMT, SDO, PDO, SYNC, TIME, EMCY, heartbeat, object dictionary | Master, slave and gateway, simulated devices. Mostly Lely; see [Master](#master-cia-301-and-cia-302) and [Slave](#slave-and-gateway-cia-301). |
| CiA 302-2 | NMT master boot-up | Lely's boot-up with a few deliberate [departures](#departures-from-cia-302-2). |
| CiA 302-3 | Configuration manager | Same result on the bus, done differently ([below](#departures-from-cia-302-2)). |
| CiA 305 | LSS | Master and slave, Lely's services ([config.md](config.md), [slave.md](slave.md)). |
| CiA 306 | EDS and DCF files | Reads vendor EDS files; writes the slave EDS and DCF exports, checked against CiA 306 ([below](#files-cia-306)). |
| CiA 309-1/-3 | ASCII gateway over TCP | Lely's text layer, canworks' own service handling ([cia309-gateway.md](cia309-gateway.md)). |
| CiA 401, 402, 404 | Device profiles | Used through their objects (simulated devices, the CiA 402 axis library); canworks has no profile conformance of its own. |
| CiA 302-4, -6, -7 | Network variables, redundancy, multi-level networking | Not implemented. |

## Master (CiA 301 and CiA 302)

Done by Lely: the boot-slave procedure, NMT startup and slave assignment (0x1F80, 0x1F81 from the config), identity checks (0x1F84-0x1F88) with boot error statuses A to O, boot time (0x1F89), heartbeat and node guarding consumers, error behaviour (0x1029), the timer SYNC producer, the EMCY consumer, the SDO client (expedited and segmented), PDOs, and the LSS master.

Done by canworks, as CiA 301 says:

- The PDO mapping order: COB-ID invalid, count 0, entries, count, COB-ID valid. Inhibit time, event timer and SYNC start are written while the PDO is off.
- The EMCY consumer covers every node ID 1-127, and an EMCY COB-ID change goes through "invalid" first.
- SYNC from the PLC cycle and the TIME producer are sent by canworks itself. Neither is sent while the master is NMT STOPPED, and the SYNC counter starts again at 1 when the master resets communication.
- The configuration check stamp in 0x1020 stays inside CiA 301's ranges (days since 1984 and milliseconds after midnight), although it is a hash, not a real date ([config.md](config.md#configuration-check)).

### Departures from CiA 302-2

These are deliberate, so the PLC keeps control of its network:

| What | CiA 302-2 | canworks | Why |
|---|---|---|---|
| Starting nodes | "Start all nodes" is one broadcast. | A node the program or an operator holds STOPPED or PRE-OPERATIONAL is not started; the others get their own START. | A held node must stay held ([config.md](config.md)). |
| Missing mandatory node | Boot-up halts. | The master keeps retrying and starts once every mandatory node has booted. | The machine recovers without a restart. |
| Boot retries | Left to the application. | Backoff retries; RESET NODE after status L or J; a node that leaves OPERATIONAL is booted again. | Unattended recovery. |
| Configuration manager (302-3) | Concise DCFs in 0x1F22, 0x1F20/0x1F25. | The plugin downloads the same values itself, one SDO at a time; 0x1F20, 0x1F21, 0x1F25 are not supported. | One download path with logging per write. |
| Saving on the device | Optional. | 0x1010 "save" only with `store_configuration` and `config_check`, never automatic. | Device memory is written only when the user asks. |
| Master TPDOs | Valid from the start. | Off until their node is up. | No output frames to a node that is not there. |

### Gaps

- The SDO client uses no block transfer.
- RTR PDOs (transmission types 252 and 253) are refused.
- 29-bit PDO COB-IDs are cut to 11 bits.
- An LSS retry does not reset a device that kept a wrong node ID.
- The master sends no EMCY of its own for an RPDO timeout or a short PDO; it logs them.

## Slave and gateway (CiA 301)

Done by Lely: NMT slave, boot-up, heartbeat producer, node and life guarding, SDO server including block transfer, PDOs with dynamic mapping where the EDS allows it, SYNC and TIME consumers, EMCY producer with 0x1003, 0x1014 and 0x1015, LSS slave.

Done by canworks: 0x1F80 = 0x04 when the EDS has none, so the slave waits in PRE-OPERATIONAL for its master; 0x1010/0x1011 with the CiA 301 signatures, abort 0x08000020 on a wrong one, restored values applied at the next reset; LSS bit timing answered "not supported".

Proprietary: the gateway's field node status objects and SDO bridge record, and the layout of forwarded field EMCYs (network and node in the manufacturer bytes). They are manufacturer objects, not CiA 302-7.

## CiA 309-3 gateway

Lely's text layer parses commands and formats answers. Not served (`ERROR: 100`): PDO writes and PDO configuration, `init`, `set id`, `set heartbeat`, guarding on and off, `lss_switch_glob 1`, `lss_activate_bitrate`, and Lely's own `_sync`, `_time` and `_boot`. CiA 309-3 has no access control; canworks adds it (loopback only, remote access through the token-protected diagnostics channel, read-only by default). Details in [cia309-gateway.md](cia309-gateway.md).

## Files (CiA 306)

canworks writes two kinds of file:

- The slave EDS ([slave.md](slave.md)): every key CiA 306 lists in `[FileInfo]` and `[DeviceInfo]`, the standard objects with their CiA 301 names and defaults, printable ASCII, REAL values as decimal numbers.
- DCF exports ([deploy.md](deploy.md#export-the-nodes-as-dcf-files)): the node's EDS with ParameterValue, `[DeviceComissioning]` and file information added. REAL values are written as decimal numbers; the rest of the file is the vendor's EDS as the plugin reads it.

The plugin reads vendor EDS files more leniently than CiA 306 asks (`eds_lint`, [config.md](config.md)), because real devices ship imperfect files.

## How conformance is checked

- **CiA 306:** every file canworks writes goes through Lely's lint and a strict check of its own (`canworks/cia306.py`): the `[FileInfo]` and `[DeviceInfo]` keys, CiA 306 date and time forms, ASCII, line length, object lists, decimal REALs, and CiA 301 defaults of the standard objects. The generator and the export refuse a file that fails it, and CI runs it over every generated EDS and exported DCF of the fixtures and examples.
- **Behaviour:** unit, simulated-bus and virtual CAN tests ([development.md](development.md)) check the master, slave and gateway frame by frame. They run against Lely devices, so they test canworks' own logic, not Lely's conformance.
- **Official testing:** CiA's Conformance Test Tool (test plan CiA 310-1) tests CiA 301 slaves and their EDS; it runs on Windows with a CAN interface that has a test driver for it. It could test canworks' slave mode; it has no test for NMT masters or CiA 309 gateways. CiA certification of a device is a paid service.
