"""Generate AI-ready files for a repository based on scan results.

Key design principle: GAP-FILLING, not structure mirroring.
Only generates content for information that is genuinely missing from the
repo's existing documentation. Redundant context files hurt LLM performance
(ETH Zurich arXiv:2602.11988).

Produces tool-specific files:
  - AGENTS.md         (Codex / generic standard)
  - CLAUDE.md         (imperative commands for Claude Code)
  - GEMINI.md         (hierarchical with @imports)
  - .github/copilot-instructions.md  (under 4000 chars)
  - .cursor/rules/repo.mdc (YAML frontmatter + glob patterns)
  - .codex/config.toml (setup/verify commands)
  - ARCHITECTURE.md   (structural overview)
  - CONTRIBUTING.md   (workflow guide)

Agent Skills (agentskills.io-compatible):
  - skills/running-tests/SKILL.md
  - skills/running-e2e-tests/SKILL.md
  - skills/definition-of-done/SKILL.md
  - skills/debugging-guide/SKILL.md
  - skills/local-dev-setup/SKILL.md
  - .claude/README.md (symlink instructions)

Also handles creating draft PRs via the GitHub API.
"""

from __future__ import annotations

import base64
import logging
import re
from textwrap import dedent

import httpx

from config import settings

logger = logging.getLogger("dashboard.readiness.generator")

GITHUB_API = "https://api.github.com"


def _github_headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.github_pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


# ---------------------------------------------------------------------------
# Gap analysis helpers
# ---------------------------------------------------------------------------


def _extract_existing_info(scan: dict) -> dict:
    """Extract what is already documented in existing files to avoid redundancy."""
    existing = {
        "has_build_commands": False,
        "has_test_commands": False,
        "has_conventions": False,
        "has_architecture_info": False,
        "has_contributing_info": False,
        "documented_dirs": set(),
        "documented_commands": [],
    }

    readme = scan["key_files"].get("README.md", "")
    contrib = scan["key_files"].get("CONTRIBUTING.md", "")
    arch = scan["key_files"].get("ARCHITECTURE.md", "")
    agents = scan["key_files"].get("AGENTS.md", "")

    all_text = f"{readme}\n{contrib}\n{arch}\n{agents}"

    cmd_re = re.compile(
        r"(?:^|\n)\s*(?:```[\s\S]*?```|`[^`]+`)",
        re.MULTILINE,
    )
    build_re = re.compile(
        r"(?i)(go\s+(build|mod|install)|npm\s+(install|ci|run)|"
        r"pip\s+install|cargo\s+(build|install)|make\s+\w+|"
        r"mvn\s+|gradle\s+|yarn\s+(install|add)|poetry\s+install)"
    )
    test_re = re.compile(
        r"(?i)(go\s+test|pytest|npm\s+test|cargo\s+test|"
        r"make\s+test|yarn\s+test|mvn\s+test)"
    )

    if build_re.search(all_text):
        existing["has_build_commands"] = True
    if test_re.search(all_text):
        existing["has_test_commands"] = True

    if re.search(r"(?i)(convention|style\s+guide|coding\s+standard|code\s+style)", all_text):
        existing["has_conventions"] = True
    if arch or re.search(r"(?i)(architect|component|design\s+decision|system\s+design)", readme):
        existing["has_architecture_info"] = True
    if contrib:
        existing["has_contributing_info"] = True

    return existing


def _infer_commands(scan: dict) -> dict:
    """Infer build, test, and lint commands from detected dependency/tool files."""
    cmds = {"build": [], "test": [], "lint": [], "install": []}
    lang = (scan.get("primary_language") or "").lower()
    dep_files = [p.split("/")[-1] for p in scan.get("dep_files", [])]

    if "go.mod" in dep_files or "go" in lang:
        cmds["install"].append("go mod tidy")
        cmds["build"].append("go build ./...")
        cmds["test"].append("go test ./...")
        cmds["lint"].append("go vet ./...")
    elif "package.json" in dep_files:
        cmds["install"].append("npm install")
        cmds["build"].append("npm run build")
        cmds["test"].append("npm test")
    elif "requirements.txt" in dep_files or "python" in lang:
        cmds["install"].append("pip install -r requirements.txt")
        cmds["test"].append("pytest")
    elif "pyproject.toml" in dep_files:
        cmds["install"].append("pip install -e '.[dev]'")
        cmds["test"].append("pytest")
    elif "Cargo.toml" in dep_files or "rust" in lang:
        cmds["build"].append("cargo build")
        cmds["test"].append("cargo test")
        cmds["lint"].append("cargo clippy")

    linter_files = [p.split("/")[-1] for p in scan.get("linter_files", [])]
    if any("golangci" in f for f in linter_files):
        cmds["lint"].append("golangci-lint run")
    if any("eslint" in f for f in linter_files):
        cmds["lint"].append("npx eslint .")
    if "Makefile" in linter_files:
        cmds["lint"].append("make lint")

    return cmds


# ---------------------------------------------------------------------------
# AGENTS.md -- gap-filling: only non-redundant info
# ---------------------------------------------------------------------------


