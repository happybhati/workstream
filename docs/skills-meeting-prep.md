# AI Agent Skills — Release Team Meeting

## Slide: What Skills Should We Build?

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│           AI Agent Skills — Where to Start                          │
│           Release Team Repositories                                 │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   What is a Skill?                                                  │
│   A SKILL.md file that teaches an agent HOW to do a specific        │
│   task in YOUR repo — the tribal knowledge it can't learn alone.    │
│                                                                     │
│   ┌──────────────────┬──────────────────┬─────────────────────┐     │
│   │  HIGH VALUE       │  MEDIUM VALUE    │  LOW VALUE          │     │
│   │  (build these)    │  (build next)    │  (skip these)       │     │
│   ├──────────────────┼──────────────────┼─────────────────────┤     │
│   │ Debugging e2e    │ Adding release   │ "How to write Go"   │     │
│   │ test failures    │ strategies       │                     │     │
│   │                  │                  │ "How to write YAML" │     │
│   │ Creating new     │ Finalizer        │                     │     │
│   │ tasks/pipelines  │ patterns         │ "How to use git"    │     │
│   │                  │                  │                     │     │
│   │ Definition of    │ Cross-cluster    │ General coding      │     │
│   │ done (PR stds)   │ debugging        │ best practices      │     │
│   └──────────────────┴──────────────────┴─────────────────────┘     │
│                                                                     │
│   Rule of thumb: If a new team member would need to ask             │
│   a person to learn it → it's a good skill.                         │
│                                                                     │
│   Priority 1: debugging-e2e-tests (biggest time sink)               │
│   Priority 2: creating-a-new-task (most frequent contribution)      │
│   Priority 3: definition-of-done  (quick win, all repos)            │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Example Skill: `debugging-e2e-tests/SKILL.md`

This is what a real skill looks like for release-service-catalog.
Agent discovers it, loads it when it encounters a failing e2e test,
and follows the steps without needing to ask a human.

```markdown
---
name: debugging-e2e-tests
description: >
  Use when an e2e test fails in CI, a PipelineRun is stuck, or you need
  to investigate why a release pipeline test is not passing. Covers log
  retrieval, failure interpretation, and common fixes.
version: 1.0.0
author: release-team
---

# Debugging E2E Test Failures

## When to Use

- A PR's e2e test job has failed in CI
- A periodic e2e pipeline is reporting failures
- You need to understand why a managed PipelineRun did not complete

## Step 1: Identify the Failing Test

```bash
# From the CI job output, find which test(s) failed
# Tests live in: tasks/managed/<task-name>/tests/
# Pipeline tests: pipelines/managed/<pipeline-name>/tests/
grep -r "FAIL\|ERROR" <ci-job-log>
```

The test file naming convention is `test-<task-name>.yaml`.
Each test has a corresponding `mocks.sh` and optionally a
`pre-apply-task-hook.sh` for setup.

## Step 2: Understand the Test Structure

Each e2e test follows this pattern:
```
tests/
  mocks.sh                    # Mock external services (Quay, Pyxis, etc.)
  pre-apply-task-hook.sh       # Create k8s resources before the task runs
  test-<task-name>.yaml        # The actual test pipeline
```

- `mocks.sh` — Replaces real API calls with mock responses. If a test
  fails on "connection refused" or "404", the mock likely needs updating.
- `pre-apply-task-hook.sh` — Creates Secrets, ConfigMaps, or other
  resources. If "not found" errors appear, check this file.

## Step 3: Check the PipelineRun Logs

```bash
# Get the PipelineRun for the test
oc get pipelineruns -n <test-namespace> --sort-by=.metadata.creationTimestamp

# Get logs for the failing TaskRun
oc logs -n <test-namespace> <pod-name> -c step-<step-name>

# If the pod is gone, check events
oc get events -n <test-namespace> --sort-by=.lastTimestamp | tail -20
```

## Step 4: Common Failure Patterns

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `connection refused` on mock URL | Mock server not started or wrong port | Check `mocks.sh` — ensure `ncat` or mock server is on expected port |
| `Secret "X" not found` | `pre-apply-task-hook.sh` didn't create it | Add the Secret to the hook script |
| `FAIL: results mismatch` | Task output changed, test expectation stale | Update expected results in `test-*.yaml` |
| `timeout waiting for PipelineRun` | Task hung on external dependency | Check if mock covers all external calls |
| `permission denied` | RBAC missing for test ServiceAccount | Check ClusterRole in test setup |

## Step 5: Running Tests Locally

```bash
# From the catalog repo root
cd tasks/managed/<task-name>/tests/

# The e2e framework uses tkn and oc under the hood
# Ensure you're logged into a test cluster
oc whoami

# Run the specific test
# (refer to .github/workflows/ for the exact test invocation)
```

## Step 6: Flake vs Real Failure

Before fixing, check if the test has failed before on `main`:
- Look at recent CI runs on the `development` branch
- If the same test failed 2+ times recently without related code changes,
  it's likely a flake — file a bug and mark as `known-flake`
- If it only fails on your PR, your changes likely broke something

## Important Notes

- Tests run in isolated namespaces that are cleaned up after each run
- Mock scripts must be idempotent — they may run multiple times
- Results wiring between tasks uses specific naming: `taskGitRevision`,
  `snapshotSpec`, `releasePlanAdmissionName` — check the pipeline YAML
- When adding a new mock, follow the pattern in existing `mocks.sh` files
```

---

## How to Present This

1. Show the slide (copy into Google Slides or just screen-share this markdown)
2. Open the example SKILL.md and walk through it:
   - "This is what a skill looks like — YAML frontmatter for discovery,
     then step-by-step instructions with exact commands"
   - "The key insight: this is stuff a new team member would need to ask
     us about. The agent can read code, but it can't know our test
     structure conventions or which namespace to look in."
3. Ask the team: "What other workflows do you find yourself explaining
   repeatedly? Those are your next skills."
