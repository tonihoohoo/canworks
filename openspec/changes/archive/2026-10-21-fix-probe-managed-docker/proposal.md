## Why

On a device moved from a native OpenPLC runtime to the managed Docker one, the probe showed the wrong runtime. Its SSH user cannot read the bootloader's folder (root's only) or use Docker (not in the docker group), and the old native unit was still installed, stopped. The probe took the stale native tree: the runtime row showed that tree's version, the plugin showed off (from the tree's `plugins.conf`) and the main action offered **Rebuild** for a runtime that does not run.

## What Changes

- With password-less sudo, the probe reads the runtime spec and lists the Docker containers through `sudo -n` (read-only) when it cannot read them itself.
- The managed runtime's folder or its containers win over an installed native unit that is not running. An installed native unit wins only when it runs, or when nothing else points to another runtime.
- A managed runtime whose spec cannot be read is still reported as managed Docker, with its version `null` (no rebuild offered).

## Impact

- `tools/deploy/canworks/devices/device-probe.sh`, its tests, docs/devices.md. PC tools 0.98.1.
