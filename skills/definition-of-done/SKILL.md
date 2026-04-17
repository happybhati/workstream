---
name: definition-of-done
description: Definition of done checklist for workstream PRs. Use when preparing a PR for review.
---

# Definition of Done

Before submitting a PR, ensure all items are checked:

## Code Quality

- [ ] Code follows existing patterns and conventions in this repository
- [ ] No commented-out code or debug statements left behind
- [ ] Functions and variables have clear, descriptive names
- [ ] Type hints on all function signatures

## Testing

- [ ] All tests pass: `make test`
- [ ] New functionality has corresponding test coverage
- [ ] Edge cases and error paths are tested

## Linting

- [ ] Linter passes: `make lint`
- [ ] Code formatted with black: `black .`

## CI Checks

- [ ] All CI workflows pass:
  - Lint
  - Test

## Documentation

- [ ] Public APIs or user-facing changes are documented
- [ ] README updated if behavior changes
- [ ] Commit messages follow conventional commits format

## PR Hygiene

- [ ] PR is focused on a single concern
- [ ] PR description explains WHAT changed and WHY
- [ ] No unrelated changes bundled in
