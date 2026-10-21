## Why

In the hardware check of a fresh install (device-install 6.4), the Devices page's plugin row read "0.98.3 · built for v4.3.1" right after **Install OpenPLC Runtime and canworks**. It said neither on nor off, although the done text says canworks switches on only with the next upload.

On the managed Docker runtime, the probe reads the plugin's state from `/opt/canworks/lib/plugins-line`. That is the line the editor hook records after each upload. Before the first upload the file does not exist, so the state is unknown (`null`) and the row leaves it out. Meanwhile the hook has already put a **disabled** `canworks` line into the container's `plugins.conf` (`docker_mode.at_start`: "added a disabled canworks line (no upload has set it yet)"). So the plugin is known to be off.

## What Changes

- On a managed Docker runtime with the plugin installed and no `plugins-line` file, the probe reports the plugin as not enabled. The row then reads "… · waiting for an upload", matching the done text and the hook's behaviour.
- A `plugins-line` that exists but cannot be read stays unknown, as today.
- Native runtimes are unchanged: they read `plugins.conf` directly.

## Capabilities

### Modified Capabilities

- `device-install`: Device probe. The plugin's state before the first upload on a managed Docker runtime.

## Impact

- `tools/deploy/canworks/devices/device-probe.sh`, its probe test, and a plan test for the row text.
- PC tools patch release.
- No change to the editor hook, the install scripts or the runtime.
