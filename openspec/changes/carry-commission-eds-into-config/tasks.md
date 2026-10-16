## 1. Server

- [ ] 1.1 `/api/open`: optional `carry_eds`; read the bytes from the current session before `open()` (pending name, or an absolute path under the Commission folder or the EDS library, normcase compared); lint them with the request's `eds_lint`; refuse with 403/422 before switching folders
- [ ] 1.2 After the folder opens, `import_eds(basename, data, "keep_both", eds_lint)` and return it as `carried_eds`
- [ ] 1.3 `_use_eds()`: accept a bare name in `s.pending` (returned as it is); compare roots with `os.path.normcase`
- [ ] 1.4 `params.py` node context: compare roots with `os.path.normcase`

## 2. Page

- [ ] 2.1 `addScannedNode()`: take an import result as a source next to `match` and `file`
- [ ] 2.2 `addToConfig()`: send `carry_eds` with `d.eds_path` when the device has an EDS; add the node with `carried_eds`; a refusal keeps the page in Commission with the banner naming the EDS

## 3. Tests and version

- [ ] 3.1 API tests: carry a pending name, a Commission folder file and a library file; an outside path is refused and the session is still in Commission
- [ ] 3.2 Page test: Add node from EDS… (node 23) then Add to a config… adds node 23 with that EDS, no file asked; a library scan match carries too
- [ ] 3.3 Tools version 0.74.0 → 0.74.1

## 4. Hardware

- [ ] 4.1 On the Windows PC with the gs_usb adapter: Commission a device, Add node from EDS… for the bench node, Add to a config… into a standalone folder; the node is added with its EDS and the config saves
