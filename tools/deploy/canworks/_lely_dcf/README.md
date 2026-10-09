# Vendored Lely `dcf` package

`__init__.py`, `device.py`, `lint.py`, `parse.py` and `print.py` are copied
unchanged from `python/dcf-tools/dcf/` of
[lely-core](https://gitlab.com/lely_industries/lely-core) at the commit in
`VERSION` (Apache License 2.0, see `LICENSE` and `NOTICE`). It is the same
commit `scripts/build-lely.sh` builds on the PLC, so the configurator, the
deploy tool and the plugin lint EDS files with the same code
(`canworks.edslint`).

`dcfgen_cli.py` is `python/dcf-tools/dcfgen/cli.py` from the same commit,
also unchanged: the DCF export (`canworks.dcfexport`) builds
each node's configuration download with dcfgen's own code, as the plugin's
dcfgen run on the PLC does. It imports `em`, `yaml` and `pkg_resources`,
which only its master DCF output uses; `dcfexport` loads it with stand-ins
for those, and with this package as its `dcf`.

To update: change the ref in `scripts/build-lely.sh` and `scripts/dev-setup.sh`,
copy the six files from that commit, write its hash to `VERSION`, and run
`scripts/check-lely-dcf.sh` and the `edslint` and `dcfexport` tests (they pin
Lely's lint messages and the download lists).
