# syntax=docker/dockerfile:1
# The local simulator runtime (canopen-local-runtime, docs/local-runtime.md):
# upstream's OpenPLC Runtime v4 image with the CANopen plugin, dcfgen, the
# device simulator and the editor hook built in, every CANopen network forced
# to run simulated. Build from the repository root:
#
#   docker build -f docker/local-runtime/Dockerfile \
#       --build-arg RUNTIME_IMAGE=ghcr.io/autonomy-logic/openplc-runtime:$(cat docker/local-runtime/runtime-version) \
#       --build-arg TOOLS_VERSION=<PC tools version> -t openplc-canopen-runtime:dev .
#
# The build stage runs the same in-image build as scripts/install-stock.sh
# --docker-image; the final stage is the unchanged upstream image plus
# /opt/openplc-canopen, two environment entries, and the HTTPS certificate
# moved into the data volume.

ARG RUNTIME_IMAGE=ghcr.io/autonomy-logic/openplc-runtime:v4.2.4

FROM ${RUNTIME_IMAGE} AS build
ARG RUNTIME_IMAGE
COPY . /src
RUN CANOPEN_IMAGE="${RUNTIME_IMAGE}" CANOPEN_IMAGE_ID="${RUNTIME_IMAGE}" \
        bash /src/scripts/install-stock.sh --in-image && \
    # Build-only: Lely's sources and pip's caches.
    rm -rf /opt/openplc-canopen/src /root/.cache && \
    find /opt/openplc-canopen -name __pycache__ -prune -exec rm -rf {} +

FROM ${RUNTIME_IMAGE}
ARG RUNTIME_IMAGE
ARG TOOLS_VERSION=dev
COPY --from=build /opt/openplc-canopen /opt/openplc-canopen
# The webserver makes its HTTPS certificate at first start next to its code;
# keep it in the data volume instead, so its fingerprint (pinned by the PC
# tools, accepted in the editor) survives `openplc-canopen-runtime update`.
RUN set -e; cd /workdir/webserver; \
    for f in certOPENPLC.pem keyOPENPLC.pem; do \
        if [ -e "$f" ]; then echo "unexpected $f in the runtime image" >&2; exit 1; fi; \
        ln -s "/var/run/runtime/$f" "$f"; \
    done
# The editor hook (keeps the canopen line in plugins.conf, reads the project
# snapshot), as the managed Docker install sets it with the bootloader.
ENV PYTHONPATH=/opt/openplc-canopen/lib/sitecustomize
# Every network runs simulated, whatever the uploaded config says.
ENV CANOPEN_FORCE_SIMULATE=1
LABEL org.opencontainers.image.title="openplc-canopen-runtime" \
      org.opencontainers.image.description="OpenPLC Runtime v4 with the CANopen plugin; every CANopen network runs simulated" \
      org.opencontainers.image.source="https://github.com/tonihoohoo/openplc-canopen" \
      org.opencontainers.image.version="${TOOLS_VERSION}" \
      org.opencontainers.image.base.name="${RUNTIME_IMAGE}" \
      io.github.tonihoohoo.openplc-canopen.tools-version="${TOOLS_VERSION}"
