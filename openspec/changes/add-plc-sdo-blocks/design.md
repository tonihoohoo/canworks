# Design

## Context

- A native plugin gets only `plugin_runtime_args_t` from the runtime (I/O image, debug variables, logging). The runtime cannot route a program call to a plugin, and it loads plugins with `dlopen(path, RTLD_LOCAL | RTLD_NOW)`, so the program's `.so` cannot link against plugin symbols.
- OpenPLC Editor 4.3.x builds C/C++ function blocks for Runtime v4 into the program `.so` (`c_blocks_code.cpp`), and since 4.3.0 a user `.stlib` library may ship them: their source travels in the archive and is grafted into each project that enables the library. A C++ block gets a `<NAME>_VARS` struct with pointers to every variable it declares (inputs, outputs, in-outs, locals), so each instance has its own state. STRING pins are `IECStringVar<254>`, one-dimensional arrays bind as pointers.
- The plugin already runs SDO transfers for any node ID on the Lely loop for the diagnostics channel (`Network::StartManual`, foreign node IDs included) and for SDO variables (one transfer per node, boot first).
- Earlier research: `plc-sdo-nmt-options.md` option B. Option E (config-based `sdo_variables`, `nmt_command_location`) shipped; this change adds B for the SDO half only.

## Goals / Non-Goals

**Goals:** any node, object and size from the program while it runs; strings and byte blocks; blocks that a user can drop in without reading a manual (one pin layout, block chosen by data kind, size from the EDS); no effect on scan timing; no stale answers after a stop.

**Non-goals:** NMT and node state blocks (the config route covers them; a `CO_NMT` block can be added to the same library later); SDO server or block transfer tuning; more than 1024 bytes per transfer; PLC targets other than Runtime v4 on Linux; any change to `sdo_variables`.

## Decisions

### 1. Blocks find the plugin by SONAME with `RTLD_NOLOAD`
The plugin `.so` gets `SONAME libcanopen_plugin.so`. glibc matches `dlopen("libcanopen_plugin.so", RTLD_NOW | RTLD_NOLOAD)` against the SONAME of objects already loaded, so the block gets a handle to the runtime's copy under any prefix (stock, `--prefix`, Docker) and never loads a second one. `dlsym(handle, "canopen_plc_api")` gives the entry point. Fallback if the spike shows the SONAME match does not work: walk `dl_iterate_phdr` for a path ending in `/libcanopen_plugin.so` and `dlopen` that path with `RTLD_NOLOAD`.
The handle is looked up on the first rising edge and cached for the process (plugins are unloaded only when the runtime exits). A failed lookup is retried on the next edge, so a program that starts before CANopen is up recovers.

Alternatives: a fixed path (breaks `--prefix`); an environment variable set by the plugin (the program `.so` may be loaded first); located-variable mailbox (option A, kept as the fallback if the spike fails).

### 2. One versioned C table
`extern "C" const canopen_plc_api_v1* canopen_plc_api(uint32_t version)` returns the table for `version` or NULL (and logs once which version was asked for and which are offered). v1:
```c
typedef struct {
  uint32_t size;  /* sizeof, for later growth */
  /* Starts a transfer. Returns a handle > 0, or 0 with *error set (ERROR_ID). */
  uint32_t (*start)(const canopen_plc_request* req, uint16_t* error);
  /* Copies the result when ended: 0 busy, 1 done, 2 error. Frees the slot when it returns 1 or 2. */
  int (*poll)(uint32_t handle, canopen_plc_result* res, uint8_t* data, uint32_t cap);
} canopen_plc_api_v1;
```
`canopen_plc_request` holds network (0 only for now), node, index, subindex, read/write, timeout ms, size (0 = from EDS), a `uint8_t` data pointer and length for writes (copied into the slot in `start`), and the data kind (int, real, string, bytes) so the plugin can resolve size 0 from the EDS type. `canopen_plc_result` holds error ID, abort code and reply size. The handle packs a slot number and a generation, so a handle from before a stop never matches a new slot.

