## Context

`ui-shell-and-connection` made one connection for every view and the connection bar under the header, but kept three extra entry points: the Nodes table's inline connect form with recent connections (`commission-workspace`), a Connect… button in each view's not-connected note (Trace, Simulation), and the Simulation view's own Runtime / Standalone simulator choice with the simulator's address, token and Connect. On a real screen with nothing connected, Simulation shows two Connect buttons and four "not connected" texts.

## Goals / Non-Goals

**Goals:** one place to connect and disconnect, in the same spot on every page; no page repeats the bar's connection state; nothing that can be done today is lost (recent connections, standalone simulator).

**Non-Goals:** changing how a connection is made (bit rate check, token, discovery, paths); several connections at once; changing what the Simulation view does once connected.

## Decisions

1. **The connection bar is the one place.** It is already on every Commission page, and its Connect… already opens the shared panel. Alternatives: the Nodes table (only one tab, not visible from Trace or Simulation) or a header button (would split state and action). The bar keeps state and action together.

2. **No button in empty states, only a pointer in words.** A second button that opens the same panel is exactly what made the screen confusing. Each page says what it needs a connection for and "Connect… above". The bar sits directly above every page's content, so the distance is short. Keyboard users reach the bar's Connect… as the first control after the tabs.

3. **Recent connections move into the panel, listed first.** They keep the one-click reconnect; reaching them now takes Connect… then the recent entry (two clicks instead of one). Focus lands on the first recent entry when there is one, so Connect…, Enter reconnects to the last target. We judged a bar button per recent connection too crowded.

4. **Standalone simulator becomes a panel target, shown in the bar.** Today it is a hidden second connection that only the Simulation view knows about. As a target in the panel (Runtime default, Standalone simulator second; only with a config, since Commission a device has no Simulation tab), it is visible in the bar and disconnected from the same place. The page holds one connection at a time: connecting to the simulator closes a runtime connection and the other way round. Nodes, Trace recording and the PDO test say they need a runtime on a simulator connection. Keeping both at once was considered; nobody needs the Nodes table of a runtime and a separate simulator's devices at the same time, and two simultaneous connections would bring back two places to look.

   The page side: `connection.js` gets a third kind next to adapter and runtime (`S.simOn`, with `connSimOn()`); `connBar`, `connDisconnect` and `connEnsure` learn it, and `connIsOn()` keeps meaning a bus connection (runtime or adapter). The settings stay in `online.json` (`sim_target`, `sim_address`, `sim_token`) through `/api/sim/settings`, so the server is unchanged; the page's `api()` adds `target: "runtime"` to every `/api/sim/*` request unless the simulator is the connection, so a saved `sim_target` never sends requests to a simulator the bar does not show. `simCanConnect` follows the bar's kind instead of `SIM.settings.target`. Switching from a runtime to the simulator is Disconnect, then Connect….

5. **Bar in Configure on Trace and Simulation.** In Configure the bar shows only while connected. Without a change, removing the views' Connect buttons would leave no way to connect there. Showing the bar on those two tool tabs (connected or not) keeps the rule simple: where a connection is used, the bar is there.

6. **Simulation shows only simulation facts.** The `#sim-conn` line repeats the bar ("Not connected.", "Connected to …"). It goes; what stays are messages the bar cannot know: the runtime simulates nothing, the view is read-only and why. The line under the heading stays, shown only once connected, with the simulation facts alone (simulated or real network, device count, changes allowed); its "Connected to …" prefix goes. A standalone simulator's connection problem shows in the bar.

## Risks / Trade-offs

- [Reconnect takes one more click] → the panel focuses the most recent entry, so it is Connect… then Enter.
- [Users who used the Nodes form may look for it] → the Nodes empty state names Connect… above; the bar's button is the primary style.
- [Page tests use the removed selectors] → move them to the bar and panel in the same PR; add a test that counts Connect buttons per page.

## Migration Plan

UI only. `online.json` is read as today; a saved `sim_target: simulator` preselects Standalone simulator in the panel. Not in real use, so no compatibility path for the removed form.
