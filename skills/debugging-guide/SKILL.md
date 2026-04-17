---
name: debugging-guide
description: How to debug issues in workstream. Use when investigating bugs or unexpected behavior.
---

# Debugging Guide

## General Approach

1. Reproduce the issue with a minimal test case
2. Check logs for error messages and stack traces
3. Use a debugger or add targeted logging
4. Verify the fix with a test before submitting

## Python Debugging

Drop into a debugger at a specific point:
```python
import pdb; pdb.set_trace()  # or: breakpoint()
```

Run pytest with output visible:
```bash
pytest -s -v tests/test_config.py
```

Debug a specific test:
```bash
pytest --pdb tests/test_config.py::test_name
```

## Logging

Workstream uses Python's `logging` module. Enable debug logging:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

Check the logger name pattern: `dashboard.<module>` (e.g., `dashboard.readiness.scanner`).

## Common Issues

- **Tests pass locally but fail in CI**: Check for environment differences or missing `.env` vars
- **Dashboard won't start**: Check if port 8080 is already in use (`lsof -ti tcp:8080`)
- **API returns empty data**: Verify `GITHUB_PAT` is set in `.env`
- **Scan fails**: Check GitHub API rate limits
