## Context

`install-stock.sh` runs the same way every time. In native mode it builds Lely (skipped when `<prefix>/lely/.ref` matches), pip-installs `tools/deploy` and the editor hook, builds the plugin and the simulator in a fresh temp dir, rewrites the `canworks` line in `plugins.conf` as disabled, and asks for a runtime restart. In Docker mode it does the same build inside the runtime image in a one-shot container, updates the bootloader spec and recreates the runtime container, which leaves the PLC without a program. It already records `<prefix>/VERSION`, `<prefix>/lib/runtime-commit` (native) and `<prefix>/lib/runtime-version` (Docker: runtime version, image, image id).

## Goals / Non-Goals

**Goals:** a re-run with nothing new changes nothing that affects the PLC and finishes in seconds; `--force` keeps today's behaviour; options that only touch the host (link, discovery, J1939 module) still apply.

**Non-Goals:** skipping inside `install-runtime.sh` before the download (the source download is small, and only `install-stock.sh` knows the runtime); `install-bridge.sh`; partial rebuilds (for example only the editor hook).

## Decisions

**One stamp file, compared whole.** (`editor_hook` too, because a native run with `--no-editor-hook` removes the hook.) At the end of a successful install (after the plugin, the hook and, in Docker mode, the spec entries), write `<prefix>/lib/install-stamp`:

```
version=0.112.0
protocols=canopen,j1939
editor_hook=1
runtime=<native: runtime git commit | docker: runtime image id>
```

A re-run computes the same three lines before doing anything that changes the device and skips when they are equal and the installed pieces are still there: the plugin library, and in Docker mode both spec entries, in native mode a `canworks` line in `plugins.conf` (enabled or not). Comparing a whole file keeps the rule simple and lets later changes add a line (a new line means a mismatch, so the first run after the upgrade installs fully). *Alternative:* compare `VERSION` and `runtime-version` separately. Rejected: protocols are not recorded anywhere today, and two files written at different points can disagree after an interrupted run.

**Write the stamp last.** An interrupted or failed install leaves the old stamp or none, so the next run installs fully. The stamp is removed at the start of a full install, for the same reason.

**What still runs on a skip.** `setup_j1939_module` (idempotent modprobe and modules-load file) and `setup_remote_access` (link and discovery, which never touch the PLC). Step lines count only these steps, so a skip prints `::canworks-step 1/1 Setting up discovery and the remote link`, or no step line when neither is asked for. The skip line is: `canworks 0.112.0 (CANopen and J1939) is already installed for this runtime; nothing to rebuild, the PLC keeps running. --force installs it again.`

**Never skip an unknown build.** A version of `unknown`, or one ending in `-dirty` (a checkout with local edits), always installs fully, because the same string can stand for different code.

**Docker runtime identity is the image id.** The version tag can be re-pushed. The image id from `docker image inspect` of the spec's image is what the build ran in, and it is already written to `runtime-version`.

**`--force`.** `install-stock.sh --force` skips the comparison. `install-runtime.sh` and `.ps1` already pass unknown options through, so they only get a help line. The Devices page offers an install only when the version or the runtime differs, so it needs no `--force`.

## Risks / Trade-offs

- [A broken install with an intact stamp (a file deleted by hand) is skipped] → the check also requires the plugin library and the runtime entries; anything else is what `--force` is for, and the skip line names it.
- [Changes to install-time options other than protocols (for example `--prefix`) are not in the stamp] → the prefix is where the stamp lives, so a new prefix has no stamp and installs fully.
- [The Devices page job view expects at least one step line] → task to check it ends a run with zero or one step as done.
