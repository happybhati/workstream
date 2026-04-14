#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

echo "Installing dependencies..."
pip install -q -r requirements.txt

if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

echo ""
echo "Starting PR Dashboard at http://localhost:8080"
echo "Press Ctrl+C to stop."
echo ""

python app.py
