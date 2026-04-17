"""Tests for agentic_readiness/scorer.py — score calculation edge cases."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentic_readiness.scorer import score_repo


def _empty_scan() -> dict:
    return {
        "repo_url": "https://github.com/test/empty",
        "readme_lines": 0,
        "has_agents_md": False,
        "agents_md_lines": 0,
        "has_claude_md": False,
        "has_gemini_md": False,
        "has_cursor_rules": False,
        "cursor_rules_count": 0,
        "has_copilot_instructions": False,
        "has_codex_config": False,
        "has_docs_dir": False,
        "docs_dir_name": "",
        "has_architecture_md": False,
        "has_contributing_md": False,
        "docs_markdown_count": 0,
        "has_github_actions": False,
        "github_actions_count": 0,
        "has_linter_config": False,
        "linter_configs_found": 0,
        "has_test_dirs": False,
        "test_dir_names": [],
        "has_codeowners": False,
        "top_level_dirs": 1,
        "has_license": False,
        "has_gitignore": False,
        "has_dependency_management": False,
        "dependency_files": [],
        "has_standard_dirs": False,
        "has_secret_files": False,
        "gitignore_covers_secrets": False,
        "has_dependabot": False,
        "has_hardcoded_tokens": False,
        "has_security_md": False,
        "languages": [],
        "file_count": 0,
        "e2e_dirs": [],
        "hack_scripts": [],
        "kind_configs": [],
        "dockerfiles": [],
        "deployment_manifests": [],
        "existing_skills": [],
        "key_files": {},
    }


def _perfect_scan() -> dict:
    scan = _empty_scan()
    scan.update(
        {
            "readme_lines": 100,
            "has_agents_md": True,
            "agents_md_lines": 600,
            "has_claude_md": True,
            "has_gemini_md": True,
            "has_cursor_rules": True,
            "cursor_rules_count": 2,
            "has_copilot_instructions": True,
            "has_codex_config": True,
            "has_docs_dir": True,
            "docs_dir_name": "docs",
            "has_architecture_md": True,
            "has_contributing_md": True,
            "docs_markdown_count": 5,
            "has_github_actions": True,
            "github_actions_count": 3,
            "has_linter_config": True,
            "linter_configs_found": 2,
            "has_test_dirs": True,
            "test_dir_names": ["tests"],
            "has_codeowners": True,
            "top_level_dirs": 8,
            "has_license": True,
            "has_gitignore": True,
            "has_dependency_management": True,
            "dependency_files": ["requirements.txt"],
            "has_standard_dirs": True,
            "has_secret_files": False,
            "gitignore_covers_secrets": True,
            "has_dependabot": True,
            "has_hardcoded_tokens": False,
            "has_security_md": True,
            "cursor_rules": ["repo.mdc"],
            "doc_dirs": ["docs"],
            "key_files": {
                "AGENTS.md": "x" * 600,
                "CLAUDE.md": "claude instructions",
                "GEMINI.md": "gemini instructions",
                "README.md": "A" * 1100 + "\npip install -r requirements.txt\npytest\n",
                ".github/copilot-instructions.md": "copilot instructions content",
                ".codex/config.toml": "[codex]\nsetup = 'make setup'",
                "ARCHITECTURE.md": "architecture overview " * 50,
                "CONTRIBUTING.md": "how to contribute " * 50,
            },
        }
    )
    return scan


def test_empty_repo_scores_low():
    result = score_repo(_empty_scan())
    assert result["total"] <= 20
    assert result["grade"] in ("D", "F")


def test_well_populated_repo_scores_higher_than_empty():
    empty = score_repo(_empty_scan())
    populated = score_repo(_perfect_scan())
    assert populated["total"] > empty["total"]
    assert populated["total"] > 40


def test_score_always_0_to_100():
    for scan_fn in (_empty_scan, _perfect_scan):
        result = score_repo(scan_fn())
        assert 0 <= result["total"] <= 100


def test_categories_sum_to_total():
    result = score_repo(_perfect_scan())
    cat_sum = sum(c["score"] for c in result["categories"].values())
    raw_max = sum(c["max"] for c in result["categories"].values())
    expected = round(cat_sum / raw_max * 100) if raw_max else 0
    assert abs(result["total"] - expected) <= 1


def test_partial_repo():
    scan = _empty_scan()
    scan["readme_lines"] = 50
    scan["has_gitignore"] = True
    scan["has_license"] = True
    result = score_repo(scan)
    assert 5 < result["total"] < 50
