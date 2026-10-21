## 1. Page

- [x] 1.1 `importReport(res, { slave })`: lead sentence with the file name, "kept as imported" and the reader for the project target (design table); one list item per correction kind with its count, singular or plural; fallback to the correction's own text for an unknown kind
- [x] 1.2 CODESYS target, node import: leave out the REAL line; no block (and the readable line when nothing else applies) when REAL was the only correction
- [x] 1.3 Pass `slave: true` from the slave EDS import; Add node from EDS… and Commission's add node pass nothing

## 2. Checks

- [x] 2.0 `make_fixtures.py`: add `nodeid-suffix.eds` (two values written `0x200+$NODEID`, one `0x180+$NODEID`) and its entry in `expected.json`
- [x] 2.1 e2e: `$NODEID` fixture under OpenPLC shows the file name, "kept as imported", "The OpenPLC plugin reads a corrected copy" and "N values written"; one entry reads "1 value ... is read as"
- [x] 2.2 e2e: the same file under a CODESYS target says "The DCFs exported to CODESYS are built from a corrected copy"; a REAL-only file shows no correction block
- [x] 2.3 Existing octet-string check still finds `[2051] DefaultValue was "----"`
- [x] 2.4 docs/configurator.md: what the banner says about corrections, per target; PC tools patch version bump (0.94.2)

## 3. Hardware

None: page text only, no PLC or bus behaviour changes.
