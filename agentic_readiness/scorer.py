"""Score a repository's AI/agentic readiness across 5 categories.

Pure logic -- operates on a ScanResult dict from scanner.py with no I/O.
Returns a ScoreResult with per-category breakdowns, findings, and a letter grade.

Scoring rubric (120 raw points, normalized to 100):
  Agent Configuration  30 pts
  Documentation        25 pts
  CI/CD & Quality      25 pts
  Code Structure       20 pts
  Security & Safety    20 pts
"""
from __future__ import annotations

import re

RAW_MAX = 120


def score_repo(scan: dict) -> dict:
    """Score a scanned repo and return a ScoreResult dict."""
    cats = {
        "agent_config": _score_agent_config(scan),
        "documentation": _score_documentation(scan),
        "ci_quality": _score_ci_quality(scan),
        "code_structure": _score_code_structure(scan),
        "security": _score_security(scan),
    }

    raw_total = sum(c["score"] for c in cats.values())
    normalized = round(raw_total * 100 / RAW_MAX)
    grade = _letter_grade(normalized)
    recs = _build_recommendations(cats, scan)

    return {
        "total": normalized,
        "raw_total": raw_total,
        "raw_max": RAW_MAX,
        "grade": grade,
        "categories": cats,
        "recommendations": recs,
    }


def _finding(present: bool, label: str, pts: int) -> dict:
    return {"present": present, "label": label, "points": pts}


# ---------------------------------------------------------------------------
# Agent Configuration (30 pts)
# ---------------------------------------------------------------------------

def _score_agent_config(scan: dict) -> dict:
    score = 0
    findings = []

    agents_md = scan["key_files"].get("AGENTS.md", "")
    if agents_md and len(agents_md) > 500:
        findings.append(_finding(True, "AGENTS.md present and substantive", 10))
        score += 10
    elif agents_md:
        findings.append(_finding(True, "AGENTS.md present but minimal", 5))
        score += 5
    else:
        findings.append(_finding(False, "AGENTS.md missing", 0))

    claude_md = scan["key_files"].get("CLAUDE.md", "")
    if claude_md:
        findings.append(_finding(True, "CLAUDE.md present", 3))
        score += 3
    else:
        findings.append(_finding(False, "CLAUDE.md missing", 0))

    gemini_md = scan["key_files"].get("GEMINI.md", "")
    if gemini_md:
        findings.append(_finding(True, "GEMINI.md present", 2))
        score += 2
    else:
        findings.append(_finding(False, "GEMINI.md missing", 0))

    cursor_rules = scan.get("cursor_rules", [])
    if cursor_rules:
        findings.append(_finding(True, f".cursor/rules/ directory ({len(cursor_rules)} file{'s' if len(cursor_rules) != 1 else ''})", 5))
        score += 5
    else:
        findings.append(_finding(False, ".cursor/rules/ not found", 0))

    copilot = scan["key_files"].get(".github/copilot-instructions.md", "")
    if copilot:
        findings.append(_finding(True, ".github/copilot-instructions.md present", 3))
        score += 3
    else:
        findings.append(_finding(False, ".github/copilot-instructions.md missing", 0))

    doc_dirs = scan.get("doc_dirs", [])
    if doc_dirs:
        findings.append(_finding(True, f"Structured docs/ directory ({', '.join(doc_dirs)})", 5))
        score += 5
    else:
        findings.append(_finding(False, "No docs/ directory", 0))

    codex_cfg = scan["key_files"].get(".codex/config.toml", "")
    if codex_cfg:
        findings.append(_finding(True, ".codex/config.toml present", 2))
        score += 2
    else:
        findings.append(_finding(False, ".codex/config.toml missing", 0))

    return {"score": min(score, 30), "max": 30, "findings": findings}


# ---------------------------------------------------------------------------
# Documentation (25 pts)
# ---------------------------------------------------------------------------

