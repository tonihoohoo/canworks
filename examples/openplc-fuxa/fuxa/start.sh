#!/bin/sh
# Starts FUXA for the canworks OpenPLC + FUXA example (docker-compose.yml).
# Installs FUXA's OPC UA driver when it is missing (into the _pkg volume, so
# only the first start needs the internet) and loads fuxa/project.json once
# (a marker in the _appdata volume), so later changes made in FUXA's editor
# are kept. Then waits on FUXA.
set -e
API=http://127.0.0.1:1881/api
PROJECT=/example/fuxa/project.json
MARKER=_appdata/.canworks-project

cd /usr/src/app/FUXA/server
node main.js &
FUXA=$!
trap 'kill -TERM $FUXA 2>/dev/null; wait $FUXA' TERM INT

# FUXA's own HTTP calls, with node (the image has no curl).
call() {
    node -e '
        const [method, url, file] = process.argv.slice(1);
        const body = file ? require("fs").readFileSync(file) : undefined;
        fetch(url, { method, body, headers: { "Content-Type": "application/json" } })
            .then(async (r) => { process.stdout.write(await r.text()); process.exit(r.ok ? 0 : 1); })
            .catch(() => process.exit(2));' "$@"
}

until call GET "$API/settings" >/dev/null 2>&1; do sleep 1; done

if ! call GET "$API/plugins" | grep -q '"name":"node-opcua"[^}]*"current":"[0-9]'; then
    echo "Installing FUXA's OPC UA driver (node-opcua)"
    echo '{"params":{"name":"node-opcua","type":"OPCUA","version":"2.149.0","group":"connectionDevice","dinamic":true}}' > /tmp/opcua-plugin.json
    call POST "$API/plugins" /tmp/opcua-plugin.json >/dev/null
fi

if [ ! -f "$MARKER" ]; then
    echo "Loading $PROJECT"
    call POST "$API/project" "$PROJECT" >/dev/null
    touch "$MARKER"
fi

wait $FUXA
