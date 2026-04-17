# Claude Configuration for workstream

## Agent Skills

This repository uses [Agent Skills](https://agentskills.io/) stored in the
`skills/` directory at the repo root.

To let Claude (and other skills-compatible agents) discover them, create a
symlink:

```bash
ln -sf ../skills .claude/skills
```

## Available Skills

- **running-tests** -- How to run the test suite
- **running-e2e-tests** -- How to run e2e/integration tests
- **definition-of-done** -- PR checklist and review standards
- **debugging-guide** -- How to debug issues
- **local-dev-setup** -- Setting up a local dev environment
