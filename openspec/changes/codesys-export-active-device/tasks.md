## 1. Script

- [ ] 1.1 `import_canworks.py`: find the active application's device by walking `parent`; `choose_plc` order named > active > only device > stop with the device list and how to set one
- [ ] 1.2 Report line with the reason; warning when a named device is not the active application's device
- [ ] 1.3 Warning when another top-level device has a CANopen Manager on the same network number

## 2. Stand-in API and tests

- [ ] 2.1 `tests/fake_codesys.py`: `parent` on objects, settable active application per project (on any device, or none)
- [ ] 2.2 Tests: second device active; named differs from active; several and none active; nested active device; re-run after switching; single device without application

## 3. Check in CODESYS

- [ ] 3.1 On the Windows PC's CODESYS: project with two devices, run in the IDE and headless with each one active; the bus lands on the active one and the report says so

## 4. Docs and release

- [ ] 4.1 `docs/codesys.md` (choosing the device), `docs/deploy.md`, CLI help of `--codesys-plc`, export README.txt and the configurator's export banner
- [ ] 4.2 README.md, PC tools version bump
