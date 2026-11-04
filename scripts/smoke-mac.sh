#!/usr/bin/env bash
# CI check for the Mac build: start a program that runs AFH, wait until it writes api.json, then
# fetch the UI from it.  Usage: bash scripts/smoke-mac.sh <program> [args...]
# SHOT=<file.png> also takes a screenshot of the desktop while it runs.
set -uo pipefail

AFH_HOME="$(mktemp -d)"
export AFH_HOME
"$@" >"$AFH_HOME/out.log" 2>&1 &
pid=$!
for _ in $(seq 1 90); do
  [ -f "$AFH_HOME/api.json" ] && break
  kill -0 "$pid" 2>/dev/null || break
  sleep 1
done
if [ ! -f "$AFH_HOME/api.json" ]; then
  echo "AFH never came up. Output:"
  cat "$AFH_HOME/out.log"
  kill "$pid" 2>/dev/null
  exit 1
fi
url="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['url'])" "$AFH_HOME/api.json")"
code="$(curl -s -o "$AFH_HOME/index.html" -w '%{http_code}' "$url/")"
echo "AFH answered $code at $url"
if [ -n "${SHOT:-}" ]; then
  sleep 12
  screencapture -x "$SHOT" || echo "no screenshot on this runner"
fi
kill "$pid" 2>/dev/null
sleep 2
[ "$code" = "200" ]
