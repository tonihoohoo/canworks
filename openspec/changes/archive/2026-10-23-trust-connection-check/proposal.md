## Why

The modbus-connections bench runs on the Mac and on Windows both hit the same gap. A config with an OpenPLC connection and a truST connection passes the check: `/api/check` and `canworks-deploy --check` report nothing, and Problems is empty. Yet the truST connection's Download is refused, for two reasons:

- the map is too big for truST's one Modbus request each way (260 input and 95 holding registers against at most 125 and 123), because the OpenPLC connection turned the mailboxes on;
- the watchdog is OpenPLC's 50 ms, and a truST scan with the library takes about 100–125 ms, so truST needs 500 ms or more.

The user learns this only when pressing Download. The connection row says nothing either.

## What Changes

- Problems shows a warning for each reason a truST or Other PLC connection's Download would be refused: no PLC link, the map is too big for truST, or the watchdog is too short for truST. The warnings are the same texts the export gives. They show as soon as the connection is in the config, before any Download.
  - Each warning points at the field to change: the connection row for the PLC link, `bridge.mailboxes` for the map size, `bridge.watchdog_ms` for the watchdog.
- Two Problems fix buttons, each one undo step:
  - **Set the watchdog to 500 ms** sets `bridge.watchdog_ms` to 500.
  - **Trim the mailboxes for truST** sets the mailboxes to one request mailbox and nothing else (`"requests": 1, "receive": false, "network_info": false, "cyclic_jobs": 0`) and repacks. When the config also has an OpenPLC connection, the button's title says that OpenPLC's receive, network info and cyclic blocks stop working too.
- The connection row's state shows "Cannot download" with the first reason while one of these warnings stands, in place of "Not downloaded yet" or "Out of date".
- `canworks-deploy --check` prints the same warnings.
- Unchanged: the export's own refusal stays, and a config without truST or Other PLC connections gets no new warnings.

## Capabilities

### Modified Capabilities
- `modbus-connections`: connections that cannot be downloaded are warned about in Problems, with fixes.

## Impact

- `tools/deploy/canworks/connections.py` (`problems`), `static/app.js` (`bridgeProblemFixes`), `static/bridge.js` (row state), `canworks/cli.py` check output.
- Tests in `tests/test_configurator_bridge.py`, `tests/test_configurator_bridge_page.py` and the CLI check tests.
- docs/modbus-bridge.md (Connections) and docs/plcopen.md (truST): one sentence each.
- `mailboxes-on-demand` (proposed) later turns the mailboxes off by default, which makes the map-size warning rarer but not gone.
- Tools minor version bump; tests run in the existing shards, no new CI job.