### 3. Fixed slot table, Lely loop does the work
64 slots, each with a 1024-byte buffer, allocated when CANopen starts. `start` takes a mutex, finds a free slot, copies the request, bumps the generation, queues the slot on its node and writes the Lely loop's wake eventfd (the same pattern as `DiagHub`). `poll` takes the mutex and copies out. Neither allocates or logs; logging happens on the Lely loop. The loop's `ServiceRequests` gains a program queue per node: it starts the next program transfer when the node is available and no other transfer of that node runs, alternating with due SDO variable transfers. Unconfigured node IDs go straight to the default Client-SDO, as manual SDOs do (`foreign_sdo_` bookkeeping reused). Size 0 is resolved on the loop from the loaded EDS before sending.
A slot whose result is not polled within 10 s of the end is freed; the instance's later `poll` sees a generation mismatch and gets ERROR_ID 8. `stop_loop` marks every slot cancelled and bumps the run generation.

### 4. Blocks are thin, the shared code is one header
Each block's C++ body is a few lines: edge detection, latching inputs, `start`, `poll`, mapping the result into its pins. Shared code (lookup, encode/decode of LWORD, REAL, STRING) lives in a header that each block source carries inline behind an include guard, because the editor grafts each block's file into one `c_blocks_code.cpp` and offers no other place for shared code. The editor binds each pin name with a `#define`, so the shared code uses no identifier that is also a pin name (`DATA`, `SIZE`, `VALUE`, `BUFFER`, `ERROR`...) and does not `#include <dlfcn.h>` after the defines; it declares `dlopen`/`dlsym` itself. The spike confirms this works in the editor's build.

### 5. Data kinds instead of one generic block
CiA 405's `SDO_READ` takes a pointer and length, which ST users find awkward and which the editor's C++ pins cannot express. Four kinds cover real objects: integers and bit strings (an `LWORD`, little-endian, zero-extended; ST's `LWORD_TO_INT` and friends truncate, which gives the right signed value), REAL (needs a bit cast ST does not have), STRING (the editor's 254-character string), bytes (a 1024-byte array for OCTET_STRING and DOMAIN). 1024 bytes keeps an instance small and covers parameter blocks; firmware download stays in the configurator.

### 6. Size from the EDS
For writes, `SIZE := 0` (the default) asks the plugin to take the size from the configured node's EDS, so the common call is node, object, value. Reads need no size. A node not in the configuration needs an explicit size.

### 7. Library build and delivery
`library/openplc_canopen/` holds the editor library project (`library.json`, the eight block sources, the shared header). The `.stlib` is built by the editor's library build. Whether CI can run that build headless (the strucpp compiler from the editor's package) is a spike question; if not, the `.stlib` is built in the editor and committed next to its sources with a CI check that its block sources match the folder. The deploy wheel carries the file; the release workflow attaches it.

### 8. Several CAN networks (parallel change)
The "several CAN networks" change would make the node ID ambiguous. The C request carries a network number from v1 (only 0 accepted now); that change adds a `NETWORK : USINT` input (0 = first network) to the blocks, which ST programs that do not set it keep working with, and accepts other numbers in the plugin. No API version bump needed. Whichever change lands second carries that pin.

## Risks / Trade-offs

- [Library C++ blocks cannot reach the plugin in the editor's build] -> the bench spike is task 1; on failure the change stops and option A (located-variable mailbox) is proposed instead.
- [The editor changes how it grafts library C++ blocks] -> the blocks use only the documented `setup()`/`loop()` form and pins; the version is pinned to 4.3.2 in docs and the spike, and the host test compiles the sources the way 4.3.2 does.
- [A program floods the bus with SDOs] -> one transfer per node and 64 slots bound it; SDO variables still get turns.
- [Program writes fight the plugin's own configuration] -> allowed with a warning, as for SDO variables.
- [The user forgets to install the library] -> the editor reports the unknown block; `--sdo-blocks` and the docs say how to install it.

## Open Questions

- Does the editor's C++ bridge support an `ARRAY[0..1023] OF BYTE` in-out pin in a library block? If not, `BUFFER` becomes an output (read) and input (write), copied each call.
- Can the `.stlib` be built in CI without the editor GUI?
