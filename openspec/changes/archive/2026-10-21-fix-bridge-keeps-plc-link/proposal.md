## Why

The Mac hardware check of a bridge install on a PLC device (device-install 6.3) passed, but the **Remote link** option was on by default. With it on, the job runs `install-link.sh --config /etc/canworks-bridge/<instance>/canworks.json`. That repoints the device's remote link, which served the PLC's config, at the bridge, and the PLC loses its remote access.

## What Changes

- `install-bridge.sh --with-link NAME` skips the link and says so when the device's remote link serves another config. This uses the same check `--uninstall` already uses.
- The probe reports the config the link serves (`link_config`). For a bridge install where the link serves another config, the plan marks it as kept: the page greys the option with a hint, and the configurator does not pass `--with-link`.
- The release-mode header of `install-bridge.sh --uninstall` says "Uninstalling" instead of "Installing".

## Impact

`scripts/install-bridge.sh`, `device-probe.sh`, `plan.py`, `service.py`, `devices.js`, tests, docs. PC tools 0.98.4.
