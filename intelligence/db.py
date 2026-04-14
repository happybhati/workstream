"""CRUD helpers for Review Intelligence (ri_*) tables."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import aiosqlite

from config import settings

DB_PATH = settings.db_path


async def _get_db() -> aiosqlite.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    return db


# ---------------------------------------------------------------------------
# ri_pull_requests
# ---------------------------------------------------------------------------

async def upsert_ri_pr(pr: dict) -> None:
    pr["collected_at"] = datetime.now(timezone.utc).isoformat()
    db = await _get_db()
    try:
        await db.execute(
            """INSERT INTO ri_pull_requests
               (id, repo, number, title, author, merged_at, base_branch,
                files_changed, additions, deletions, description, collected_at)
               VALUES (:id, :repo, :number, :title, :author, :merged_at,
                       :base_branch, :files_changed, :additions, :deletions,
                       :description, :collected_at)
               ON CONFLICT(id) DO UPDATE SET
                   title=excluded.title, files_changed=excluded.files_changed,
                   additions=excluded.additions, deletions=excluded.deletions,
                   description=excluded.description, collected_at=excluded.collected_at
            """,
            pr,
        )
        await db.commit()
    finally:
        await db.close()


async def get_ri_pr(pr_id: str) -> dict | None:
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM ri_pull_requests WHERE id = :id", {"id": pr_id}
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_ri_prs_by_repo(repo: str, limit: int = 100) -> list[dict]:
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM ri_pull_requests WHERE repo = :repo ORDER BY merged_at DESC LIMIT :limit",
            {"repo": repo, "limit": limit},
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def count_ri_prs() -> dict:
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT repo, COUNT(*) as cnt FROM ri_pull_requests GROUP BY repo"
        )
        rows = await cursor.fetchall()
        result = {row["repo"]: row["cnt"] for row in rows}
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM ri_pull_requests")
        row = await cursor.fetchone()
        result["_total"] = row["cnt"] if row else 0
        return result
    finally:
        await db.close()


async def get_latest_merged_at(repo: str) -> str | None:
    """Return the most recent merged_at timestamp we've collected for a repo."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT MAX(merged_at) as latest FROM ri_pull_requests WHERE repo = :repo",
            {"repo": repo},
        )
        row = await cursor.fetchone()
        return row["latest"] if row and row["latest"] else None
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# ri_review_comments
# ---------------------------------------------------------------------------

async def insert_ri_comment(comment: dict) -> None:
    db = await _get_db()
    try:
        await db.execute(
            """INSERT INTO ri_review_comments
               (pr_id, reviewer, file_path, line_number, body, review_state,
                created_at, category)
               VALUES (:pr_id, :reviewer, :file_path, :line_number, :body,
                       :review_state, :created_at, :category)
            """,
            comment,
        )
        await db.commit()
    finally:
        await db.close()


async def bulk_insert_ri_comments(comments: list[dict]) -> int:
    if not comments:
        return 0
    db = await _get_db()
    try:
        for c in comments:
            c.setdefault("node_id", "")
        await db.executemany(
            """INSERT INTO ri_review_comments
               (pr_id, reviewer, file_path, line_number, body, review_state,
                created_at, category, node_id)
               VALUES (:pr_id, :reviewer, :file_path, :line_number, :body,
                       :review_state, :created_at, :category, :node_id)
            """,
            comments,
        )
        await db.commit()
        return len(comments)
    finally:
        await db.close()


async def comment_node_ids_exist(node_ids: list[str]) -> set[str]:
    """Return the subset of node_ids that already exist in the DB."""
    if not node_ids:
        return set()
    db = await _get_db()
    try:
        placeholders = ",".join("?" for _ in node_ids)
        cursor = await db.execute(
            f"SELECT node_id FROM ri_review_comments WHERE node_id IN ({placeholders})",
            node_ids,
        )
        rows = await cursor.fetchall()
        return {r["node_id"] for r in rows if r["node_id"]}
    finally:
        await db.close()


