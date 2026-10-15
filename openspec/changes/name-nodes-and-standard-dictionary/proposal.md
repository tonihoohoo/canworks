## Why

On the Nodes table the **Device** column stays empty for every node that was only heard on the bus. The device's name, vendor and product are read only by **Scan the bus**, so a user who connects and sees nodes 23, 32 and 49 by their heartbeats has nothing but numbers to tell them apart, and has to know to run a scan (which on a busy bus first asks to run anyway) just to learn what they are.

Opening such a node is worse. Without an EDS the **Object dictionary** tab says the node has no EDS, and the SDO panel's object picker says "No EDS objects (type index and subindex)". Yet every CANopen device has the CiA 301 communication objects (device type, error register, identity, heartbeat, PDO settings and so on), and a device whose 0x1000 says CiA 401 or CiA 402 has that profile's standard objects too. The user has to remember indexes like 0x1017 by heart to do the most basic checks on a device they have no EDS for.

## What Changes

- **Device name for every node, without a scan.** When a node is first heard (heartbeat, boot-up or EMCY), the configurator reads its identity in the background with a few SDO reads: 0x1008 manufacturer device name, 0x1018 identity (vendor, product, revision, serial), 0x1000 device type, and 0x1009/0x100A hardware and software version. Reads go one node at a time, once per node per connection, again after the node boots up, and are skipped for a node in STOPPED (it does not answer SDO) until it leaves that state. A scan fills the same record, so nothing is read twice.
- **What the Device column shows.** The device's own name (0x1008) in full. If the device has no 0x1008, the product name of a matching EDS in the library or project; else the device profile from 0x1000 ("CiA 401 I/O device", "CiA 402 drive"); else vendor and product numbers. Vendor, product and profile follow in muted text. While reading the cell says "Reading…", and a node that does not answer SDO says so ("no SDO answer") instead of staying blank. With a config, the Name column keeps the configured name and adds the device's own name under it in muted text.
- **Name everywhere the node appears.** The node's heading, its tree entry in Commission a device, and the Status tab (a Device line with name, vendor, product, revision, serial, hardware and software version and profile). **Add to a config…** suggests the device's name as the new node's name.
- **Standard object dictionary without an EDS.** A node with no EDS (configured, picked or matched) gets a built-in standard dictionary: the CiA 301 communication objects, plus the CiA 401 or CiA 402 standard objects when 0x1000 names that profile. The **Object dictionary** tab shows it with the same tree, reading, watch, formats, notes and editing as an EDS, with a line at the top saying these are standard objects, the device may lack some of them, and offering the EDS pick (library matches or **Pick EDS file…**) for the device's own objects. The SDO panel's object picker lists the same objects.
- **Objects the device lacks.** An entry whose read is refused with "object does not exist" (0x06020000) or "sub-index does not exist" (0x06090011) is marked "not on this device"; after **Read all**, those are hidden by default, with a filter to show them again. Arrays such as 0x1003 error history and the PDO mapping objects show as many sub-entries as their sub-index 0 says once it is read. The standard dictionary lists RPDO and TPDO 1-4; **Read all** also looks for PDO 5 onwards until the first one that does not exist.
- **Parameters stay EDS-only.** Back up, Compare, Restore and Store need the device's own EDS; without one the **Parameters** tab says so and offers the same EDS pick, instead of the current "has no EDS here" line.
- Configurator tools version 0.61.x -> 0.62.0 (minor: new behaviour on the Nodes table and node tabs).

No config, contract, plugin or deploy change. Identity reads use the existing manual SDO read on both an adapter and a runtime connection.

## Default picked

- **Automatic, no setting.** Identity reads are a handful of SDO uploads per node, the same as a manual read, which needs no force and no Allow changes. They are not offered as an option to turn off; a scan already sends far more.
- **Built-in profiles: CiA 301, 401 and 402.** These are the profiles the toolkit already has built-in notes for. A device whose 0x1000 names another profile gets the CiA 301 objects and a line saying that profile's objects are not built in.
- **No vendor name list.** Vendor IDs are shown as numbers, with the vendor name from a matching EDS when there is one; the toolkit does not ship a vendor ID registry.

## Out of scope

- Uploading the device's own EDS from 0x1021 (store EDS) or DOMAIN objects.
- Back up and compare against the standard dictionary.
- The EDS library folder row on the Nodes tab (change `browse-eds-library-folder`) and the trace view (change `fix-trace-pause-and-about`).

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-configurator`: new requirements for reading the identity of heard nodes, device names in the Nodes table and elsewhere, the standard object dictionary, objects a device lacks, Read all on it and the Parameters tab without an EDS; modified "Object dictionary view", "Manual SDO and NMT in the online view", "Filters in the object dictionary view" and "Node Status tab".

## Impact

- `tools/deploy/canworks/builtin_od/` (new): `cia301.eds`, `cia401.eds`, `cia402.eds`, standard objects written as EDS sections and parsed with the existing EDS reader.
- `tools/deploy/canworks/configurator/server.py` and `params.py`: `/api/online/identify` (identity of one node through the connection's manual SDO read, with EDS library matches); `od_entries` and `od_read` accept a `standard` source with the device type.
- `tools/deploy/canworks/configurator/static/commission.js`, `app.js` (`nodeSource`, `odPanel`, `sdoPanel`, `paramsPanel`, node heading, Status tab), `nodes.js` (with-config table), `tree.js` (Commission a device labels), `style.css`.
- Page and unit tests; `docs/configurator.md`; README (Nodes table and object dictionary paragraphs).
