---
name: local-dev-setup
description: How to set up a local development environment for workstream. Use when onboarding or resetting your dev environment.
---

# Local Development Setup

## Prerequisites

- [Python 3.12+](https://www.python.org/downloads/)
- [Git](https://git-scm.com/)

## Clone & Setup

```bash
git clone https://github.com/happybhati/workstream.git
cd workstream
make setup
```

Or manually:
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Copy the example environment file and add your tokens:
```bash
cp .env.example .env
# Edit .env with your GITHUB_PAT, JIRA_TOKEN, etc.
```

## Verify Setup

```bash
make test
```

## Run

```bash
make run
# Dashboard available at http://localhost:8080
```

## IDE Setup

If using Cursor or VS Code, the repo includes:
- `.cursor/rules/` -- AI coding rules
- `.editorconfig` -- formatting rules
