## 1. Probe

- [x] 1.1 device-probe.sh: on a docker-managed runtime with the plugin library and no `/opt/canworks/lib/plugins-line`, report `enabled: false`; an existing but unreadable file stays `null`
- [x] 1.2 Probe test on a fake device: fresh managed install (no plugins-line) gives `enabled: false`; with the recorded line, its own value; native unchanged
- [x] 1.3 Plan test: the row reads "… · waiting for an upload" for that probe

## 2. Docs and release

- [x] 2.1 docs/devices.md: the plugin row says "waiting for an upload" until the first upload on a managed Docker runtime
- [x] 2.2 PC tools patch version; doc goldens

## 3. Hardware

- [ ] 3.1 Pi after a plugin reinstall with no recorded line (or the line moved aside): the row reads "waiting for an upload"; after the upload, "on"
