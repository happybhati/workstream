---
name: running-e2e-tests
description: How to run end-to-end tests for workstream. Use when verifying the full dashboard flow.
---

# Running E2E Tests

## Overview

Workstream is a local web application. E2E testing involves starting the server and verifying endpoints respond correctly.

## Manual E2E Verification

```bash
# Start the server
python app.py &

# Test key endpoints
curl http://localhost:8080/
curl http://localhost:8080/api/agents
curl -X POST http://localhost:8080/api/readiness/scan \
  -H 'Content-Type: application/json' \
  -d '{"repo_url":"https://github.com/happybhati/workstream"}'

# Stop the server
kill %1
```

## Makefile Targets

```bash
make help  # List all available targets
make test  # Run unit tests
make run   # Start the dashboard for manual testing
```

## Tips

- The server requires a `.env` file with at least `GITHUB_PAT` for full functionality
- Check CI workflow files for automated test steps
