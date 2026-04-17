---
name: running-tests
description: How to run unit tests for workstream. Use when writing, modifying, or verifying tests before submitting a PR.
---

# Running Tests

## Quick Start

```bash
make test
# or directly:
python -m pytest tests/ -v
```

## Python Testing

Run a specific test file:
```bash
pytest tests/test_config.py
```

Run a specific test function:
```bash
pytest tests/test_config.py::test_config_defaults
```

Run with verbose output and coverage:
```bash
pytest tests/ -v --cov=. --cov-report=term
```

## Test Locations

- `tests/` -- all test files

## Linting (run before committing)

```bash
make lint
# or: ruff check . && black --check .
```

## Tips

- Always run the full test suite before submitting a PR
- If adding new functionality, write tests alongside the code
- Check CI workflow definitions in `.github/workflows/` for the exact test matrix
