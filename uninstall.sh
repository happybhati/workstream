#!/usr/bin/env bash
# Uninstall the Workstream LaunchAgent service and CLI symlink.
set -euo pipefail

LABEL="com.workstream.dashboard"
PLIST_DST="$HOME/Library/LaunchAgents/${LABEL}.plist"
CLI_DST="$HOME/.local/bin/workstream"

echo "=== Workstream Uninstaller ==="
echo ""

# --- 1. Stop and unload service ---
if launchctl list "$LABEL" &>/dev/null; then
    echo "Stopping service..."
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    sleep 1
    echo "Service stopped."
else
    echo "Service is not currently running."
fi

# --- 2. Remove plist ---
if [ -f "$PLIST_DST" ]; then
    rm -f "$PLIST_DST"
    echo "Removed LaunchAgent plist."
else
    echo "No LaunchAgent plist found."
fi

# --- 3. Remove CLI symlink ---
if [ -L "$CLI_DST" ] || [ -f "$CLI_DST" ]; then
    rm -f "$CLI_DST"
    echo "Removed 'workstream' command from $CLI_DST."
else
    echo "No CLI symlink found."
fi

echo ""
echo "Workstream uninstalled."
echo "Your data (database, logs, config) has been left in place."
echo "To remove everything: rm -rf ~/.cursor/workflow/dashboard"
