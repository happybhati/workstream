"""Score a repository's AI/agentic readiness across 6 categories.

Pure logic -- operates on a ScanResult dict from scanner.py with no I/O.
Returns a ScoreResult with per-category breakdowns, findings, and a letter grade.

Research-backed scoring rubric (170 raw points, normalized to 100):
  Agent Configuration  35 pts  (AGENTS.md quality, line limits, section completeness)
  Documentation        25 pts
  CI/CD & Quality      30 pts  (type checkers, pre-commit hooks)
  Code Structure       20 pts
  Security & Safety    25 pts  (agent config risk scanning)
  Fullsend Readiness   35 pts  (skill quality, symlinks, deeper backpressure)

References:
  - arXiv 2601.20404: AGENTS.md reduces agent runtime by 28.6%
  - agents.md standard: 6 core sections, <100 lines recommended
  - Anthropic CLAUDE.md docs: <200 lines for >90% adherence
  - agentskills.io spec: YAML frontmatter, "Use when..." descriptions
  - AgentLint: security scanning for agent config files
"""

from __future__ import annotations

import re

RAW_MAX = 170


def score_repo(scan: dict) -> dict:
    """Score a scanned repo and return a ScoreResult dict."""
    cats = {
        "agent_config": _score_agent_config(scan),
        "documentation": _score_documentation(scan),
        "ci_quality": _score_ci_quality(scan),
        "code_structure": _score_code_structure(scan),
        "security": _score_security(scan),
        "fullsend_readiness": _score_fullsend_readiness(scan),
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
# Agent Configuration (35 pts)
# ---------------------------------------------------------------------------


def _score_agent_config(scan: dict) -> dict:
    score = 0
    findings = []

    agents_analysis = scan.get("agents_md_analysis", {})
    agents_md = scan["key_files"].get("AGENTS.md", "")
    if agents_analysis.get("present"):
        lines = agents_analysis.get("lines", 0)
        section_count = agents_analysis.get("section_count", 0)
        quality = agents_analysis.get("quality", "unknown")

        if quality == "verbose":
            findings.append(_finding(True, f"AGENTS.md present but verbose ({lines} lines, <100 recommended)", 5))
            score += 5
        elif section_count >= 4 and lines <= 100:
            findings.append(
                _finding(
                    True,
                    f"AGENTS.md well-structured ({lines} lines, {section_count} sections)",
                    12,
                )
            )
            score += 12
        elif section_count >= 2:
            findings.append(
                _finding(
                    True,
                    f"AGENTS.md has {section_count} sections (4+ recommended per standard)",
                    8,
                )
            )
            score += 8
        elif len(agents_md) > 500:
            findings.append(_finding(True, "AGENTS.md present and substantive", 7))
            score += 7
        else:
            findings.append(_finding(True, "AGENTS.md present but minimal", 4))
            score += 4
    else:
        findings.append(_finding(False, "AGENTS.md missing (reduces agent runtime 28.6% per arXiv 2601.20404)", 0))

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
        findings.append(
            _finding(
                True,
                f".cursor/rules/ directory ({len(cursor_rules)} file{'s' if len(cursor_rules) != 1 else ''})",
                5,
            )
        )
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

    claude_rules = scan.get("claude_rules", [])
    if claude_rules:
        findings.append(_finding(True, f".claude/rules/ directory ({len(claude_rules)} rules)", 3))
        score += 3

    return {"score": min(score, 35), "max": 35, "findings": findings}


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

        has_build_cmds = bool(
            re.search(
                r"(?i)(go\s+(build|test|run|mod)|npm\s+(install|test|run)|"
                r"pip\s+install|cargo\s+(build|test)|make\s+\w+|pytest|"
                r"mvn\s+|gradle\s+|yarn\s+(install|test))",
                readme,
            )
        )
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
# CI/CD & Quality (30 pts)
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

    type_checkers = scan.get("type_checker_files", [])
    if type_checkers:
        names = [p.split("/")[-1] for p in type_checkers[:3]]
        findings.append(_finding(True, f"Type checker configured ({', '.join(names)})", 5))
        score += 5
    else:
        findings.append(_finding(False, "No type checker (tsconfig, mypy, pyright)", 0))

    pre_commit = scan.get("pre_commit_files", [])
    if pre_commit:
        findings.append(_finding(True, "Pre-commit hooks configured", 5))
        score += 5
    else:
        findings.append(_finding(False, "No pre-commit hooks (.pre-commit-config.yaml, .husky)", 0))

    return {"score": min(score, 30), "max": 30, "findings": findings}


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
        findings.append(
            _finding(
                True,
                f"Dependency management ({', '.join(p.split('/')[-1] for p in dep_files[:3])})",
                4,
            )
        )
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
# Security & Safety (25 pts) -- agent config risk scanning
# ---------------------------------------------------------------------------


def _score_security(scan: dict) -> dict:
    score = 0
    findings = []

    secrets_in_tree = scan.get("secrets_in_tree", [])
    if not secrets_in_tree:
        findings.append(_finding(True, "No secret files committed (.env, credentials, keys)", 5))
        score += 5
    else:
        findings.append(
            _finding(
                False,
                f"Potential secret files in repo: {', '.join(secrets_in_tree[:3])}",
                0,
            )
        )

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

    agent_risks = scan.get("agent_config_risks", [])
    if not agent_risks:
        findings.append(_finding(True, "No risky patterns in agent config files (AgentLint check)", 5))
        score += 5
    else:
        risk_summary = f"{len(agent_risks)} risky pattern(s): {agent_risks[0]['pattern'][:40]}"
        findings.append(_finding(False, f"Agent config security risks found — {risk_summary}", 0))

    return {"score": min(score, 25), "max": 25, "findings": findings}


# ---------------------------------------------------------------------------
# Fullsend Readiness (35 pts) -- skills, backpressure, context quality
# ---------------------------------------------------------------------------


def _score_fullsend_readiness(scan: dict) -> dict:
    """Score readiness for fullsend agentic SDLC platform.

    Based on fullsend-ai/fullsend repo-readiness and codebase-context docs:
    - Agent skills (agentskills.io spec) with quality assessment
    - Backpressure mechanisms (linters, type checkers, pre-commit, tests in CI)
    - Context file quality (CLAUDE.md brevity, BOOKMARKS.md)
    - Skill symlinks for agent discovery
    - CODEOWNERS for human approval paths
    """
    score = 0
    findings = []

    existing_skills = scan.get("existing_skills", [])
    if len(existing_skills) >= 3:
        findings.append(_finding(True, f"Agent Skills directory ({len(existing_skills)} skills)", 8))
        score += 8
    elif existing_skills:
        findings.append(
            _finding(
                True,
                f"Agent Skills directory ({len(existing_skills)} skill{'s' if len(existing_skills) != 1 else ''})",
                4,
            )
        )
        score += 4
    else:
        findings.append(_finding(False, "No skills/ directory with SKILL.md files", 0))

    skill_symlinks = scan.get("skill_symlinks", [])
    if skill_symlinks:
        findings.append(
            _finding(True, f"Skills symlinked for agent discovery ({len(skill_symlinks)} in .claude/.cursor)", 3)
        )
        score += 3
    elif existing_skills:
        findings.append(_finding(False, "Skills exist but not symlinked to .claude/ or .cursor/ for discovery", 0))

    ci_commands = scan.get("ci_commands", {})
    bp_count = 0
    bp_details = []
    if ci_commands.get("test"):
        bp_count += 1
        bp_details.append("CI tests")
    if ci_commands.get("lint"):
        bp_count += 1
        bp_details.append("CI lint")
    if scan.get("linter_files"):
        bp_count += 1
        bp_details.append("linter configs")
    if scan.get("test_dirs"):
        bp_count += 1
        bp_details.append("test dirs")
    if scan.get("type_checker_files"):
        bp_count += 1
        bp_details.append("type checker")
    if scan.get("pre_commit_files"):
        bp_count += 1
        bp_details.append("pre-commit hooks")

    if bp_count >= 4:
        findings.append(_finding(True, f"Strong backpressure ({bp_count}: {', '.join(bp_details[:4])})", 8))
        score += 8
    elif bp_count >= 2:
        findings.append(_finding(True, f"Moderate backpressure ({bp_count}: {', '.join(bp_details)})", 5))
        score += 5
    elif bp_count >= 1:
        findings.append(_finding(True, f"Minimal backpressure ({bp_details[0]})", 2))
        score += 2
    else:
        findings.append(_finding(False, "No backpressure mechanisms (tests/linters in CI)", 0))

    claude_md = scan["key_files"].get("CLAUDE.md", "")
    claude_md_lines = scan.get("claude_md_lines", 0)
    if claude_md and claude_md_lines <= 60:
        findings.append(_finding(True, f"CLAUDE.md is concise ({claude_md_lines} lines, ≤60 recommended)", 5))
        score += 5
    elif claude_md and claude_md_lines <= 200:
        findings.append(
            _finding(True, f"CLAUDE.md is moderate ({claude_md_lines} lines, ≤60 ideal, <200 for >90% adherence)", 3)
        )
        score += 3
    elif claude_md:
        findings.append(
            _finding(
                True, f"CLAUDE.md is verbose ({claude_md_lines} lines, >200 hurts adherence per Anthropic docs)", 1
            )
        )
        score += 1
    else:
        findings.append(_finding(False, "No CLAUDE.md for agent context", 0))

    if scan.get("has_bookmarks"):
        findings.append(_finding(True, "BOOKMARKS.md for progressive disclosure", 3))
        score += 3
    else:
        findings.append(_finding(False, "No BOOKMARKS.md for on-demand references", 0))

    codeowners = scan["key_files"].get("CODEOWNERS", "")
    if codeowners:
        findings.append(_finding(True, "CODEOWNERS defines human approval paths", 5))
        score += 5
    else:
        findings.append(_finding(False, "No CODEOWNERS for merge approval paths", 0))

    arch_quality = scan.get("arch_md_quality", {})
    if arch_quality.get("quality") in ("good", "excellent"):
        findings.append(_finding(True, f"ARCHITECTURE.md quality: {arch_quality['quality']}", 3))
        score += 3
    elif arch_quality.get("present"):
        findings.append(_finding(True, "ARCHITECTURE.md present but could be improved", 1))
        score += 1

    return {"score": min(score, 35), "max": 35, "findings": findings}


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

    agents_analysis = scan.get("agents_md_analysis", {})
    if not scan["key_files"].get("AGENTS.md"):
        recs.append(
            {
                "priority": "high",
                "text": "Add AGENTS.md — reduces agent iteration time by 28.6% (arXiv 2601.20404). Include: summary, rules, build/test, style, architecture, security sections",
                "impact": "+12 pts",
            }
        )
    elif agents_analysis.get("quality") == "verbose":
        recs.append(
            {
                "priority": "medium",
                "text": f"Trim AGENTS.md to <100 lines (currently {agents_analysis.get('lines', 0)}) — concise files reduce prompt token waste",
                "impact": "+4 pts",
            }
        )
    elif agents_analysis.get("section_count", 0) < 4:
        missing = set(["summary", "rules", "build", "test", "style", "architecture"]) - set(
            agents_analysis.get("sections_found", [])
        )
        recs.append(
            {
                "priority": "medium",
                "text": f"Add missing AGENTS.md sections: {', '.join(sorted(missing)[:4])}",
                "impact": "+4 pts",
            }
        )

    if not scan["key_files"].get("CLAUDE.md"):
        recs.append(
            {
                "priority": "medium",
                "text": "Add CLAUDE.md with imperative commands for Claude Code (<200 lines for >90% adherence per Anthropic docs)",
                "impact": "+3 pts",
            }
        )

    if not scan.get("cursor_rules"):
        recs.append(
            {
                "priority": "medium",
                "text": "Add .cursor/rules/ directory with project-specific rules",
                "impact": "+5 pts",
            }
        )

    if not scan["key_files"].get(".github/copilot-instructions.md"):
        recs.append(
            {
                "priority": "low",
                "text": "Add .github/copilot-instructions.md for Copilot code review",
                "impact": "+3 pts",
            }
        )

    if not scan["key_files"].get("ARCHITECTURE.md"):
        recs.append(
            {
                "priority": "high",
                "text": "Add ARCHITECTURE.md with headings, code blocks, and API docs — agents use this as primary nav reference",
                "impact": "+7 pts",
            }
        )
    else:
        arch_quality = scan.get("arch_md_quality", {})
        if arch_quality.get("quality") in ("minimal", "unstructured"):
            recs.append(
                {
                    "priority": "medium",
                    "text": f"Improve ARCHITECTURE.md — currently {arch_quality.get('quality')}. Add headings, code blocks, and component descriptions",
                    "impact": "+2 pts",
                }
            )

    if not scan["key_files"].get("CONTRIBUTING.md"):
        recs.append(
            {
                "priority": "medium",
                "text": "Add CONTRIBUTING.md with build, test, and submission instructions",
                "impact": "+5 pts",
            }
        )

    if not scan.get("has_ci"):
        recs.append(
            {
                "priority": "high",
                "text": "Set up GitHub Actions for CI/CD (lint, test, build)",
                "impact": "+8 pts",
            }
        )
    if not scan["key_files"].get("CODEOWNERS"):
        recs.append(
            {
                "priority": "medium",
                "text": "Add CODEOWNERS for automatic review assignment and human approval paths",
                "impact": "+5 pts",
            }
        )

    if not scan.get("type_checker_files"):
        recs.append(
            {
                "priority": "medium",
                "text": "Add type checking (tsconfig.json, mypy.ini, pyrightconfig.json) — agents produce fewer type errors with type checkers as backpressure",
                "impact": "+5 pts",
            }
        )

    if not scan.get("pre_commit_files"):
        recs.append(
            {
                "priority": "low",
                "text": "Add pre-commit hooks (.pre-commit-config.yaml or .husky) — catches agent mistakes before CI",
                "impact": "+5 pts",
            }
        )

    if not scan.get("dep_files"):
        recs.append(
            {
                "priority": "medium",
                "text": "Add explicit dependency management (go.mod, package.json, etc.)",
                "impact": "+4 pts",
            }
        )

    if scan.get("secrets_in_tree"):
        recs.append(
            {
                "priority": "critical",
                "text": "Remove committed secret files (.env, credentials) from the repository",
                "impact": "+5 pts",
            }
        )
    if not scan.get("gitignore_covers_secrets"):
        recs.append(
            {
                "priority": "high",
                "text": "Update .gitignore to cover .env, credentials, and key files",
                "impact": "+3 pts",
            }
        )
    if not scan.get("has_dependabot") and not scan.get("has_renovate"):
        recs.append(
            {
                "priority": "medium",
                "text": "Configure Dependabot or Renovate for automated dependency updates",
                "impact": "+4 pts",
            }
        )
    if not scan["key_files"].get("SECURITY.md"):
        recs.append(
            {
                "priority": "low",
                "text": "Add SECURITY.md with vulnerability reporting instructions",
                "impact": "+3 pts",
            }
        )

    agent_risks = scan.get("agent_config_risks", [])
    if agent_risks:
        recs.append(
            {
                "priority": "critical",
                "text": f"Fix {len(agent_risks)} risky pattern(s) in agent config files (e.g., curl|sh, exposed tokens, rm -rf)",
                "impact": "+5 pts",
            }
        )

    if not scan.get("existing_skills"):
        recs.append(
            {
                "priority": "high",
                "text": "Add agent skills in skills/ directory (agentskills.io spec) — running-tests, debugging-guide, definition-of-done are high-value starting points",
                "impact": "+8 pts",
            }
        )
    elif not scan.get("skill_symlinks") and scan.get("existing_skills"):
        recs.append(
            {
                "priority": "medium",
                "text": "Symlink skills/ into .claude/ or .cursor/ for automatic agent discovery",
                "impact": "+3 pts",
            }
        )

    if not scan.get("has_bookmarks"):
        recs.append(
            {
                "priority": "medium",
                "text": "Add BOOKMARKS.md for progressive disclosure — curated references agents load on demand",
                "impact": "+3 pts",
            }
        )
    claude_md_lines = scan.get("claude_md_lines", 0)
    if claude_md_lines > 200:
        recs.append(
            {
                "priority": "high",
                "text": f"Trim CLAUDE.md to <200 lines (currently {claude_md_lines}) — Anthropic data shows >90% adherence drops above 200 lines",
                "impact": "+4 pts",
            }
        )
    elif claude_md_lines > 60:
        recs.append(
            {
                "priority": "low",
                "text": f"Consider trimming CLAUDE.md to ≤60 lines (currently {claude_md_lines}) for optimal conciseness",
                "impact": "+2 pts",
            }
        )

    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    recs.sort(key=lambda r: priority_order.get(r["priority"], 4))
    return recs