def _score_documentation(scan: dict) -> dict:
    score = 0
    findings = []

    readme = scan["key_files"].get("README.md", "")
    if readme:
        if len(readme) > 1000:
            findings.append(_finding(True, "README.md is substantive", 8))
            score += 8
        else:
            findings.append(_finding(True, "README.md exists but is short", 4))
            score += 4

        has_build_cmds = bool(re.search(
            r"(?i)(go\s+(build|test|run|mod)|npm\s+(install|test|run)|"
            r"pip\s+install|cargo\s+(build|test)|make\s+\w+|pytest|"
            r"mvn\s+|gradle\s+|yarn\s+(install|test))",
            readme
        ))
        if has_build_cmds:
            bonus = min(2, max(0, 8 - score))
            if bonus > 0:
                findings.append(_finding(True, "README contains build/test commands", bonus))
                score += bonus
    else:
        findings.append(_finding(False, "README.md missing", 0))

    arch = scan["key_files"].get("ARCHITECTURE.md", "")
    if arch:
        findings.append(_finding(True, "ARCHITECTURE.md present", 7))
        score += 7
    else:
        findings.append(_finding(False, "ARCHITECTURE.md missing", 0))

    contrib = scan["key_files"].get("CONTRIBUTING.md", "")
    if contrib:
        findings.append(_finding(True, "CONTRIBUTING.md present", 5))
        score += 5
    else:
        findings.append(_finding(False, "CONTRIBUTING.md missing", 0))

    tree = scan.get("tree", [])
    extra_docs = [p for p in tree if p.lower().startswith("docs/") and p.endswith(".md")]
    if len(extra_docs) >= 3:
        findings.append(_finding(True, f"Additional docs ({len(extra_docs)} markdown files in docs/)", 5))
        score += 5
    elif extra_docs:
        findings.append(_finding(True, f"Some docs ({len(extra_docs)} file(s) in docs/)", 2))
        score += 2
    else:
        findings.append(_finding(False, "No additional documentation in docs/", 0))

    return {"score": min(score, 25), "max": 25, "findings": findings}


# ---------------------------------------------------------------------------
# CI/CD & Quality (25 pts)
# ---------------------------------------------------------------------------

def _score_ci_quality(scan: dict) -> dict:
    score = 0
    findings = []

    if scan.get("has_ci"):
        n = len(scan.get("ci_workflows", []))
        findings.append(_finding(True, f"GitHub Actions ({n} workflow{'s' if n != 1 else ''})", 8))
        score += 8
    else:
        findings.append(_finding(False, "No GitHub Actions workflows", 0))

    linters = scan.get("linter_files", [])
    if len(linters) >= 2:
        findings.append(_finding(True, f"Linter/formatter configs ({len(linters)} found)", 7))
        score += 7
    elif linters:
        findings.append(_finding(True, f"Linter config ({linters[0]})", 4))
        score += 4
    else:
        findings.append(_finding(False, "No linter/formatter configuration", 0))

    test_dirs = scan.get("test_dirs", [])
    if test_dirs:
        findings.append(_finding(True, f"Test directories ({', '.join(test_dirs[:3])})", 5))
        score += 5
    else:
        tree = scan.get("tree", [])
        test_files = [p for p in tree if "_test." in p or "test_" in p or ".spec." in p or ".test." in p]
        if test_files:
            findings.append(_finding(True, f"Test files found ({len(test_files)} files)", 3))
            score += 3
        else:
            findings.append(_finding(False, "No test files found", 0))

    codeowners = scan["key_files"].get("CODEOWNERS", "")
    if codeowners:
        findings.append(_finding(True, "CODEOWNERS file present", 5))
        score += 5
    else:
        findings.append(_finding(False, "CODEOWNERS missing", 0))

    return {"score": min(score, 25), "max": 25, "findings": findings}


# ---------------------------------------------------------------------------
# Code Structure (20 pts)
# ---------------------------------------------------------------------------

def _score_code_structure(scan: dict) -> dict:
    score = 0
    findings = []

    dirs = scan.get("dirs", [])
    tree = scan.get("tree", [])
    root_files = [p for p in tree if "/" not in p]
    nested_ratio = 1 - (len(root_files) / max(len(tree), 1))

    if len(dirs) >= 3 and nested_ratio > 0.5:
        findings.append(_finding(True, f"Well-organized layout ({len(dirs)} top-level dirs)", 6))
        score += 6
    elif len(dirs) >= 2:
        findings.append(_finding(True, f"Basic directory structure ({len(dirs)} dirs)", 3))
        score += 3
    else:
        findings.append(_finding(False, "Flat or minimal directory structure", 0))

    license_file = scan["key_files"].get("LICENSE", "")
    if license_file:
        findings.append(_finding(True, "LICENSE file present", 4))
        score += 4
    else:
        findings.append(_finding(False, "LICENSE missing", 0))

    gitignore = scan["key_files"].get(".gitignore", "")
    if gitignore:
        findings.append(_finding(True, ".gitignore present", 3))
        score += 3
    else:
        findings.append(_finding(False, ".gitignore missing", 0))

    dep_files = scan.get("dep_files", [])
    if dep_files:
        findings.append(_finding(True, f"Dependency management ({', '.join(p.split('/')[-1] for p in dep_files[:3])})", 4))
        score += 4
    else:
        findings.append(_finding(False, "No dependency management file", 0))

    structured = scan.get("structured_dirs", [])
    if structured:
        findings.append(_finding(True, f"Separation of concerns ({', '.join(structured[:4])})", 3))
        score += 3
    else:
        findings.append(_finding(False, "No standard structural directories (src/, pkg/, lib/, etc.)", 0))

    return {"score": min(score, 20), "max": 20, "findings": findings}


# ---------------------------------------------------------------------------
# Security & Safety (20 pts) -- NEW
# ---------------------------------------------------------------------------

