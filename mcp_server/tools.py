"""MCP tool implementations for the Release Service MCP server.

All tools read from the shared SQLite database populated by the
collector and analyzer. They never expose secrets or raw tokens.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from config import settings

DB_PATH = settings.db_path

def _load_tracked_repos() -> dict[str, dict]:
    """Load repo metadata from the intelligence DB tables (populated by collection scans).

    Falls back to an empty dict if no repos have been collected yet.
    """
    try:
        db = _get_db()
        rows = db.execute(
            "SELECT DISTINCT repo FROM ri_pull_requests"
        ).fetchall()
        db.close()
        return {r["repo"]: {} for r in rows}
    except Exception:
        return {}


def _get_db() -> sqlite3.Connection:
    """Synchronous DB connection for MCP tools (MCP server runs in its own process)."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Domain Knowledge Tools
# ---------------------------------------------------------------------------

def list_release_repos() -> list[dict]:
    """Return all tracked repositories with metadata from the intelligence DB."""
    tracked = _load_tracked_repos()
    result = []
    for repo in tracked:
        result.append({"repo": repo})
    return result


def get_repo_context(repo: str) -> dict:
    """Return rich context for a specific repository."""
    tracked = _load_tracked_repos()
    if repo not in tracked:
        return {"error": f"Unknown repo: {repo}. Known repos: {list(tracked.keys())}"}

    db = _get_db()
    try:
        # PR stats from review intelligence
        row = db.execute(
            "SELECT COUNT(*) as cnt FROM ri_pull_requests WHERE repo = ?", (repo,)
        ).fetchone()
        pr_count = row["cnt"] if row else 0

        row = db.execute(
            "SELECT COUNT(*) as cnt FROM ri_review_comments c "
            "JOIN ri_pull_requests p ON c.pr_id = p.id WHERE p.repo = ?", (repo,)
        ).fetchone()
        comment_count = row["cnt"] if row else 0

        # Top reviewers for this repo
        rows = db.execute(
            "SELECT c.reviewer, COUNT(*) as cnt FROM ri_review_comments c "
            "JOIN ri_pull_requests p ON c.pr_id = p.id WHERE p.repo = ? "
            "GROUP BY c.reviewer ORDER BY cnt DESC LIMIT 5", (repo,)
        ).fetchall()
        top_reviewers = [{"reviewer": r["reviewer"], "comments": r["cnt"]} for r in rows]

        # Category distribution
        rows = db.execute(
            "SELECT c.category, COUNT(*) as cnt FROM ri_review_comments c "
            "JOIN ri_pull_requests p ON c.pr_id = p.id WHERE p.repo = ? "
            "AND c.category != '' GROUP BY c.category ORDER BY cnt DESC", (repo,)
        ).fetchall()
        categories = {r["category"]: r["cnt"] for r in rows}

        # Recent PRs from dashboard
        rows = db.execute(
            "SELECT number, title, author, state, url, updated_at FROM pull_requests "
            "WHERE repo_full_name = ? ORDER BY updated_at DESC LIMIT 10", (repo,)
        ).fetchall()
        recent_prs = [dict(r) for r in rows]

    finally:
        db.close()

    return {
        "repo": repo,
        "review_intelligence": {
            "merged_prs_analyzed": pr_count,
            "review_comments_collected": comment_count,
            "top_reviewers": top_reviewers,
            "category_distribution": categories,
        },
        "recent_prs": recent_prs,
    }