async def get_comments_for_pr(pr_id: str) -> list[dict]:
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM ri_review_comments WHERE pr_id = :pr_id ORDER BY created_at",
            {"pr_id": pr_id},
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def get_comments_by_reviewer(reviewer: str, limit: int = 200) -> list[dict]:
    db = await _get_db()
    try:
        cursor = await db.execute(
            """SELECT c.*, p.repo, p.title as pr_title
               FROM ri_review_comments c
               JOIN ri_pull_requests p ON c.pr_id = p.id
               WHERE c.reviewer = :reviewer
               ORDER BY c.created_at DESC LIMIT :limit""",
            {"reviewer": reviewer, "limit": limit},
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def search_comments(query: str, repo: str = "", limit: int = 50) -> list[dict]:
    db = await _get_db()
    try:
        repo_filter = "AND p.repo = :repo" if repo else ""
        cursor = await db.execute(
            f"""SELECT c.*, p.repo, p.title as pr_title
                FROM ri_review_comments c
                JOIN ri_pull_requests p ON c.pr_id = p.id
                WHERE c.body LIKE :query {repo_filter}
                ORDER BY c.created_at DESC LIMIT :limit""",
            {"query": f"%{query}%", "repo": repo, "limit": limit},
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def get_comments_by_file_path(file_path_pattern: str, limit: int = 30) -> list[dict]:
    db = await _get_db()
    try:
        cursor = await db.execute(
            """SELECT c.*, p.repo, p.title as pr_title
               FROM ri_review_comments c
               JOIN ri_pull_requests p ON c.pr_id = p.id
               WHERE c.file_path LIKE :pattern AND c.file_path != ''
               ORDER BY c.created_at DESC LIMIT :limit""",
            {"pattern": f"%{file_path_pattern}%", "limit": limit},
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def get_comments_by_category(category: str, repo: str = "", limit: int = 50) -> list[dict]:
    db = await _get_db()
    try:
        repo_filter = "AND p.repo = :repo" if repo else ""
        cursor = await db.execute(
            f"""SELECT c.*, p.repo, p.title as pr_title
                FROM ri_review_comments c
                JOIN ri_pull_requests p ON c.pr_id = p.id
                WHERE c.category = :category {repo_filter}
                ORDER BY c.created_at DESC LIMIT :limit""",
            {"category": category, "repo": repo, "limit": limit},
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def get_unclassified_comments(limit: int = 500) -> list[dict]:
    db = await _get_db()
    try:
        cursor = await db.execute(
            """SELECT * FROM ri_review_comments
               WHERE category = '' OR category IS NULL
               ORDER BY created_at DESC LIMIT :limit""",
            {"limit": limit},
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def update_comment_category(comment_id: int, category: str) -> None:
    db = await _get_db()
    try:
        await db.execute(
            "UPDATE ri_review_comments SET category = :cat WHERE id = :id",
            {"cat": category, "id": comment_id},
        )
        await db.commit()
    finally:
        await db.close()


async def batch_update_categories(updates: list[tuple[int, str]]) -> int:
    """Updates is a list of (comment_id, category) tuples."""
    if not updates:
        return 0
    db = await _get_db()
    try:
        await db.executemany(
            "UPDATE ri_review_comments SET category = ? WHERE id = ?",
            [(cat, cid) for cid, cat in updates],
        )
        await db.commit()
        return len(updates)
    finally:
        await db.close()


async def count_ri_comments() -> dict:
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM ri_review_comments"
        )
        row = await cursor.fetchone()
        total = row["cnt"] if row else 0

        cursor = await db.execute(
            """SELECT category, COUNT(*) as cnt FROM ri_review_comments
               WHERE category != '' GROUP BY category ORDER BY cnt DESC"""
        )
        by_category = {r["category"]: r["cnt"] for r in await cursor.fetchall()}

        cursor = await db.execute(
            """SELECT reviewer, COUNT(*) as cnt FROM ri_review_comments
               GROUP BY reviewer ORDER BY cnt DESC LIMIT 20"""
        )
        by_reviewer = {r["reviewer"]: r["cnt"] for r in await cursor.fetchall()}

        return {"total": total, "by_category": by_category, "by_reviewer": by_reviewer}
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# ri_patterns
# ---------------------------------------------------------------------------

async def upsert_ri_pattern(pattern: dict) -> None:
    pattern["updated_at"] = datetime.now(timezone.utc).isoformat()
    db = await _get_db()
    try:
        await db.execute(
            """INSERT INTO ri_patterns
               (category, pattern, example_comment, frequency, reviewer, repo, updated_at)
               VALUES (:category, :pattern, :example_comment, :frequency,
                       :reviewer, :repo, :updated_at)
            """,
            pattern,
        )
        await db.commit()
    finally:
        await db.close()


async def clear_ri_patterns() -> None:
    db = await _get_db()
    try:
        await db.execute("DELETE FROM ri_patterns")
        await db.commit()
    finally:
        await db.close()


async def get_patterns(category: str = "", repo: str = "", limit: int = 50) -> list[dict]:
    db = await _get_db()
    try:
        conditions = []
        params: dict = {"limit": limit}
        if category:
            conditions.append("category = :category")
            params["category"] = category
        if repo:
            conditions.append("repo = :repo")
            params["repo"] = repo
        where = " AND ".join(conditions) if conditions else "1=1"
        cursor = await db.execute(
            f"""SELECT * FROM ri_patterns WHERE {where}
                ORDER BY frequency DESC LIMIT :limit""",
            params,
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# ri_reviewer_profiles
# ---------------------------------------------------------------------------

async def upsert_reviewer_profile(profile: dict) -> None:
    profile["updated_at"] = datetime.now(timezone.utc).isoformat()
    for key in ("top_categories", "common_phrases", "focus_areas"):
        if isinstance(profile.get(key), (dict, list)):
            profile[key] = json.dumps(profile[key])
    db = await _get_db()
    try:
        await db.execute(
            """INSERT INTO ri_reviewer_profiles
               (reviewer, total_reviews, total_comments, top_categories,
                common_phrases, avg_comments_per_pr, focus_areas, updated_at)
               VALUES (:reviewer, :total_reviews, :total_comments, :top_categories,
                       :common_phrases, :avg_comments_per_pr, :focus_areas, :updated_at)
               ON CONFLICT(reviewer) DO UPDATE SET
                   total_reviews=excluded.total_reviews,
                   total_comments=excluded.total_comments,
                   top_categories=excluded.top_categories,
                   common_phrases=excluded.common_phrases,
                   avg_comments_per_pr=excluded.avg_comments_per_pr,
                   focus_areas=excluded.focus_areas,
                   updated_at=excluded.updated_at
            """,
            profile,
        )
        await db.commit()
    finally:
        await db.close()


async def get_reviewer_profile(reviewer: str) -> dict | None:
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM ri_reviewer_profiles WHERE reviewer = :r",
            {"r": reviewer},
        )
        row = await cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        for key in ("top_categories", "common_phrases", "focus_areas"):
            if d.get(key):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d
    finally:
        await db.close()


async def get_all_reviewer_profiles() -> list[dict]:
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM ri_reviewer_profiles ORDER BY total_comments DESC"
        )
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            for key in ("top_categories", "common_phrases", "focus_areas"):
                if d.get(key):
                    try:
                        d[key] = json.loads(d[key])
                    except (json.JSONDecodeError, TypeError):
                        pass
            result.append(d)
        return result
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Aggregate statistics
# ---------------------------------------------------------------------------

async def get_ri_statistics() -> dict:
    """Combined statistics for the Review Intelligence dashboard."""
    pr_counts = await count_ri_prs()
    comment_counts = await count_ri_comments()
    profiles = await get_all_reviewer_profiles()

    db = await _get_db()
    try:
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM ri_patterns")
        row = await cursor.fetchone()
        pattern_count = row["cnt"] if row else 0
    finally:
        await db.close()

    return {
        "prs_collected": pr_counts,
        "comments": comment_counts,
        "pattern_count": pattern_count,
        "reviewer_count": len(profiles),
        "top_reviewers": [
            {"reviewer": p["reviewer"], "comments": p["total_comments"]}
            for p in profiles[:10]
        ],
    }


# ---------------------------------------------------------------------------
# Repo-scoped queries for per-repo intelligence display
# ---------------------------------------------------------------------------

async def get_repo_intelligence(repo: str) -> dict:
    """Return complete intelligence data for a single repo."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM ri_pull_requests WHERE repo = :repo",
            {"repo": repo},
        )
        row = await cursor.fetchone()
        pr_count = row["cnt"] if row else 0

        cursor = await db.execute(
            """SELECT category, COUNT(*) as cnt
               FROM ri_review_comments c
               JOIN ri_pull_requests p ON c.pr_id = p.id
               WHERE p.repo = :repo AND c.category != '' AND c.category != 'other'
               GROUP BY c.category ORDER BY cnt DESC""",
            {"repo": repo},
        )
        categories = {r["category"]: r["cnt"] for r in await cursor.fetchall()}

        cursor = await db.execute(
            """SELECT c.reviewer, COUNT(*) as cnt
               FROM ri_review_comments c
               JOIN ri_pull_requests p ON c.pr_id = p.id
               WHERE p.repo = :repo AND c.reviewer != ''
               GROUP BY c.reviewer ORDER BY cnt DESC LIMIT 10""",
            {"repo": repo},
        )
        reviewers = [{"reviewer": r["reviewer"], "comments": r["cnt"]} for r in await cursor.fetchall()]

        cursor = await db.execute(
            "SELECT * FROM ri_patterns WHERE repo = :repo ORDER BY frequency DESC LIMIT 20",
            {"repo": repo},
        )
        patterns = [dict(r) for r in await cursor.fetchall()]

        cursor = await db.execute(
            """SELECT COUNT(*) as cnt
               FROM ri_review_comments c
               JOIN ri_pull_requests p ON c.pr_id = p.id
               WHERE p.repo = :repo""",
            {"repo": repo},
        )
        row = await cursor.fetchone()
        comment_count = row["cnt"] if row else 0

        cursor = await db.execute(
            """SELECT MIN(p.merged_at) as earliest, MAX(p.merged_at) as latest
               FROM ri_pull_requests p WHERE p.repo = :repo""",
            {"repo": repo},
        )
        row = await cursor.fetchone()
        date_range = {"earliest": row["earliest"], "latest": row["latest"]} if row else {}

        return {
            "repo": repo,
            "pr_count": pr_count,
            "comment_count": comment_count,
            "categories": categories,
            "reviewers": reviewers,
            "patterns": patterns,
            "date_range": date_range,
        }
    finally:
        await db.close()


async def get_collected_repos() -> list[dict]:
    """Return list of repos with collection stats."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            """SELECT repo, COUNT(*) as pr_count,
                      MIN(merged_at) as earliest, MAX(merged_at) as latest
               FROM ri_pull_requests
               GROUP BY repo ORDER BY repo"""
        )
        rows = await cursor.fetchall()
        result = []
        for r in rows:
            repo = r["repo"]
            cursor2 = await db.execute(
                """SELECT COUNT(*) as cnt
                   FROM ri_review_comments c
                   JOIN ri_pull_requests p ON c.pr_id = p.id
                   WHERE p.repo = :repo""",
                {"repo": repo},
            )
            row2 = await cursor2.fetchone()
            result.append({
                "repo": repo,
                "pr_count": r["pr_count"],
                "comment_count": row2["cnt"] if row2 else 0,
                "earliest": r["earliest"],
                "latest": r["latest"],
            })
        return result
    finally:
        await db.close()
