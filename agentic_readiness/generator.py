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
    lang = (scan.get("primary_language") or "").lower()

    lines = [
        f"# {owner}/{repo}",
        "",
    ]

    all_cmds = cmds["install"] + cmds["build"] + cmds["test"] + cmds["lint"]
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
        lines += [f"```bash", f"{cmd}", "```", ""]

    lines += ["## Testing", ""]
    for cmd in cmds["test"]:
        lines += [f"```bash", f"{cmd}", "```", ""]

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
            lines += ["```bash", "python -m venv venv", "source venv/bin/activate",
                      "pip install -r requirements.txt", "```"]
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

            ---
            *Generated by [Workstream AI Readiness Analyzer](http://localhost:8080)*
        """)

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
