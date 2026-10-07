## Context

The local simulator runtime (canopen-local-runtime) shipped in 0.30.0 under the name `openplc-canopen-runtime` for the image, the command, the container and the volume (`openplc-canopen-runtime-data`). The only known installs are the owner's own Mac checks, but released tools 0.30.0 and 0.30.1 create that container, so the rename must take it over cleanly.

## Goals / Non-Goals

**Goals:** one new name used for image, command, container and volume; existing local runtimes keep their program data, credentials and certificate after the rename; old scripts keep working for one release.

**Non-Goals:** renaming `--runtime local`, `local-runtime.json`, the docs file, the Docker build folder or the spec capability. Those already say "local" and are not seen next to a real runtime. Moving or copying old image tags to the new package.

## Decisions

### 1. Name: `openplc-canopen-sim-runtime`
"sim" matches the rest of the project (`adapter.simulate`, `openplc-canopen-sim`, the Simulation view) and "runtime" keeps it recognisable as an OpenPLC runtime. `openplc-canopen-runtime-simulation` was considered; it is longer to type for a command used every day and puts the important word last. `openplc-canopen-sim` alone is taken by the device simulator.

### 2. Volume: reuse, do not copy
Docker and Podman cannot rename a volume. When `start` or `update` finds the old container and no new one, it stops and removes the old container and creates the new one on the old volume. The volume name in use is saved in `local-runtime.json` (`volume`), and every later command uses the saved name, so a taken-over runtime keeps `openplc-canopen-runtime-data` until `remove --data`. A fresh install gets `openplc-canopen-sim-runtime-data`. Copying the volume would need a helper container and doubles the data for no gain.

When both an old and a new container exist (someone ran an old and a new tools version), the command uses the new one and says the old one can be removed with `docker rm -f openplc-canopen-runtime`. It never removes a container it did not take over.

### 3. Old command as an alias for one release
`pyproject.toml` keeps `openplc-canopen-runtime` pointing at a small wrapper that prints `openplc-canopen-runtime is now openplc-canopen-sim-runtime; this name goes away in the next release` to stderr and calls the same `main`. The release after removes the entry point; that removal is a task of whichever change comes next, recorded in the docs' changelog line.

### 4. Image name in releases
`release-deploy.yml` pushes to `ghcr.io/<owner>/openplc-canopen-sim-runtime` only. The default image of the tools is `ghcr.io/tonihoohoo/openplc-canopen-sim-runtime:<version>`, so tools from this release never look at the old package. The release workflow's per-arch `build-<arch>` tags move to the new package with it.

## Risks / Trade-offs

- **A user upgrades the tools and runs `update`** → the takeover in decision 2 keeps their data; covered by unit tests with the fake engine and by the end-to-end test, which starts a container under the old name first.
- **Two GHCR packages for a while** → the old one is documented as superseded; deleting it is a manual step once 0.30.x is unused.
- **New package visibility**: the old package became anonymously pullable on its own (linked to the public repository through the source label). The new one should too; if not, it is set to public once after the first release.