def generate_agents_md(scan: dict, intelligence: dict | None = None) -> str:
    owner = scan["owner"]
    repo = scan["repo"]
    lang = scan.get("primary_language", "")
    desc = scan.get("description", "")
    dirs = scan.get("dirs", [])
    tree = scan.get("tree", [])
    existing = _extract_existing_info(scan)
    cmds = _infer_commands(scan)

    lines = [
        "# AGENTS.md",
        "",
        f"> Agent guidance for **{owner}/{repo}**",
        "",
    ]

    if desc and not existing["has_architecture_info"]:
        lines += [f"{desc}", ""]

    lines += ["## Repository Map", "", "```"]
    lines += [f"{owner}/{repo}/"]
    for d in sorted(dirs)[:20]:
        marker = _dir_purpose(d, tree)
        lines += [f"  {d}/ {marker}"]
    lines += ["```", ""]

    if not existing["has_build_commands"] and (cmds["install"] or cmds["build"]):
        lines += ["## Build Commands", ""]
        for cmd in cmds["install"]:
            lines += [f"- Install: `{cmd}`"]
        for cmd in cmds["build"]:
            lines += [f"- Build: `{cmd}`"]
        lines += [""]

    if not existing["has_test_commands"] and cmds["test"]:
        lines += ["## Test Commands", ""]
        for cmd in cmds["test"]:
            lines += [f"- `{cmd}`"]
        lines += [""]

    if cmds["lint"]:
        lines += ["## Lint", ""]
        for cmd in cmds["lint"]:
            lines += [f"- `{cmd}`"]
        lines += [""]

    if not existing["has_conventions"]:
        lines += [
            "## Conventions",
            "",
            "- Follow existing code style and patterns",
            "- Write tests for new functionality",
            "- Keep PRs focused on a single concern",
        ]
        if lang:
            ll = lang.lower()
            if "go" in ll:
                lines += [
                    "- Handle all errors explicitly (no blank `_ = err`)",
                    "- Use table-driven tests",
                    "- Exported names use PascalCase",
                ]
            elif "python" in ll:
                lines += [
                    "- Use type hints on function signatures",
                    "- Follow PEP 8",
                ]
            elif "typescript" in ll or "javascript" in ll:
                lines += [
                    "- Prefer `const` over `let`; use strict TypeScript",
                    "- Use async/await over raw promises",
                ]
        lines += [""]

    if intelligence and intelligence.get("patterns"):
        lines += ["## Team Review Patterns", ""]
        for p in intelligence["patterns"][:5]:
            lines += [f"- {p['pattern']}"]
        lines += [""]

    pointers = []
    if scan.get("key_files", {}).get("CONTRIBUTING.md"):
        pointers.append("- Workflow: `CONTRIBUTING.md`")
    if scan.get("key_files", {}).get("ARCHITECTURE.md"):
        pointers.append("- Architecture: `ARCHITECTURE.md`")
    if scan.get("doc_dirs"):
        pointers.append(f"- Docs: `{scan['doc_dirs'][0]}/`")
    if scan.get("ci_workflows"):
        pointers.append("- CI: `.github/workflows/`")
    if pointers:
        lines += ["## See Also", ""] + pointers + [""]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLAUDE.md -- imperative commands, not descriptions
# ---------------------------------------------------------------------------


