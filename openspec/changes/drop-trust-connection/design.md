## Context

The `trust` target was added with the PLCopen export (#259) and became a connection kind with modbus-connections (#264); trust-connection-check (#270) and mailboxes-on-demand (#271) added the Problems fixes and blocks limit. All of it exists because truST's `modbus-tcp` driver only fills the located `%I`/`%Q` byte image with one request each way, its PLCopen import drops AT addresses, and its scan takes about 100-125 ms.

## Decisions

**Clean cut, no conversion.** A config with `"kind": "trust"` fails the check with the existing unknown-kind error ("field 'kind' must be one of ..."), which lists the remaining kinds. No auto-conversion to `plc`: nothing is in real use. The configurator shows the error in Problems like any other.

**`--for trust` is an argparse choice error.** It goes from `choices` instead of getting its own refusal text: the usage line lists `generic` and `codesys`.

**Keep the truST compile check, on the generic export.** It is the only CI step that runs a real strict IEC compiler over the PLCopen XML (STruC++ only builds the library sources). Measured in the explore: the generic export with all mailboxes and the whole library, plus the CI test `main` that calls `CO_SDO_READ`, `CAN_RECEIVE`, `CO_SDO_READ_STRING` and `J1939_DM_READ`, imports with verdict `full` and builds. The test no longer copies `canworks_io.st`. `fetch-trust.sh`, the cache key and the path filter stay as they are, so CI time does not move.

**The `trust` dialect goes.** `plcopen.DIALECTS` becomes `codesys` and `generic`; the module docstring keeps the note that the generic dialect's STRUCT form exists because some importers cannot assign to an array element in a namespace, without naming a target.

**`inputs_on_loss` kinds.** `openplcmodbus.inputs_on_loss(cfg, kinds)` is called with `("plc",)` only for the generic export.

**Writers and the PLC link.** The rule "the PLC is the OpenPLC connection, else the first Other PLC that writes" keeps working with the kind list reduced to `plc`.

**Docs.** truST disappears from user docs and README. `docs/plcopen.md` keeps one table row per target (generic) and loses the truST section; the "what works without mailboxes" facts it held for truST are already in the Function blocks section docs. `docs/development.md` says CI imports and builds the generic export with a pinned truST release as a strict compiler.

## Risks

- A truST user now wires truST's driver, the byte image and the copy loops by hand and gets no warning about the one-request limit or the watchdog. Accepted: truST is not a supported target any more.
- The truST compile check depends on a third-party pre-1.0 binary; if a future pin breaks the generic import, the check can be dropped then without touching the product.
