## Context

Found in the 2026-10-23 Windows check of the CODESYS import explore: virtual-plant (networks `io`, `motion`, `host`) built with `--codesys-import --codesys-new` into a new Control Win V3 x64 project. Network 1 worked; network 2 stopped when the script added `CANopen_Manager` under its CANbus. A patched copy that also checked `projects.primary.find(name, True)` built all three networks with 0 errors. The parameter dump showed the remote device heartbeat producer as parameter `0x01017000` (index << 12, a struct) on `connectors[].host_parameters`, 0 for `conveyor` and `cell`, 100 for nodes whose DCF has `ParameterValue=0x64`.

## Goals / Non-Goals

**Goals:** multi-network builds work on a real CODESYS; the configured heartbeat reaches CODESYS for every node.

**Non-Goals:** node device identity in the device repository (two nodes of one EDS share a CODESYS device id; handled in add-codesys-import), updating nodes in place (add-codesys-import).

## Decisions

- **Name check over the whole tree.** `_unique_name(parent, base)` collects the names of every object under the top-level device that holds the parent (the object right below the project) instead of the parent's children. Other top-level devices keep their own names: projects with one device per hardware variant all have a `CANbus`, so the scope is the device, not the project. Suffix stays `_2`, `_3`, ... so existing projects keep their first names.
- **Heartbeat as a plan device setting.** `plan.py` adds the heartbeat producer parameter to each node's `params` when `heartbeat_ms` > 0, by id `0x01017000` (a plain UINT in ms, "Heartbeat-Producer Time", per the SP22 dump). Setting it through the existing `apply_params` keeps the "Settings found by id" behavior: a CODESYS without it gets a report line, not a stop. Alternative considered: make the DCF always write `ParameterValue` for 0x1017. Rejected: the DCF export is shared with Lely, and the rule "a value equal to the EDS default writes nothing" is deliberate there.
- **Stand-in refuses duplicate names tree-wide** with CODESYS's message text, so the regression is caught in CI.

## Risks / Trade-offs

- [Element name of the heartbeat struct differs between CODESYS versions] → missing element gives the usual "not set" report line; task 1.1 reads it from the SP22 dump.
- [A user-made object already named `CANopen_Manager` elsewhere] → the new one becomes `CANopen_Manager_2`; harmless, the report names it.
