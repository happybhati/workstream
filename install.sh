#!/usr/bin/env bash
# Install Workstream as a macOS LaunchAgent service.
# For Linux, use: bin/workstream-linux install
# For containers: podman build -t workstream:dev . && podman-compose up
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "ERROR: install.sh is for macOS only (uses LaunchAgent)."
    echo ""
    echo "For Linux, use one of:"
    echo "  ./bin/workstream-linux install   # systemd user service"
    echo "  podman-compose up                # container (Fedora-based)"
    echo ""
    echo "For manual run on any platform:"
    echo "  python3 -m venv venv && source venv/bin/activate"
    echo "  pip install -r requirements.txt"
    echo "  python -m uvicorn app:app --host 0.0.0.0 --port 8080"
    exit 1
fi

DASHBOARD_DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.workstream.dashboard"
PLIST_SRC="$DASHBOARD_DIR/${LABEL}.plist"
PLIST_DST="$HOME/Library/LaunchAgents/${LABEL}.plist"
CLI_SRC="$DASHBOARD_DIR/bin/workstream"
CLI_DST="$HOME/.local/bin/workstream"

echo "=== Workstream Installer ==="
echo ""

# --- 1. Ensure venv and deps ---
echo "[1/5] Setting up Python environment..."
if [ ! -d "$DASHBOARD_DIR/venv" ]; then
    python3 -m venv "$DASHBOARD_DIR/venv"
fi
source "$DASHBOARD_DIR/venv/bin/activate"
pip install -q -r "$DASHBOARD_DIR/requirements.txt"

# --- 2. Create logs directory ---
echo "[2/5] Creating log directory..."
mkdir -p "$DASHBOARD_DIR/logs"

# --- 3. Stop existing service if running ---
echo "[3/5] Stopping existing service (if any)..."
if launchctl list "$LABEL" &>/dev/null; then
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    sleep 1
fi
# Also kill anything on port 8080 left from manual runs
lsof -ti:8080 | xargs kill -9 2>/dev/null || true

# --- 4. Install plist with resolved paths ---
echo "[4/5] Installing LaunchAgent..."
mkdir -p "$HOME/Library/LaunchAgents"
sed "s|__DASHBOARD_DIR__|${DASHBOARD_DIR}|g" "$PLIST_SRC" > "$PLIST_DST"

# --- 5. Symlink CLI ---
echo "[5/5] Installing 'workstream' command..."
mkdir -p "$(dirname "$CLI_DST")"
rm -f "$CLI_DST"
ln -s "$CLI_SRC" "$CLI_DST"

# Ensure ~/.local/bin is on PATH
if ! echo "$PATH" | grep -q "$HOME/.local/bin"; then
    echo ""
    echo "NOTE: Add ~/.local/bin to your PATH if not already present:"
    echo '  echo '\''export PATH="$HOME/.local/bin:$PATH"'\'' >> ~/.zshrc && source ~/.zshrc'
fi

# --- Load and start ---
echo ""
launchctl load "$PLIST_DST"
sleep 2

if launchctl list "$LABEL" &>/dev/null; then
    echo "Workstream installed and running!"
    echo ""
    echo "  Dashboard:  http://localhost:8080"
    echo "  CLI:        workstream start | stop | restart | status | open | logs"
    echo "  Logs:       $DASHBOARD_DIR/logs/workstream.log"
    echo ""
    echo "The service will auto-start on login and auto-restart on crash."
else
    echo "Warning: Service loaded but may not be running yet."
    echo "Check: workstream status"
    echo "Logs:  workstream logs"
fi
