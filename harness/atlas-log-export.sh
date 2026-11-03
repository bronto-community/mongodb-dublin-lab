#!/bin/sh
# Manage the Atlas project's OpenTelemetry log exports (OTEL_LOG_EXPORT), which
# the Atlas CLI has no commands for. Uses a temporary project API key created
# with your logged-in Atlas CLI (atlas auth login), and deletes it at the end.
#
#   ./atlas-log-export.sh list
#   EXPORT_KEY=... ./atlas-log-export.sh add https://ingestion.eu.staging.bronto.io/v1/logs x-bronto-api-key
#   ./atlas-log-export.sh delete <integration-id>
#
# The header value (EXPORT_KEY) comes from the environment, so it never lands
# in your shell history or the process list.
set -eu
P=${ATLAS_PROJECT_ID:-6ac39bb035b2838e26badbdf}
ORG=${ATLAS_ORG_ID:-6ac39a4e45934434f8738e03}
API="https://cloud.mongodb.com/api/atlas/v2/groups/$P/logIntegrations"
ACCEPT='Accept: application/vnd.atlas.2025-03-12+json'
cmd=${1:?usage: $0 list | add <endpoint> <header-name> | delete <id>}

tmp=$(mktemp -d); chmod 700 "$tmp"
key=$(atlas projects apiKeys create --desc "temp: OTel log export ($cmd)" --role GROUP_OWNER --projectId "$P" -o json)
kid=$(printf '%s' "$key" | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
trap 'atlas organizations apiKeys delete "$kid" --orgId "$ORG" --force >/dev/null 2>&1 && echo "temporary API key deleted"; rm -rf "$tmp"' EXIT
printf '%s' "$key" | python3 -c 'import sys,json;k=json.load(sys.stdin);print("user = \"%s:%s\"" % (k["publicKey"], k["privateKey"]))' > "$tmp/auth"
atlas organizations apiKeys accessLists create --apiKey "$kid" --ip "$(curl -s https://checkip.amazonaws.com)" --orgId "$ORG" -o json >/dev/null
sleep 3  # the access list takes a moment to apply

call() {  # method url [body-file]: prints the status and the response, with header values removed
  curl -s --digest -K "$tmp/auth" -H "$ACCEPT" -H 'Content-Type: application/json' -X "$1" "$2" \
    ${3:+--data-binary @"$3"} -w '\nHTTP %{http_code}\n' | python3 -c '
import json, sys
body, _, code = sys.stdin.read().rpartition("\nHTTP ")
print("HTTP", code.strip())
try:
    d = json.loads(body)
except Exception:
    print(body[:800]); sys.exit()
for r in d.get("results", [d]):
    for h in r.get("otelSuppliedHeaders", []):
        h["value"] = "<hidden>"
print(json.dumps(d, indent=1)[:3000])'
}

case $cmd in
  list)
    call GET "$API" ;;
  add)
    endpoint=${2:?endpoint}; header=${3:?header name}
    : "${EXPORT_KEY:?set EXPORT_KEY to the header value}"
    python3 -c 'import json,os,sys; json.dump({"type": "OTEL_LOG_EXPORT", "logTypes": ["MONGOD"], "otelEndpoint": sys.argv[1],
        "otelSuppliedHeaders": [{"name": sys.argv[2], "value": os.environ["EXPORT_KEY"]}]}, open(sys.argv[3], "w"))' \
      "$endpoint" "$header" "$tmp/body.json"
    echo "adding $endpoint at $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    call POST "$API" "$tmp/body.json" ;;
  delete)
    call DELETE "$API/${2:?integration id}" ;;
  *) echo "usage: $0 list | add <endpoint> <header-name> | delete <id>" >&2; exit 2 ;;
esac
