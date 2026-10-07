## 1. Deploy tool

- [x] 1.1 `clash.bundle_uses` skips a `conf/*.json` whose content is empty or whitespace only, with no problem reported
- [x] 1.2 Unit test: empty and whitespace-only `conf/ethercat.json` give no warning; `{` still gives the "not readable JSON" warning
- [x] 1.3 Configurator `scan.scan` skips empty or whitespace-only `.json` files the same way; unit test
- [x] 1.4 Bump the deploy tool version to the next free patch version (0.30.1)
- [x] 1.5 docs/deploy.md says empty configs are skipped
