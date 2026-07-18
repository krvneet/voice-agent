#!/usr/bin/env bash
# Run BOTH services (agent worker + web) on one Linux VM — no Docker.
#
#   ./run.sh
#
# Ctrl+C stops both cleanly. If either service dies, the other is stopped too.
set -euo pipefail
cd "$(dirname "$0")"          # always run from the repo root

# Locate the virtualenv (supports both ".venv" and "venv" layouts).
if [ -x ./.venv/bin/python ]; then
  VENV=./.venv/bin
elif [ -x ./venv/bin/python ]; then
  VENV=./venv/bin
else
  echo "ERROR: no virtualenv found (looked for ./.venv and ./venv)." >&2
  exit 1
fi
echo "using venv: $VENV"

# 1) Agent worker — use `start` (production), NOT `dev`.
#    `dev` runs a file-watcher/reloader that can busy-loop on a VM.
"$VENV/python" agent/agent.py start &
AGENT_PID=$!

# 2) Web UI + token server.
#    If TLS certs exist (web/cert.pem + web/key.pem), serve HTTPS on :8443
#    (browsers require HTTPS or localhost to grant microphone access).
#    Otherwise serve plain HTTP on :8080.
if [ -f web/cert.pem ] && [ -f web/key.pem ]; then
  echo "web: HTTPS on :8443 (self-signed cert)"
  "$VENV/python" -m uvicorn server:app --host 0.0.0.0 --port 8443 --app-dir web \
    --ssl-certfile web/cert.pem --ssl-keyfile web/key.pem &
else
  echo "web: HTTP on :8080 (no certs — mic only works via localhost)"
  "$VENV/python" -m uvicorn server:app --host 0.0.0.0 --port 8080 --app-dir web &
fi
WEB_PID=$!

echo "agent PID=$AGENT_PID   web PID=$WEB_PID   (Ctrl+C stops both)"

# Kill both together on Ctrl+C / termination.
trap 'echo; echo "stopping..."; kill "$AGENT_PID" "$WEB_PID" 2>/dev/null || true' INT TERM

# Wait until either process exits, then stop the other.
wait -n "$AGENT_PID" "$WEB_PID"
echo "a service exited — stopping the other"
kill "$AGENT_PID" "$WEB_PID" 2>/dev/null || true
wait || true
