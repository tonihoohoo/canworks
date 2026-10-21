## 0. Check

- [ ] 0.1 On the PC with the display project (Toni): confirm the vendor CANbus is type 15 and that a refused `add` leaves no child (the report from 2026-10-21 already shows the refusal message)

## 1. Script

- [ ] 1.1 `import_canworks.py`: CANbus candidate list (same-interface buses in the project, other project buses, installed, stock last) and first-accepted add; refusals collected
- [ ] 1.2 Manager identification from a sibling bus with the same identification, else today's rule
- [ ] 1.3 Report: created line names the CANbus id/version and where it came from; refusal error lists tried CANbus devices
- [ ] 1.4 `warn_other_devices`: one warning per network with the device names (first 5, then "and N more")

## 2. Stand-in API and tests

- [ ] 2.1 `tests/fake_codesys.py`: an interface that accepts only a given CANbus id; repository with several type-15 ids
- [ ] 2.2 Tests: device without bus whose interface accepts only the vendor CANbus used by another device (adds it, manager under it, node added); vendor CANbus only installed, not in project; nothing accepted (error lists tried); stock still used on a plain PLC; one warning for many other devices

## 3. Configurator

- [ ] 3.1 Build dialog's first sentence names the device from the report's `device` line; test in the CODESYS page tests

## 4. Check in CODESYS

- [ ] 4.1 Toni, on the display project: ExampleApp without a bus, run the script; the vendor CANbus, manager and node 2 are added and the project builds

## 5. Docs and release

- [ ] 5.1 `docs/codesys.md` (which CANbus a new bus gets), README.md, PC tools version bump
