## 1. Tabs per workspace

- [x] 1.1 Configure: Network, Variable declarations (OpenPLC), Simulation file; Commission: Nodes, Simulation (live), Trace, Frame lab; links switch workspace
- [x] 1.2 Split the Simulation view into Simulation file (Configure) and live Simulation (Commission) with the "Edit the simulation file" link
- [x] 1.3 Node tab renamed Simulated device with the pointer to Commission → Simulation

## 2. One picker and the Project page

- [x] 2.1 Connection bar network picker shown in Commission while unconnected (config networks); remove the tab-row chips and Trace's own Network select
- [x] 2.2 Project tree entry with Project target and Online access; remove the target field from Bus pages and the Modbus bridge page; header badge opens Project

## 3. Connect

- [x] 3.1 Connect panel host combobox (found, remembered, local, typed); "Looking for runtimes…"
- [x] 3.2 Token field inside the panel for Runtime and Adapter on another machine; remove the token dialog
- [x] 3.3 Trace Start while not connected opens the panel and starts after connecting; replace every "Online view" text (server.py, shell.js, links.js)

## 4. Checks and docs

- [x] 4.1 Page tests: tabs per workspace, cross-workspace links, one network control on Trace, Project page, Start opens panel then records, inline token accepted and refused; update tests that open Trace or Simulation in Configure
- [x] 4.2 README and docs/configurator.md (tabs, Project page, connect panel); PC tools minor version bump