def _score_security(scan: dict) -> dict:
    score = 0
    findings = []

    secrets_in_tree = scan.get("secrets_in_tree", [])
    if not secrets_in_tree:
        findings.append(_finding(True, "No secret files committed (.env, credentials, keys)", 5))
        score += 5
    else:
        findings.append(_finding(False, f"Potential secret files in repo: {', '.join(secrets_in_tree[:3])}", 0))

    if scan.get("gitignore_covers_secrets"):
        findings.append(_finding(True, ".gitignore covers secret patterns", 3))
        score += 3
    else:
        findings.append(_finding(False, ".gitignore does not cover common secret patterns", 0))

    if scan.get("has_dependabot") or scan.get("has_renovate"):
        tool = "Dependabot" if scan.get("has_dependabot") else "Renovate"
        findings.append(_finding(True, f"{tool} configured for dependency updates", 4))
        score += 4
    else:
        findings.append(_finding(False, "No Dependabot or Renovate configured", 0))

    if not scan.get("has_secrets_in_content"):
        findings.append(_finding(True, "No hardcoded tokens/keys detected", 5))
        score += 5
    else:
        findings.append(_finding(False, "Possible hardcoded tokens/keys detected in files", 0))

    security_md = scan["key_files"].get("SECURITY.md", "")
    if security_md:
        findings.append(_finding(True, "SECURITY.md present", 3))
        score += 3
    else:
        findings.append(_finding(False, "SECURITY.md missing", 0))

    return {"score": min(score, 20), "max": 20, "findings": findings}


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------

def _letter_grade(normalized: int) -> str:
    if normalized >= 90:
        return "A"
    if normalized >= 75:
        return "B"
    if normalized >= 60:
        return "C"
    if normalized >= 40:
        return "D"
    return "F"


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

def _build_recommendations(categories: dict, scan: dict) -> list[dict]:
    recs = []

    agent = categories["agent_config"]
    if not scan["key_files"].get("AGENTS.md"):
        recs.append({
            "priority": "high",
            "text": "Add an AGENTS.md file to guide AI agents through your codebase",
            "impact": "+8 pts",
        })

    if not scan["key_files"].get("CLAUDE.md"):
        recs.append({
            "priority": "medium",
            "text": "Add CLAUDE.md with imperative commands for Claude Code",
            "impact": "+3 pts",
        })

    if not scan.get("cursor_rules"):
        recs.append({
            "priority": "medium",
            "text": "Add .cursor/rules/ directory with project-specific rules",
            "impact": "+4 pts",
        })

    if not scan["key_files"].get(".github/copilot-instructions.md"):
        recs.append({
            "priority": "low",
            "text": "Add .github/copilot-instructions.md for Copilot code review",
            "impact": "+3 pts",
        })

    docs = categories["documentation"]
    if not scan["key_files"].get("ARCHITECTURE.md"):
        recs.append({
            "priority": "high",
            "text": "Add ARCHITECTURE.md describing system structure and key design decisions",
            "impact": "+6 pts",
        })
    if not scan["key_files"].get("CONTRIBUTING.md"):
        recs.append({
            "priority": "medium",
            "text": "Add CONTRIBUTING.md with build, test, and submission instructions",
            "impact": "+4 pts",
        })

    ci = categories["ci_quality"]
    if not scan.get("has_ci"):
        recs.append({
            "priority": "high",
            "text": "Set up GitHub Actions for CI/CD (lint, test, build)",
            "impact": "+7 pts",
        })
    if not scan["key_files"].get("CODEOWNERS"):
        recs.append({
            "priority": "low",
            "text": "Add a CODEOWNERS file for automatic review assignment",
            "impact": "+4 pts",
        })

    structure = categories["code_structure"]
    if not scan.get("dep_files"):
        recs.append({
            "priority": "medium",
            "text": "Add explicit dependency management (go.mod, package.json, etc.)",
            "impact": "+3 pts",
        })

    security = categories["security"]
    if scan.get("secrets_in_tree"):
        recs.append({
            "priority": "critical",
            "text": "Remove committed secret files (.env, credentials) from the repository",
            "impact": "+4 pts",
        })
    if not scan.get("gitignore_covers_secrets"):
        recs.append({
            "priority": "high",
            "text": "Update .gitignore to cover .env, credentials, and key files",
            "impact": "+3 pts",
        })
    if not scan.get("has_dependabot") and not scan.get("has_renovate"):
        recs.append({
            "priority": "medium",
            "text": "Configure Dependabot or Renovate for automated dependency updates",
            "impact": "+3 pts",
        })
    if not scan["key_files"].get("SECURITY.md"):
        recs.append({
            "priority": "low",
            "text": "Add SECURITY.md with vulnerability reporting instructions",
            "impact": "+3 pts",
        })

    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    recs.sort(key=lambda r: priority_order.get(r["priority"], 4))
    return recs
