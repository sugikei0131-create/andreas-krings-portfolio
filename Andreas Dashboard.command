#!/bin/bash
# Andreas Krings — one-click dashboard launcher (macOS)
# Starts the local server (if needed) and opens the dashboard in your browser.
# Double-click this file. Nothing else is required.

cd "$(dirname "$0")" || exit 1

# Prefer the Homebrew Python (stable); fall back to any python3.
if [ -x /opt/homebrew/bin/python3.13 ]; then PY=/opt/homebrew/bin/python3.13
elif [ -x /opt/homebrew/bin/python3 ]; then PY=/opt/homebrew/bin/python3
elif [ -x /usr/local/bin/python3 ]; then PY=/usr/local/bin/python3
else PY=python3; fi

# Start the server only if it is not already running.
if ! curl -s --max-time 2 http://127.0.0.1:8765/api/status >/dev/null 2>&1; then
  nohup "$PY" serve.py >/dev/null 2>&1 &
  sleep 1
fi

open "http://127.0.0.1:8765/dashboard.html"
