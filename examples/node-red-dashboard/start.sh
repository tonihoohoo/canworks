#!/bin/sh
# Starts Node-RED for the canworks dashboard example (docker-compose.yml).
# Installs the canworks package that the setup service exported (again when
# its version changed) and Node-RED Dashboard 2.0 into /data, writes the flow
# (the exported canworks flow plus dashboard.json) once, in place of the
# image's sample flow, then starts Node-RED with the image's entrypoint.
# Later starts keep your flow.
set -e
DASHBOARD_VERSION=1.34.0
DATA=/data
SHARE=/share
EXAMPLE=/example

PKG=$(ls "$SHARE"/node-red-canworks-*.tgz)
VERSION=$(basename "$PKG" .tgz | sed 's/^node-red-canworks-//')
cd "$DATA"
[ -f package.json ] || echo '{"name": "node-red-project", "private": true}' > package.json
if [ "$(cat .canworks-version 2>/dev/null)" != "$VERSION" ] || [ ! -d node_modules/@flowfuse/node-red-dashboard ]; then
    echo "Installing node-red-canworks $VERSION and Node-RED Dashboard 2.0 $DASHBOARD_VERSION"
    rm -f node-red-canworks-*.tgz
    cp "$PKG" .
    npm install --no-audit --no-fund --no-update-notifier --cache "$DATA/.npm" \
        "./$(basename "$PKG")" "@flowfuse/node-red-dashboard@$DASHBOARD_VERSION"
    echo "$VERSION" > .canworks-version
fi
if [ ! -f .canworks-flow ]; then
    echo "Writing the flow: $SHARE/plant_node-red.json and dashboard.json"
    node -e 'const fs = require("fs"); const [a, b, out] = process.argv.slice(1);
        const read = (f) => JSON.parse(fs.readFileSync(f, "utf8"));
        fs.writeFileSync(out, JSON.stringify(read(a).concat(read(b)), null, 1));' \
        "$SHARE/plant_node-red.json" "$EXAMPLE/dashboard.json" flows.json.new
    mv -f flows.json.new flows.json
    touch .canworks-flow
fi
cd /usr/src/node-red
exec ./entrypoint.sh
