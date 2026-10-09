## REMOVED Requirements

### Requirement: Taking over a local runtime from the earlier name
**Reason**: The project is not in use anywhere yet, so the rename to canworks is a clean cut without compatibility code. No local runtime from tools 0.30.x needs to be carried over.
**Migration**: Remove an old local runtime with `docker rm -f openplc-canopen-runtime` (and `docker volume rm openplc-canopen-runtime-data`), then run `canworks-sim-runtime start`.

### Requirement: Earlier command name
**Reason**: Clean cut: the PC tools install only the canworks command names, with no aliases.
**Migration**: Use `canworks-sim-runtime` in scripts.
