#!/bin/sh
# Starts FUXA for the canworks FUXA example (docker-compose.yml). Turns on
# FUXA's built-in Node-RED, installs the canworks package that the setup
# service exported (again when its version changed) into Node-RED's user
# folder, writes the flow (the exported canworks flow plus plant.json) and
# loads fuxa/project.json once, then keeps FUXA running. Later starts keep
# your flow and your FUXA project. Needs no internet.
set -e
SERVER=/usr/src/app/FUXA/server
APPDATA=$SERVER/_appdata
RED=$APPDATA/node-red
SHARE=/share
EXAMPLE=/example
mkdir -p "$RED"

# Node-RED on (FUXA's default is off), other settings kept.
node -e 'const fs = require("fs"); const f = process.argv[1];
    const s = fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, "utf8")) : {};
    if (s.nodeRedEnabled !== true) { s.nodeRedEnabled = true; fs.writeFileSync(f, JSON.stringify(s, null, 2)); }' \
    "$APPDATA/mysettings.json"

PKG=$(ls "$SHARE"/node-red-canworks-*.tgz)
VERSION=$(basename "$PKG" .tgz | sed 's/^node-red-canworks-//')
cd "$RED"
[ -f package.json ] || echo '{"name": "node-red-project", "private": true}' > package.json
if [ "$(cat .canworks-version 2>/dev/null)" != "$VERSION" ]; then
    echo "Installing node-red-canworks $VERSION"
    rm -f node-red-canworks-*.tgz
    cp "$PKG" .
    npm install --offline --no-audit --no-fund --no-update-notifier "./$(basename "$PKG")"
    echo "$VERSION" > .canworks-version
fi
if [ ! -f .canworks-flow ]; then
    echo "Writing the flow: $SHARE/plant_node-red.json and plant.json"
    node -e 'const fs = require("fs"); const [a, b, out] = process.argv.slice(1);
        const read = (f) => JSON.parse(fs.readFileSync(f, "utf8"));
        fs.writeFileSync(out, JSON.stringify(read(a).concat(read(b)), null, 1));' \
        "$SHARE/plant_node-red.json" "$EXAMPLE/plant.json" flows.json.new
    mv -f flows.json.new flows.json
    touch .canworks-flow
fi

cd "$SERVER"
node main.js &
PID=$!
trap 'kill -TERM $PID; wait $PID' TERM INT
if [ ! -f "$APPDATA/.canworks-project" ]; then
    echo "Loading fuxa/project.json"
    if node -e 'const fs = require("fs");
        const body = fs.readFileSync(process.argv[1], "utf8");
        const url = "http://127.0.0.1:1881/api/";
        const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
        (async () => {
            for (let i = 0; i < 120; i++) {
                try { if ((await fetch(url + "settings")).ok) break; } catch (e) { }
                await sleep(1000);
            }
            const r = await fetch(url + "project", { method: "POST", body, headers: { "Content-Type": "application/json" } });
            if (!r.ok) { console.error("loading the FUXA project failed: HTTP " + r.status); process.exit(1); }
        })();' "$EXAMPLE/fuxa/project.json"; then
        touch "$APPDATA/.canworks-project"
    fi
fi
wait $PID
