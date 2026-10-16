## Context

The exploration (main 46367f6) compared canworks' output with CiA 301/302/305/306/309-3. The master, slave device, simulator and 309-3 text layer are Lely's, so most standard behaviour is inherited. The faults found are in the parts canworks writes itself: the slave EDS generator, the DCF export, the configuration stamp in 0x1020, and the SYNC and TIME frames the plugin builds itself. The only file checks today are Lely's lint, which allow-lists keys but never requires one, and `eds_check.cpp`, which only needs Lely to parse the file.

## Goals / Non-Goals

**Goals:** fix the faults found; make every EDS and DCF canworks writes pass a CiA 306 check that is not Lely's; document where canworks departs from the standards on purpose.

**Non-Goals:** CiA certification, an interop test with another stack, changing the CiA 302-2 departures, stricter checks on vendor EDS files.

## Decisions

### Decimal REALs in written files, hex only inside

Lely's Python dcf-tools read REAL values only as hex bit patterns, which is why the generator writes them that way. The plugin's prepared EDS copy already rewrites decimal REALs to hex before dcfgen and its own checks (canopen-master-bringup "Prepared EDS copy"). So the generator can write decimal, and the file the plugin runs and the file the user imports elsewhere stay the same file. Apply must confirm the slave device mode reads the EDS through the same prepared copy, or that Lely's C parser reads decimal REALs; if neither, the slave loader gets the prepared copy too.

The DCF export keeps building and validating on Lely's form and converts REAL values to decimal only when writing the file. The decimal text is the shortest that reads back to the same bit pattern (Python `repr` of the float32/float64 value), so nothing is lost.

Alternative: keep hex and add a separate "export for other tools" file. Rejected, because the slave EDS spec requires the exported file to be byte-identical to the one that runs.

### Reproducible dates

CiA 306 lists `CreationDate`/`CreationTime` (`mm-dd-yyyy`, `hh:mm(AM|PM)`). Writing the current time would change the file on every run and break the byte-identical fixture tests. The description gets an optional `date` (`YYYY-MM-DD`, optionally with `HH:MM`). When it is missing the generator uses today's date at 12:00AM, and the configurator fills `date` the first time the user generates, so later runs reproduce the file. Creation and modification are the same value; `ModifiedBy` is the tool and version, as in the DCF export.

### Our own CiA 306 checker

A small Python module (`cia306.py`) with a list of rules, each with a CiA 306 or CiA 301 reference in its message. It runs on canworks' own output only, so it can be strict without rejecting vendor files. python-canopen as a second parser was considered and left out, to add no package install to CI (canopen-ci "Bounded package installs"). The rules are those listed in the proposal; each failure names the file, section and key.

The generator and the export call it before writing, as they already call Lely's lint, and write nothing when it fails. A CI test runs it over every generated slave EDS (fixtures and examples) and every DCF the existing export tests write, so the test adds seconds, not a job.

### 0x1020 ranges

CiA 301 defines 0x1020 sub 1 as days since 1984-01-01 and sub 2 as milliseconds after midnight. The stamp keeps its 64-bit FNV hash and maps it to `date = 1 + (h >> 32) % 65535` and `time = 1 + (h & 0xFFFFFFFF) % 86399999`. Both stay non-zero, the same config still gives the same values, and about 42 bits of the hash remain, enough to notice any change. The values change once with this release, so nodes with `config_check` are configured again once; the project is not in use, so no migration.

### SYNC and TIME gated on the master's NMT state

The plugin already tracks the master's own NMT state (master `state_location`). `ServiceSyncRequests` and the TIME send in the tick skip sending while that state is STOPPED; skipped PLC-cycle SYNC requests in STOPPED are not counted as skipped frames. On leaving STOPPED, TIME is sent at once (as after bus recovery) and SYNC resumes with the next request. The SYNC counter is set to 1 in the master's reset-communication handler, as Lely's own SYNC producer does on its start.

### Standards page

`docs/standards.md` is the place a user or an auditor looks for "is this conformant". It is a table per standard: what canworks does, who does it (Lely or canworks), departures and why, gaps, and how it is tested. It mentions CiA's Conformance Test Tool as the route to certification for the slave mode, without promising it.

## Risks / Trade-offs

- [Slave mode may not read decimal REALs] → apply checks it first and routes the slave EDS through the prepared copy if needed.
- [New text limits reject names users already have] → the project is not in real use; the message names the field and the limit.
- [Strict checker false positives on canworks' own fixtures] → fixing those fixtures is part of the work; the checker never runs on vendor files.
- [0x1020 values change] → one extra configuration download per node after upgrade.