def generate_claude_md(scan: dict, intelligence: dict | None = None) -> str:
    owner = scan["owner"]
    repo = scan["repo"]
    cmds = _infer_commands(scan)
    ci_cmds = scan.get("ci_commands", {})
    lang = (scan.get("primary_language") or "").lower()

    lines = [
        f"# {owner}/{repo}",
        "",
    ]

    install = ci_cmds.get("install", []) or cmds["install"]
    build = ci_cmds.get("build", []) or cmds["build"]
    test = ci_cmds.get("test", []) or cmds["test"]
    lint = ci_cmds.get("lint", []) or cmds["lint"]
    all_cmds = install[:2] + build[:1] + test[:2] + lint[:2]
    if all_cmds:
        for cmd in all_cmds:
            lines.append(cmd)
        lines.append("")

    lines.append("## Rules")
    lines.append("")
    lines.append("- Follow existing code patterns in this repository")
    lines.append("- Write tests for all changes")

    if "go" in lang:
        lines += [
            "- Handle all errors; never use blank identifier for errors",
            "- Use table-driven tests with t.Run()",
            "- Run `go vet ./...` before committing",
        ]
    elif "python" in lang:
        lines += [
            "- Use type hints on all function signatures",
            "- Follow PEP 8; use pytest for tests",
        ]
    elif "typescript" in lang or "javascript" in lang:
        lines += [
            "- Use strict TypeScript; prefer const over let",
            "- Use async/await, not raw promises",
        ]

    lines.append("")

    if intelligence and intelligence.get("patterns"):
        lines += ["## Team Conventions"]
        lines.append("")
        for p in intelligence["patterns"][:5]:
            lines.append(f"- {p['pattern']}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# GEMINI.md -- hierarchical with @imports
# ---------------------------------------------------------------------------


def generate_gemini_md(scan: dict) -> str:
    owner = scan["owner"]
    repo = scan["repo"]
    desc = scan.get("description", "")
    cmds = _infer_commands(scan)
    lang = (scan.get("primary_language") or "").lower()

    lines = [
        f"# {owner}/{repo}",
        "",
    ]
    if desc:
        lines += [f"{desc}", ""]

    lines += ["## Setup", ""]
    for cmd in cmds["install"] + cmds["build"]:
        lines += ["```bash", f"{cmd}", "```", ""]

    lines += ["## Testing", ""]
    for cmd in cmds["test"]:
        lines += ["```bash", f"{cmd}", "```", ""]

    lines += ["## Code Style", ""]
    if "go" in lang:
        lines += ["- Go: handle all errors, table-driven tests, PascalCase exports"]
    elif "python" in lang:
        lines += ["- Python: PEP 8, type hints, pytest"]
    elif "typescript" in lang or "javascript" in lang:
        lines += ["- TypeScript: strict mode, const over let, async/await"]
    else:
        lines += ["- Follow existing patterns in this repository"]
    lines += [""]

    existing_docs = []
    if scan.get("key_files", {}).get("CONTRIBUTING.md"):
        existing_docs.append("@CONTRIBUTING.md")
    if scan.get("key_files", {}).get("ARCHITECTURE.md"):
        existing_docs.append("@ARCHITECTURE.md")
    if existing_docs:
        lines += ["## References", ""]
        for doc in existing_docs:
            lines += [f"- {doc}"]
        lines += [""]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# .github/copilot-instructions.md -- under 4000 chars for code review
# ---------------------------------------------------------------------------


def generate_copilot_instructions(scan: dict) -> str:
    owner = scan["owner"]
    repo = scan["repo"]
    lang = (scan.get("primary_language") or "").lower()
    cmds = _infer_commands(scan)

    lines = [
        f"# Copilot Instructions for {owner}/{repo}",
        "",
    ]

    if cmds["test"]:
        lines += [f"Run tests: `{cmds['test'][0]}`", ""]
    if cmds["lint"]:
        lines += [f"Lint: `{cmds['lint'][0]}`", ""]

    lines += ["## Review Guidelines", ""]
    lines += [
        "- Verify error handling is complete",
        "- Check test coverage for new code",
        "- Ensure backward compatibility",
    ]
    if "go" in lang:
        lines += [
            "- Verify all errors are checked (no `_ = err`)",
            "- Check for goroutine leaks and proper context cancellation",
        ]
    elif "python" in lang:
        lines += [
            "- Verify type hints are present",
            "- Check for proper exception handling",
        ]
    lines += [""]

    content = "\n".join(lines)
    if len(content) > 4000:
        content = content[:3950] + "\n\n<!-- truncated to 4000 char limit -->\n"
    return content


# ---------------------------------------------------------------------------
# .cursor/rules/repo.mdc -- YAML frontmatter + glob patterns
# ---------------------------------------------------------------------------


def generate_cursor_rules(scan: dict, intelligence: dict | None = None) -> str:
    owner = scan["owner"]
    repo = scan["repo"]
    lang = (scan.get("primary_language") or "").lower()
    desc = scan.get("description", "")
    cmds = _infer_commands(scan)

    globs = []
    if "go" in lang:
        globs = ["**/*.go"]
    elif "python" in lang:
        globs = ["**/*.py"]
    elif "typescript" in lang:
        globs = ["**/*.ts", "**/*.tsx"]
    elif "javascript" in lang:
        globs = ["**/*.js", "**/*.jsx"]
    elif "rust" in lang:
        globs = ["**/*.rs"]

    lines = ["---"]
    if globs:
        lines += [f"globs: {', '.join(globs)}"]
    lines += [f"description: Rules for {owner}/{repo}", "---", ""]

    lines += [f"# {repo}", ""]
    if desc:
        lines += [f"{desc}", ""]

    if cmds["test"]:
        lines += [f"Test command: `{cmds['test'][0]}`"]
    if cmds["lint"]:
        lines += [f"Lint command: `{cmds['lint'][0]}`"]
    if cmds["test"] or cmds["lint"]:
        lines += [""]

    lines += ["## Conventions", ""]
    lines += ["- Follow existing code patterns"]
    lines += ["- Write tests for all changes"]
    lines += ["- Keep PRs focused on a single concern"]

    if "go" in lang:
        lines += [
            "- Handle all errors explicitly",
            "- Use table-driven tests with t.Run()",
            "- Exported names: PascalCase",
        ]
    elif "python" in lang:
        lines += [
            "- Type hints on all function signatures",
            "- PEP 8 style",
            "- pytest for tests",
        ]
    elif "typescript" in lang or "javascript" in lang:
        lines += [
            "- Strict TypeScript",
            "- const over let",
            "- async/await over raw promises",
        ]
    lines += [""]

    if intelligence and intelligence.get("patterns"):
        lines += ["## Team Review Patterns", ""]
        for p in intelligence["patterns"][:5]:
            lines += [f"- {p['pattern']}"]
        lines += [""]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# .codex/config.toml -- setup and verify commands
# ---------------------------------------------------------------------------


def generate_codex_config(scan: dict) -> str:
    cmds = _infer_commands(scan)

    install = cmds["install"][0] if cmds["install"] else ""
    verify = cmds["test"][0] if cmds["test"] else (cmds["build"][0] if cmds["build"] else "")

    lines = [
        "# Codex configuration",
        "# https://github.com/openai/codex",
        "",
    ]

    if install:
        lines += [
            "[setup]",
            f'install = "{install}"',
            "",
        ]

    if verify:
        lines += [
            "[verify]",
            f'command = "{verify}"',
            "",
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ARCHITECTURE.md
# ---------------------------------------------------------------------------


def generate_architecture_md(scan: dict) -> str:
    owner = scan["owner"]
    repo = scan["repo"]
    desc = scan.get("description", "")
    lang = scan.get("primary_language", "")
    dirs = scan.get("dirs", [])
    tree = scan.get("tree", [])

    lines = [
        "# Architecture",
        "",
        f"## {owner}/{repo}",
        "",
    ]
    if desc:
        lines += [f"{desc}", ""]
    if lang:
        langs = scan.get("languages", {})
        if langs:
            total = sum(langs.values())
            lang_parts = []
            for l, b in sorted(langs.items(), key=lambda x: -x[1])[:6]:
                pct = round(b / total * 100) if total else 0
                lang_parts.append(f"{l} ({pct}%)")
            lines += [f"**Languages:** {', '.join(lang_parts)}", ""]

    lines += ["## Directory Structure", "", "```"]
    lines += [f"{repo}/"]
    for d in sorted(dirs)[:30]:
        count = sum(1 for p in tree if p.startswith(d + "/"))
        lines += [f"  {d}/ ({count} files)"]
    lines += ["```", ""]

    key_dirs = _identify_key_dirs(scan)
    if key_dirs:
        lines += ["## Components", ""]
        for path, purpose in key_dirs:
            lines += [f"### `{path}/`", "", f"{purpose}", ""]

    if scan.get("has_ci"):
        lines += [
            "## CI/CD",
            "",
            f"This project uses GitHub Actions with {len(scan.get('ci_workflows', []))} workflow(s):",
            "",
        ]
        for w in scan.get("ci_workflows", [])[:10]:
            lines += [f"- {w}"]
        lines += [""]

    dep_files = scan.get("dep_files", [])
    if dep_files:
        lines += ["## Dependencies", "", "Managed via:", ""]
        for df in dep_files[:5]:
            lines += [f"- `{df}`"]
        lines += [""]

    lines += [
        "## Design Decisions",
        "",
        "<!-- Document key architectural decisions here -->",
        "<!-- Format: ### Decision Title -->",
        "<!-- **Context:** Why was this decision needed? -->",
        "<!-- **Decision:** What was decided? -->",
        "<!-- **Consequences:** What are the trade-offs? -->",
        "",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CONTRIBUTING.md
# ---------------------------------------------------------------------------


def generate_contributing_md(scan: dict) -> str:
    owner = scan["owner"]
    repo = scan["repo"]
    lang = scan.get("primary_language", "")

    lines = [
        f"# Contributing to {repo}",
        "",
        f"Thank you for contributing to **{owner}/{repo}**!",
        "",
        "## Getting Started",
        "",
        "1. Fork the repository",
        f"2. Clone your fork: `git clone https://github.com/<your-user>/{repo}.git`",
        "3. Create a feature branch: `git checkout -b feature/your-change`",
        "",
    ]

    dep_files = scan.get("dep_files", [])
    if dep_files:
        dep_name = dep_files[0].split("/")[-1]
        lines += ["## Setup", ""]
        if "go.mod" in dep_name:
            lines += ["```bash", "go mod tidy", "go build ./...", "```"]
        elif "package.json" in dep_name:
            lines += ["```bash", "npm install", "npm run build  # if applicable", "```"]
        elif "requirements.txt" in dep_name:
            lines += [
                "```bash",
                "python -m venv venv",
                "source venv/bin/activate",
                "pip install -r requirements.txt",
                "```",
            ]
        elif "Cargo.toml" in dep_name:
            lines += ["```bash", "cargo build", "```"]
        else:
            lines += [f"See `{dep_name}` for dependency details."]
        lines += [""]

    if scan.get("test_dirs") or scan.get("has_ci"):
        lines += ["## Testing", ""]
        if lang and "go" in lang.lower():
            lines += ["```bash", "go test ./...", "```"]
        elif lang and "python" in lang.lower():
            lines += ["```bash", "pytest", "```"]
        elif lang and ("javascript" in lang.lower() or "typescript" in lang.lower()):
            lines += ["```bash", "npm test", "```"]
        else:
            lines += ["Run the project's test suite before submitting changes."]
        lines += [""]

    lines += [
        "## Submitting Changes",
        "",
        "1. Commit your changes with a clear message",
        "2. Push to your fork",
        "3. Open a Pull Request against the `main` branch",
        "4. Describe what changed and why in the PR description",
        "",
        "## Code Style",
        "",
        "- Follow the existing code patterns in the repository",
    ]

    if scan.get("linter_files"):
        lf = scan["linter_files"][0].split("/")[-1]
        lines += [f"- Linting is configured via `{lf}` -- ensure your changes pass"]

    lines += [
        "- Keep changes focused and atomic",
        "- Write or update tests for new functionality",
        "",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent Skills (agentskills.io specification)
# ---------------------------------------------------------------------------

def generate_skill_running_tests(scan: dict) -> str:
    """Generate skills/running-tests/SKILL.md."""
    repo = scan["repo"]
    lang = (scan.get("primary_language") or "").lower()
    cmds = _infer_commands(scan)
    ci_cmds = scan.get("ci_commands", {})
    test_dirs = scan.get("test_dirs", [])
    makefile_targets = scan.get("makefile_targets", [])

    lines = [
        "---",
        "name: running-tests",
        "description: Use when writing, modifying, or verifying tests. Use when a PR needs test validation, CI is failing, or you need to run a specific test file or function.",
        "---",
        "",
        "# Running Tests",
        "",
        "## Quick Start",
        "",
    ]

    real_test_cmds = ci_cmds.get("test", []) or cmds["test"]
    if real_test_cmds:
        for cmd in real_test_cmds[:3]:
            lines += ["```bash", cmd, "```", ""]
    else:
        lines += ["No standard test command detected. Check the project README or Makefile.", ""]

    test_make_targets = [t for t in makefile_targets if "test" in t.lower()]
    if test_make_targets:
        lines += ["## Makefile Targets", ""]
        for t in test_make_targets[:5]:
            lines += [f"- `make {t}`"]
        lines += [""]

    if "go" in lang:
        lines += [
            "## Running Specific Tests",
            "",
            "```bash",
            "go test ./path/to/package/...",
            "go test -v -run TestFunctionName ./...",
            "go test -race ./...  # recommended for CI",
            "```",
            "",
        ]
    elif "python" in lang:
        lines += [
            "## Running Specific Tests",
            "",
            "```bash",
            "pytest path/to/test_file.py",
            "pytest path/to/test_file.py::test_function_name",
            "pytest -v --tb=short  # verbose with short tracebacks",
            "```",
            "",
        ]
    elif "typescript" in lang or "javascript" in lang:
        lines += [
            "## Running Specific Tests",
            "",
            "```bash",
            "npm test -- --testPathPattern=path/to/test",
            "```",
            "",
        ]

    if test_dirs:
        lines += ["## Test Locations", ""]
        for d in test_dirs[:10]:
            lines += [f"- `{d}/`"]
        lines += [""]

    real_lint_cmds = ci_cmds.get("lint", []) or cmds["lint"]
    if real_lint_cmds:
        lines += ["## Linting (run before committing)", ""]
        for cmd in real_lint_cmds[:3]:
            lines += ["```bash", cmd, "```", ""]

    lines += [
        "## Output Format",
        "",
        "When reporting test results, use:",
        "",
        "```markdown",
        "## Test Results",
        "",
        "**Command:** `<command run>`",
        "**Status:** PASS / FAIL",
        "**Failed tests:** <list if any>",
        "**Root cause:** <brief analysis if failing>",
        "```",
        "",
    ]

    return "\n".join(lines)


def generate_skill_running_e2e_tests(scan: dict) -> str:
    """Generate skills/running-e2e-tests/SKILL.md."""
    repo = scan["repo"]
    lang = (scan.get("primary_language") or "").lower()
    all_paths = scan.get("tree", [])
    dirs = scan.get("dirs", [])

    e2e_dirs = [d for d in dirs if d.lower() in ("e2e", "integration-tests", "integration", "test/e2e")]
    e2e_paths = [p for p in all_paths if any(seg in p.lower() for seg in ("e2e", "integration-test", "integration_test"))]
    has_kind = any("kind" in p.lower() for p in all_paths)
    has_docker_compose = any("docker-compose" in p.lower() or "compose.yaml" in p.lower() or "compose.yml" in p.lower() for p in all_paths)
    has_makefile = any(p.split("/")[-1] == "Makefile" for p in all_paths)
    hack_scripts = [p for p in all_paths if p.startswith("hack/")]

    lines = [
        "---",
        "name: running-e2e-tests",
        "description: Use when verifying cross-component behavior, debugging CI e2e failures, or testing deployment pipelines. Use when integration tests fail or a PR changes multiple services.",
        "---",
        "",
        "# Running E2E / Integration Tests",
        "",
    ]

    if e2e_dirs:
        lines += ["## E2E Test Locations", ""]
        for d in e2e_dirs:
            lines += [f"- `{d}/`"]
        lines += [""]

    if has_kind:
        lines += [
            "## Kind Cluster Setup",
            "",
            "This repo uses [kind](https://kind.sigs.k8s.io/) for local Kubernetes testing.",
            "",
            "```bash",
            "# Create a kind cluster (check hack/ or Makefile for project-specific config)",
            "kind create cluster --name test-cluster",
            "```",
            "",
            "Tear down after testing:",
            "```bash",
            "kind delete cluster --name test-cluster",
            "```",
            "",
        ]

    if has_docker_compose:
        lines += [
            "## Docker Compose",
            "",
            "```bash",
            "docker-compose up -d",
            "# run tests",
            "docker-compose down",
            "```",
            "",
        ]

    if has_makefile:
        lines += [
            "## Makefile Targets",
            "",
            "Check available targets:",
            "```bash",
            "make help  # or: grep -E '^[a-zA-Z_-]+:' Makefile",
            "```",
            "",
            "Common e2e-related targets to look for: `make e2e`, `make integration`, `make test-e2e`",
            "",
        ]

    if hack_scripts:
        lines += ["## Hack Scripts", ""]
        for s in hack_scripts[:10]:
            lines += [f"- `{s}`"]
        lines += ["", "Check these scripts for cluster setup, test data seeding, or environment preparation.", ""]

    if "go" in lang:
        lines += [
            "## Running Go Integration Tests",
            "",
            "```bash",
            "# Many Go projects use build tags for integration tests",
            "go test -tags=integration ./...",
            "```",
            "",
        ]

    lines += [
        "## Tips",
        "",
        "- E2E tests may require a running cluster or external services",
        "- Check CI workflow files for the exact setup steps used in automated runs",
        "- Clean up test resources after running to avoid state leakage",
        "",
        "## Output Format",
        "",
        "When reporting e2e results, use:",
        "",
        "```markdown",
        "## E2E Test Results",
        "",
        "**Test suite:** <name>",
        "**Status:** PASS / FAIL",
        "**Failed tests:** <test names>",
        "**Category:** A (test code) / B (app code) / C (infra/flaky)",
        "**Root cause:** <analysis>",
        "**Suggested fix:** <file and change>",
        "```",
        "",
    ]

    return "\n".join(lines)


def generate_skill_definition_of_done(scan: dict, intelligence: dict | None = None) -> str:
    """Generate skills/definition-of-done/SKILL.md."""
    repo = scan["repo"]
    cmds = _infer_commands(scan)
    ci_workflows = scan.get("ci_workflows", [])
    linter_files = scan.get("linter_files", [])

    lines = [
        "---",
        "name: definition-of-done",
        "description: Use when preparing a PR for review, checking if a change is complete, or an agent needs to verify its own work before submitting. Use when you need the PR checklist.",
        "---",
        "",
        "# Definition of Done",
        "",
        "Before submitting a PR, ensure all items are checked:",
        "",
        "## Code Quality",
        "",
        "- [ ] Code follows existing patterns and conventions in this repository",
        "- [ ] No commented-out code or debug statements left behind",
        "- [ ] Functions and variables have clear, descriptive names",
        "",
        "## Testing",
        "",
    ]

    if cmds["test"]:
        lines += [f"- [ ] All tests pass: `{cmds['test'][0]}`"]
    else:
        lines += ["- [ ] All existing tests pass"]
    lines += [
        "- [ ] New functionality has corresponding test coverage",
        "- [ ] Edge cases and error paths are tested",
        "",
    ]

    if cmds["lint"] or linter_files:
        lines += ["## Linting", ""]
        if cmds["lint"]:
            lines += [f"- [ ] Linter passes: `{cmds['lint'][0]}`"]
        else:
            lines += ["- [ ] Code passes all configured linters"]
        lines += [""]

    if ci_workflows:
        lines += ["## CI Checks", ""]
        lines += ["- [ ] All CI workflows pass:"]
        for w in ci_workflows[:8]:
            lines += [f"  - {w}"]
        lines += [""]

    lines += [
        "## Documentation",
        "",
        "- [ ] Public APIs or user-facing changes are documented",
        "- [ ] README updated if behavior changes",
        "- [ ] Commit messages are clear and follow project conventions",
        "",
        "## PR Hygiene",
        "",
        "- [ ] PR is focused on a single concern",
        "- [ ] PR description explains WHAT changed and WHY",
        "- [ ] No unrelated changes bundled in",
        "",
    ]

    if intelligence and intelligence.get("patterns"):
        lines += ["## Team Review Patterns", "", "Based on historical review analysis, reviewers commonly flag:", ""]
        for p in intelligence["patterns"][:5]:
            lines += [f"- {p['pattern']}"]
        lines += [""]

    return "\n".join(lines)


def generate_skill_debugging_guide(scan: dict) -> str:
    """Generate skills/debugging-guide/SKILL.md."""
    repo = scan["repo"]
    lang = (scan.get("primary_language") or "").lower()
    all_paths = scan.get("tree", [])

    has_dockerfile = any(p.split("/")[-1].lower() in ("dockerfile", "containerfile") for p in all_paths)
    has_k8s = any(seg in p.lower() for p in all_paths for seg in ("deploy", "kustomize", "helm", "manifest"))
    log_files = [p for p in all_paths if "log" in p.lower() and ("config" in p.lower() or "setup" in p.lower())]
    env_files = [p for p in all_paths if p.split("/")[-1].startswith(".env")]

    lines = [
        "---",
        "name: debugging-guide",
        "description: Use when investigating bugs, unexpected behavior, test failures, or CI errors. Use when logs show errors, tests fail intermittently, or the application crashes.",
        "---",
        "",
        "# Debugging Guide",
        "",
        "## General Approach",
        "",
        "1. Reproduce the issue with a minimal test case",
        "2. Check logs for error messages and stack traces",
        "3. Use a debugger or add targeted logging",
        "4. Verify the fix with a test before submitting",
        "",
    ]

    if "go" in lang:
        lines += [
            "## Go Debugging",
            "",
            "Use delve for interactive debugging:",
            "```bash",
            "dlv test ./path/to/package -- -test.run TestName",
            "```",
            "",
            "Enable verbose logging:",
            "```bash",
            "go test -v -count=1 ./...",
            "```",
            "",
            "Profile a slow test:",
            "```bash",
            "go test -cpuprofile cpu.prof -memprofile mem.prof ./...",
            "```",
            "",
        ]
    elif "python" in lang:
        lines += [
            "## Python Debugging",
            "",
            "Drop into a debugger at a specific point:",
            "```python",
            "import pdb; pdb.set_trace()  # or: breakpoint()",
            "```",
            "",
            "Run pytest with output visible:",
            "```bash",
            "pytest -s -v path/to/test_file.py",
            "```",
            "",
            "Debug a specific test:",
            "```bash",
            "pytest --pdb path/to/test_file.py::test_name",
            "```",
            "",
        ]
    elif "typescript" in lang or "javascript" in lang:
        lines += [
            "## Node.js Debugging",
            "",
            "Run with inspector:",
            "```bash",
            "node --inspect-brk dist/index.js",
            "```",
            "",
            "Then open `chrome://inspect` in Chrome.",
            "",
        ]

    if has_dockerfile:
        lines += [
            "## Container Debugging",
            "",
            "Build and run locally:",
            "```bash",
            "docker build -t debug-image .",
            "docker run -it --entrypoint /bin/sh debug-image",
            "```",
            "",
            "Check container logs:",
            "```bash",
            "docker logs <container-id>",
            "```",
            "",
        ]

    if has_k8s:
        lines += [
            "## Kubernetes Debugging",
            "",
            "Check pod status and logs:",
            "```bash",
            "kubectl get pods -n <namespace>",
            "kubectl logs -f <pod-name> -n <namespace>",
            "kubectl describe pod <pod-name> -n <namespace>",
            "```",
            "",
            "Exec into a running pod:",
            "```bash",
            "kubectl exec -it <pod-name> -n <namespace> -- /bin/sh",
            "```",
            "",
        ]

    if env_files:
        lines += ["## Environment Variables", ""]
        for f in env_files[:5]:
            lines += [f"- Check `{f}` for configuration settings"]
        lines += ["", "Missing or incorrect environment variables are a common source of bugs.", ""]

    lines += [
        "## Common Issues",
        "",
        "- **Tests pass locally but fail in CI**: Check for environment differences, missing env vars, or timing-dependent tests",
        "- **Flaky tests**: Look for shared state, race conditions, or network dependencies",
        "- **Build failures**: Verify dependency versions match what CI uses",
        "",
    ]

    return "\n".join(lines)


def generate_skill_local_dev_setup(scan: dict) -> str:
    """Generate skills/local-dev-setup/SKILL.md."""
    repo = scan["repo"]
    owner = scan["owner"]
    lang = (scan.get("primary_language") or "").lower()
    cmds = _infer_commands(scan)
    all_paths = scan.get("tree", [])
    dep_files = scan.get("dep_files", [])

    has_kind = any("kind" in p.lower() for p in all_paths)
    has_docker_compose = any("docker-compose" in p.lower() or "compose.yaml" in p.lower() or "compose.yml" in p.lower() for p in all_paths)
    has_makefile = any(p.split("/")[-1] == "Makefile" for p in all_paths)
    hack_scripts = [p for p in all_paths if p.startswith("hack/")]
    has_dockerfile = any(p.split("/")[-1].lower() in ("dockerfile", "containerfile") for p in all_paths)

    lines = [
        "---",
        "name: local-dev-setup",
        "description: Use when onboarding to this repo, cloning for the first time, resetting a dev environment, or an agent needs to set up a working local instance.",
        "---",
        "",
        "# Local Development Setup",
        "",
        "## Prerequisites",
        "",
    ]

    prereqs = []
    if "go" in lang:
        prereqs += ["- [Go](https://go.dev/dl/) (check `go.mod` for minimum version)"]
    if "python" in lang:
        prereqs += ["- [Python 3](https://www.python.org/downloads/) (check `pyproject.toml` or `setup.cfg` for minimum version)"]
    if "typescript" in lang or "javascript" in lang:
        prereqs += ["- [Node.js](https://nodejs.org/) (check `package.json` engines field)"]
    if "rust" in lang:
        prereqs += ["- [Rust](https://rustup.rs/)"]
    if has_kind:
        prereqs += ["- [kind](https://kind.sigs.k8s.io/) (for local Kubernetes cluster)"]
    if has_docker_compose or has_dockerfile:
        prereqs += ["- [Docker](https://docs.docker.com/get-docker/)"]
    prereqs += ["- [Git](https://git-scm.com/)"]

    lines += prereqs + [""]

    lines += [
        "## Clone & Setup",
        "",
        "```bash",
        f"git clone https://github.com/{owner}/{repo}.git",
        f"cd {repo}",
        "```",
        "",
    ]

    if cmds["install"]:
        lines += ["## Install Dependencies", ""]
        for cmd in cmds["install"]:
            lines += ["```bash", cmd, "```", ""]

    if cmds["build"]:
        lines += ["## Build", ""]
        for cmd in cmds["build"]:
            lines += ["```bash", cmd, "```", ""]

    if cmds["test"]:
        lines += ["## Verify Setup", "", "Run the test suite to confirm everything works:", ""]
        for cmd in cmds["test"]:
            lines += ["```bash", cmd, "```", ""]

    if has_kind:
        lines += [
            "## Kind Cluster Setup",
            "",
            "```bash",
            "# Create a local Kubernetes cluster",
            "kind create cluster --name dev-cluster",
            "",
            "# Verify it's running",
            "kubectl cluster-info --context kind-dev-cluster",
            "```",
            "",
            "To tear down:",
            "```bash",
            "kind delete cluster --name dev-cluster",
            "```",
            "",
        ]

    if has_docker_compose:
        lines += [
            "## Docker Compose Services",
            "",
            "```bash",
            "docker-compose up -d",
            "```",
            "",
        ]

    if has_makefile:
        lines += [
            "## Makefile",
            "",
            "This project has a Makefile. List available targets:",
            "```bash",
            "make help",
            "```",
            "",
        ]

    if hack_scripts:
        lines += ["## Developer Scripts", "", "Useful scripts in `hack/`:", ""]
        for s in hack_scripts[:8]:
            lines += [f"- `{s}`"]
        lines += [""]

    lines += [
        "## IDE Setup",
        "",
        "If using Cursor or VS Code, the repo may include:",
        "- `.cursor/rules/` -- AI coding rules",
        "- `.vscode/` -- editor settings",
        "- `.editorconfig` -- formatting rules",
        "",
    ]

    return "\n".join(lines)


def generate_bookmarks_md(scan: dict) -> str:
    """Generate BOOKMARKS.md for progressive disclosure (fullsend best practice)."""
    repo = scan["repo"]
    owner = scan["owner"]

    lines = [
        f"# Bookmarks for {owner}/{repo}",
        "",
        "Curated references for agents to load on demand. Each entry describes",
        "what the target contains so agents can decide whether to load it.",
        "",
    ]

    if scan.get("ci_workflows"):
        lines += [
            "## CI/CD",
            "",
        ]
        for w in scan.get("ci_workflows", [])[:5]:
            lines += [f"- `.github/workflows/` — {w}: build, test, and deploy pipeline"]
        lines += [""]

    if scan.get("doc_dirs"):
        lines += ["## Documentation", ""]
        for d in scan.get("doc_dirs", []):
            lines += [f"- `{d}/` — project documentation and guides"]
        lines += [""]

    if scan["key_files"].get("CONTRIBUTING.md"):
        lines += ["- `CONTRIBUTING.md` — how to submit changes, coding standards, PR process", ""]

    if scan["key_files"].get("ARCHITECTURE.md"):
        lines += ["- `ARCHITECTURE.md` — system design, component boundaries, key decisions", ""]

    existing_skills = scan.get("existing_skills", [])
    if existing_skills:
        lines += ["## Agent Skills", ""]
        for skill_path in existing_skills:
            skill_name = skill_path.split("/")[1] if len(skill_path.split("/")) >= 3 else skill_path
            lines += [f"- `{skill_path}` — {skill_name} skill"]
        lines += [""]

    dep_files = scan.get("dep_files", [])
    if dep_files:
        lines += ["## Dependencies", ""]
        for df in dep_files[:5]:
            lines += [f"- `{df}` — dependency manifest"]
        lines += [""]

    return "\n".join(lines)


def generate_claude_skills_readme(scan: dict) -> str:
    """Generate .claude/README.md with symlink instructions for skills discovery."""
    repo = scan["repo"]
    return dedent(f"""\
        # Claude Configuration for {repo}

        ## Agent Skills

        This repository uses [Agent Skills](https://agentskills.io/) stored in the
        `skills/` directory at the repo root.

        To let Claude (and other skills-compatible agents) discover them, create a
        symlink:

        ```bash
        ln -sf ../skills .claude/skills
        ```

        After this, Claude Code and other agents will automatically load the skills
        when working in this repository.

        ## Available Skills

        - **running-tests** -- How to run the test suite
        - **running-e2e-tests** -- How to run e2e/integration tests
        - **definition-of-done** -- PR checklist and review standards
        - **debugging-guide** -- How to debug issues
        - **local-dev-setup** -- Setting up a local dev environment
    """)


# ---------------------------------------------------------------------------
# Generate files -- GAP-FILLING logic
# ---------------------------------------------------------------------------


def generate_files(scan: dict, score_result: dict | None = None, intelligence: dict | None = None) -> dict[str, str]:
    """Return a dict of {filepath: content} for files that should be generated.

    Only produces files that are missing or insufficient. Existing, substantive
    files are NOT overwritten.
    """
    files = {}
    key = scan.get("key_files", {})

    if not key.get("AGENTS.md") or len(key.get("AGENTS.md", "")) < 200:
        files["AGENTS.md"] = generate_agents_md(scan, intelligence)

    if not key.get("CLAUDE.md"):
        files["CLAUDE.md"] = generate_claude_md(scan, intelligence)

    if not key.get("GEMINI.md"):
        files["GEMINI.md"] = generate_gemini_md(scan)

    if not key.get(".github/copilot-instructions.md"):
        files[".github/copilot-instructions.md"] = generate_copilot_instructions(scan)

    if not scan.get("cursor_rules"):
        files[".cursor/rules/repo.mdc"] = generate_cursor_rules(scan, intelligence)

    if not key.get(".codex/config.toml"):
        files[".codex/config.toml"] = generate_codex_config(scan)

    if not key.get("ARCHITECTURE.md"):
        files["ARCHITECTURE.md"] = generate_architecture_md(scan)

    if not key.get("CONTRIBUTING.md"):
        files["CONTRIBUTING.md"] = generate_contributing_md(scan)

    existing_skills = [p for p in scan.get("tree", []) if p.startswith("skills/") and p.endswith("SKILL.md")]
    existing_skill_names = {p.split("/")[1] for p in existing_skills if len(p.split("/")) >= 3}

    if "running-tests" not in existing_skill_names:
        files["skills/running-tests/SKILL.md"] = generate_skill_running_tests(scan)

    if "running-e2e-tests" not in existing_skill_names:
        files["skills/running-e2e-tests/SKILL.md"] = generate_skill_running_e2e_tests(scan)

    if "definition-of-done" not in existing_skill_names:
        files["skills/definition-of-done/SKILL.md"] = generate_skill_definition_of_done(scan, intelligence)

    if "debugging-guide" not in existing_skill_names:
        files["skills/debugging-guide/SKILL.md"] = generate_skill_debugging_guide(scan)

    if "local-dev-setup" not in existing_skill_names:
        files["skills/local-dev-setup/SKILL.md"] = generate_skill_local_dev_setup(scan)

    has_claude_readme = any(p.lower() == ".claude/readme.md" for p in scan.get("tree", []))
    if not has_claude_readme:
        files[".claude/README.md"] = generate_claude_skills_readme(scan)

    if not key.get("BOOKMARKS.md"):
        files["BOOKMARKS.md"] = generate_bookmarks_md(scan)

    return files


# ---------------------------------------------------------------------------
# Draft PR creation via GitHub API
# ---------------------------------------------------------------------------


async def create_draft_pr(
    owner: str,
    repo: str,
    files: dict[str, str],
    branch_name: str = "add-ai-readiness-files",
    base_branch: str | None = None,
) -> dict:
    """Create a branch, commit files, and open a draft PR."""
    if not settings.github_pat:
        return {"error": "GITHUB_PAT not configured"}

    headers = _github_headers()

    async with httpx.AsyncClient(
        base_url=GITHUB_API,
        headers=headers,
        timeout=30,
    ) as client:
        if not base_branch:
            resp = await client.get(f"/repos/{owner}/{repo}")
            if resp.status_code != 200:
                return {"error": f"Cannot access repo: {resp.status_code}"}
            base_branch = resp.json().get("default_branch", "main")

        resp = await client.get(f"/repos/{owner}/{repo}/git/ref/heads/{base_branch}")
        if resp.status_code != 200:
            return {"error": f"Cannot get base branch ref: {resp.status_code}"}
        base_sha = resp.json()["object"]["sha"]

        resp = await client.post(
            f"/repos/{owner}/{repo}/git/refs",
            json={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
        )
        if resp.status_code == 422:
            resp = await client.patch(
                f"/repos/{owner}/{repo}/git/refs/heads/{branch_name}",
                json={"sha": base_sha, "force": True},
            )
        if resp.status_code not in (200, 201):
            return {"error": f"Cannot create branch: {resp.status_code} - {resp.text}"}

        for filepath, content in files.items():
            encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")

            existing = await client.get(
                f"/repos/{owner}/{repo}/contents/{filepath}",
                params={"ref": branch_name},
            )
            body = {
                "message": f"Add {filepath} for AI/agentic readiness",
                "content": encoded,
                "branch": branch_name,
            }
            if existing.status_code == 200:
                body["sha"] = existing.json()["sha"]

            resp = await client.put(
                f"/repos/{owner}/{repo}/contents/{filepath}",
                json=body,
            )
            if resp.status_code not in (200, 201):
                logger.warning("Failed to create %s: %s", filepath, resp.status_code)

        file_list = ", ".join(f"`{f}`" for f in files.keys())
        skill_files = [f for f in files if f.startswith("skills/")]
        symlink_note = ""
        if skill_files:
            symlink_note = dedent("""\

                ### Agent Skills Setup

                This PR includes [agentskills.io](https://agentskills.io/)-compatible
                skills in `skills/`. To let Claude Code (or other agents) discover them,
                create a symlink after merging:

                ```bash
                mkdir -p .claude && ln -sf ../skills .claude/skills
                ```

                See `.claude/README.md` for details.
            """)
        pr_body = dedent(f"""\
            ## AI Readiness Bootstrap

            This PR adds foundational files to make this repository more accessible
            to AI coding agents (Cursor, Copilot, Codex, Claude, Gemini, etc.).

            ### Files Added
            {file_list}

            ### Why
            These files provide non-redundant, tool-specific context that helps
            AI agents understand repository conventions, build commands, and
            architectural boundaries -- enabling more effective AI-assisted development.

            Generated files follow the gap-filling principle: only information
            not already present in existing documentation is included.
            {symlink_note}
            ---
            *Generated by [Workstream AI Readiness Analyzer](http://localhost:8080)*
        """
        )

        resp = await client.post(
            f"/repos/{owner}/{repo}/pulls",
            json={
                "title": "Add AI agent readiness files",
                "body": pr_body,
                "head": branch_name,
                "base": base_branch,
                "draft": True,
            },
        )
        if resp.status_code not in (200, 201):
            return {"error": f"Failed to create PR: {resp.status_code} - {resp.text}"}

        pr_data = resp.json()
        return {
            "pr_url": pr_data["html_url"],
            "branch": branch_name,
            "pr_number": pr_data["number"],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dir_purpose(dirname: str, tree: list[str]) -> str:
    d = dirname.lower()
    mapping = {
        "src": "# source code",
        "lib": "# library code",
        "pkg": "# packages",
        "cmd": "# command entrypoints",
        "api": "# API definitions",
        "internal": "# internal packages",
        "test": "# tests",
        "tests": "# tests",
        "spec": "# tests/specs",
        "docs": "# documentation",
        "doc": "# documentation",
        "scripts": "# utility scripts",
        "bin": "# binaries/scripts",
        "config": "# configuration",
        "deploy": "# deployment configs",
        "ci": "# CI configuration",
        ".github": "# GitHub config & workflows",
        "hack": "# development scripts",
        "tools": "# tooling",
        "examples": "# examples",
        "vendor": "# vendored dependencies",
        "static": "# static assets",
        "public": "# public assets",
        "components": "# UI components",
        "pages": "# page components",
        "services": "# service layer",
        "models": "# data models",
        "utils": "# utilities",
        "helpers": "# helpers",
        "middleware": "# middleware",
        "controllers": "# controllers",
        "routes": "# routing",
        "migrations": "# DB migrations",
    }
    return mapping.get(d, "")


def _identify_key_dirs(scan: dict) -> list[tuple[str, str]]:
    tree = scan.get("tree", [])
    dirs = scan.get("dirs", [])
    results = []

    for d in sorted(dirs):
        purpose = _dir_purpose(d, tree)
        if purpose:
            count = sum(1 for p in tree if p.startswith(d + "/"))
            results.append((d, f"{purpose.lstrip('# ').capitalize()} ({count} files)"))

    return results[:12]