def get_recent_prs(repo: str, state: str = "open", limit: int = 10) -> list[dict]:
    """Get recent PRs for a repo from the dashboard database."""
    db = _get_db()
    try:
        if state == "all":
            rows = db.execute(
                "SELECT * FROM pull_requests WHERE repo_full_name = ? "
                "ORDER BY updated_at DESC LIMIT ?", (repo, limit)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM pull_requests WHERE repo_full_name = ? AND state = ? "
                "ORDER BY updated_at DESC LIMIT ?", (repo, state, limit)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Review Intelligence Tools
# ---------------------------------------------------------------------------

def get_review_patterns(repo: str = "", category: str = "") -> list[dict]:
    """Get recurring review patterns, optionally filtered by repo and category."""
    db = _get_db()
    try:
        conditions = []
        params = []
        if repo:
            conditions.append("repo = ?")
            params.append(repo)
        if category:
            conditions.append("category = ?")
            params.append(category)
        where = " AND ".join(conditions) if conditions else "1=1"
        rows = db.execute(
            f"SELECT * FROM ri_patterns WHERE {where} ORDER BY frequency DESC LIMIT 50",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


def get_reviewer_profile(reviewer: str) -> dict:
    """Get detailed profile for a specific reviewer."""
    db = _get_db()
    try:
        row = db.execute(
            "SELECT * FROM ri_reviewer_profiles WHERE reviewer = ?", (reviewer,)
        ).fetchone()
        if not row:
            return {"error": f"No profile found for reviewer: {reviewer}"}
        d = dict(row)
        for key in ("top_categories", "common_phrases", "focus_areas"):
            if d.get(key):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    pass

        # Sample recent comments
        rows = db.execute(
            "SELECT c.body, c.file_path, c.category, p.repo, p.title as pr_title "
            "FROM ri_review_comments c JOIN ri_pull_requests p ON c.pr_id = p.id "
            "WHERE c.reviewer = ? ORDER BY c.created_at DESC LIMIT 10", (reviewer,)
        ).fetchall()
        d["recent_comments"] = [dict(r) for r in rows]
        return d
    finally:
        db.close()


def search_past_reviews(query: str, repo: str = "") -> list[dict]:
    """Keyword search over historical review comments."""
    db = _get_db()
    try:
        repo_filter = "AND p.repo = ?" if repo else ""
        params = [f"%{query}%"]
        if repo:
            params.append(repo)
        rows = db.execute(
            f"SELECT c.body, c.reviewer, c.file_path, c.line_number, c.category, "
            f"c.created_at, p.repo, p.title as pr_title, p.number as pr_number "
            f"FROM ri_review_comments c JOIN ri_pull_requests p ON c.pr_id = p.id "
            f"WHERE c.body LIKE ? {repo_filter} "
            f"ORDER BY c.created_at DESC LIMIT 30",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


def get_team_standards() -> dict:
    """Return aggregated coding standards extracted from review patterns."""
    db = _get_db()
    try:
        # Top patterns by frequency
        rows = db.execute(
            "SELECT category, pattern, frequency, example_comment "
            "FROM ri_patterns ORDER BY frequency DESC LIMIT 30"
        ).fetchall()
        patterns = [dict(r) for r in rows]

        # Category distribution across all comments
        rows = db.execute(
            "SELECT category, COUNT(*) as cnt FROM ri_review_comments "
            "WHERE category != '' AND category != 'other' "
            "GROUP BY category ORDER BY cnt DESC"
        ).fetchall()
        distribution = {r["category"]: r["cnt"] for r in rows}

        # Top reviewers
        rows = db.execute(
            "SELECT reviewer, total_comments, focus_areas "
            "FROM ri_reviewer_profiles ORDER BY total_comments DESC LIMIT 10"
        ).fetchall()
        reviewers = []
        for r in rows:
            d = dict(r)
            if d.get("focus_areas"):
                try:
                    d["focus_areas"] = json.loads(d["focus_areas"])
                except (json.JSONDecodeError, TypeError):
                    pass
            reviewers.append(d)

        return {
            "top_patterns": patterns,
            "category_distribution": distribution,
            "top_reviewers": reviewers,
            "summary": _generate_standards_summary(distribution, patterns),
        }
    finally:
        db.close()


def _generate_standards_summary(distribution: dict, patterns: list[dict]) -> str:
    """Generate a human-readable summary of team standards."""
    if not distribution:
        return "No review data collected yet. Run 'workstream collect-reviews' first."

    top_3 = sorted(distribution.items(), key=lambda x: x[1], reverse=True)[:3]
    lines = ["Based on analysis of historical PR reviews, the team prioritizes:\n"]
    for i, (cat, count) in enumerate(top_3, 1):
        cat_label = {
            "bug": "Bug prevention and correctness",
            "error_handling": "Proper error handling",
            "security": "Security practices",
            "testing": "Test coverage",
            "performance": "Performance optimization",
            "concurrency": "Concurrency safety",
            "api_design": "API design consistency",
            "documentation": "Documentation quality",
            "architecture": "Architectural integrity",
        }.get(cat, cat)
        lines.append(f"{i}. {cat_label} ({count} review comments)")

    return "\n".join(lines)


def get_similar_reviews(file_path: str) -> list[dict]:
    """Find past review comments on files with similar paths/extensions."""
    ext = Path(file_path).suffix
    name = Path(file_path).name

    db = _get_db()
    try:
        # First try exact file name match
        rows = db.execute(
            "SELECT c.body, c.reviewer, c.file_path, c.category, c.line_number, "
            "p.repo, p.title as pr_title "
            "FROM ri_review_comments c JOIN ri_pull_requests p ON c.pr_id = p.id "
            "WHERE c.file_path LIKE ? AND c.file_path != '' "
            "ORDER BY c.created_at DESC LIMIT 15",
            (f"%{name}",),
        ).fetchall()

        if len(rows) < 5 and ext:
            # Fall back to extension match
            rows = db.execute(
                "SELECT c.body, c.reviewer, c.file_path, c.category, c.line_number, "
                "p.repo, p.title as pr_title "
                "FROM ri_review_comments c JOIN ri_pull_requests p ON c.pr_id = p.id "
                "WHERE c.file_path LIKE ? AND c.file_path != '' "
                "ORDER BY c.created_at DESC LIMIT 15",
                (f"%{ext}",),
            ).fetchall()

        return [dict(r) for r in rows]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Enhanced Review Tools
# ---------------------------------------------------------------------------

def generate_contextual_review_prompt(pr_id: str) -> dict:
    """Build a review prompt enriched with team context and past patterns.

    This complements the existing reviewer.py prompt with intelligence data.
    """
    db = _get_db()
    try:
        # Get PR info from dashboard DB
        parts = pr_id.split(":")
        if len(parts) >= 3:
            repo = parts[1]
        else:
            return {"error": f"Invalid PR ID format: {pr_id}"}

        # Repo-specific patterns
        rows = db.execute(
            "SELECT category, pattern, example_comment FROM ri_patterns "
            "WHERE repo = ? ORDER BY frequency DESC LIMIT 5", (repo,)
        ).fetchall()
        repo_patterns = [dict(r) for r in rows]

        # Top reviewer focus areas
        rows = db.execute(
            "SELECT reviewer, focus_areas, common_phrases FROM ri_reviewer_profiles "
            "ORDER BY total_comments DESC LIMIT 3"
        ).fetchall()
        reviewer_context = []
        for r in rows:
            d = dict(r)
            for key in ("focus_areas", "common_phrases"):
                if d.get(key):
                    try:
                        d[key] = json.loads(d[key])
                    except (json.JSONDecodeError, TypeError):
                        pass
            reviewer_context.append(d)

        # Category distribution for the repo
        rows = db.execute(
            "SELECT c.category, COUNT(*) as cnt FROM ri_review_comments c "
            "JOIN ri_pull_requests p ON c.pr_id = p.id WHERE p.repo = ? "
            "AND c.category != '' GROUP BY c.category ORDER BY cnt DESC", (repo,)
        ).fetchall()
        focus_areas = {r["category"]: r["cnt"] for r in rows}

    finally:
        db.close()

    context_block = _build_context_block(repo, repo_patterns, reviewer_context, focus_areas)

    return {
        "pr_id": pr_id,
        "repo": repo,
        "team_context": context_block,
        "repo_patterns": repo_patterns,
        "reviewer_profiles": reviewer_context,
        "focus_areas": focus_areas,
    }


def _build_context_block(
    repo: str,
    patterns: list[dict],
    reviewers: list[dict],
    focus_areas: dict,
) -> str:
    """Build the team-context block to inject into AI review prompts."""
    lines = [
        f"\n--- TEAM CONTEXT FOR {repo} ---\n",
        "This repository is part of the Konflux CI release platform.",
    ]

    if focus_areas:
        top = sorted(focus_areas.items(), key=lambda x: x[1], reverse=True)[:3]
        lines.append("\nHistorical review focus areas (by frequency):")
        for cat, cnt in top:
            lines.append(f"  - {cat}: {cnt} past comments")

    if patterns:
        lines.append("\nRecurring review patterns in this repo:")
        for p in patterns[:3]:
            lines.append(f"  [{p['category']}] {p['pattern']}")

    if reviewers:
        lines.append("\nKey reviewer expectations:")
        for r in reviewers:
            areas = r.get("focus_areas", [])
            if areas:
                lines.append(f"  - {r['reviewer']} focuses on: {', '.join(areas[:3])}")

    lines.append("\n--- END TEAM CONTEXT ---\n")
    return "\n".join(lines)


def get_review_statistics() -> dict:
    """Dashboard-style statistics about the collected review intelligence."""
    db = _get_db()
    try:
        # PR counts by repo
        rows = db.execute(
            "SELECT repo, COUNT(*) as cnt FROM ri_pull_requests GROUP BY repo"
        ).fetchall()
        prs_by_repo = {r["repo"]: r["cnt"] for r in rows}

        total_prs = sum(prs_by_repo.values())

        # Comment stats
        row = db.execute("SELECT COUNT(*) as cnt FROM ri_review_comments").fetchone()
        total_comments = row["cnt"] if row else 0

        # Categories
        rows = db.execute(
            "SELECT category, COUNT(*) as cnt FROM ri_review_comments "
            "WHERE category != '' GROUP BY category ORDER BY cnt DESC"
        ).fetchall()
        by_category = {r["category"]: r["cnt"] for r in rows}

        # Reviewer count
        row = db.execute("SELECT COUNT(*) as cnt FROM ri_reviewer_profiles").fetchone()
        reviewer_count = row["cnt"] if row else 0

        # Pattern count
        row = db.execute("SELECT COUNT(*) as cnt FROM ri_patterns").fetchone()
        pattern_count = row["cnt"] if row else 0

        # Top reviewers
        rows = db.execute(
            "SELECT reviewer, total_comments FROM ri_reviewer_profiles "
            "ORDER BY total_comments DESC LIMIT 10"
        ).fetchall()
        top_reviewers = [{"reviewer": r["reviewer"], "comments": r["total_comments"]} for r in rows]

        return {
            "total_prs_analyzed": total_prs,
            "prs_by_repo": prs_by_repo,
            "total_comments": total_comments,
            "comments_by_category": by_category,
            "reviewer_count": reviewer_count,
            "pattern_count": pattern_count,
            "top_reviewers": top_reviewers,
        }
    finally:
        db.close()
