# syntax=docker/dockerfile:1
# canworks-bridge, the Modbus TCP bridge (docs/modbus-bridge.md), as a
# container image. Build from the repository root:
#
#   docker build -f docker/bridge/Dockerfile --build-arg TOOLS_VERSION=<PC tools version> -t canworks-bridge:dev .
#
# Run with the host's network (CAN interfaces and the Modbus port) and the
# config folder mounted at /etc/canworks-bridge:
#
#   docker run -d --network host --cap-add NET_ADMIN -v /srv/bridge:/etc/canworks-bridge canworks-bridge:dev
#
# The build stage runs scripts/install-bridge.sh; the final stage holds
# /opt/canworks (canworks-bridge, Lely CANopen, dcfgen and the EDS lint) on
# the same Debian release.

FROM debian:bookworm AS build
ARG TOOLS_VERSION=dev
COPY . /src
# .git is not in the build context: the bridge reports the tools version.
# No systemd in the image: the unit is written to a scratch folder.
RUN CANWORKS_PLUGIN_VERSION="${TOOLS_VERSION}" CANWORKS_SYSTEMCTL=true CANWORKS_UNIT_DIR=/tmp/units \
        CANWORKS_BRIDGE_CONF_DIR=/tmp/conf CANWORKS_MODPROBE=true CANWORKS_MODULES_LOAD_DIR=/tmp/modules \
        bash /src/scripts/install-bridge.sh && \
    # Build-only: Lely's and the runtime's sources, pip's caches.
    rm -rf /opt/canworks/src /root/.cache && \
    find /opt/canworks -name __pycache__ -prune -exec rm -rf {} +

FROM debian:bookworm-slim
ARG TOOLS_VERSION=dev
RUN apt-get update -qq && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends libssl3 python3 iproute2 && \
    rm -rf /var/lib/apt/lists/*
COPY --from=build /opt/canworks /opt/canworks
VOLUME /etc/canworks-bridge
ENTRYPOINT ["/opt/canworks/bin/canworks-bridge"]
CMD ["--config", "/etc/canworks-bridge/canworks.json"]
LABEL org.opencontainers.image.title="canworks-bridge" \
      org.opencontainers.image.description="CANopen and J1939 networks served as Modbus TCP registers" \
      org.opencontainers.image.source="https://github.com/tonihoohoo/canworks" \
      org.opencontainers.image.version="${TOOLS_VERSION}"
