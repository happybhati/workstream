from __future__ import annotations

import aiosqlite

from config import settings

DB_PATH = settings.db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS pull_requests (
    id TEXT PRIMARY KEY,           -- "github:org/repo:42" or "gitlab:group/project:23"
    platform TEXT NOT NULL,        -- "github" or "gitlab"
    repo_full_name TEXT NOT NULL,  -- "org/repo" or "group/project"
    number INTEGER NOT NULL,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    state TEXT NOT NULL,           -- open, closed, merged, draft
    is_draft INTEGER DEFAULT 0,
    url TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    ci_status TEXT DEFAULT 'unknown',  -- passing, failing, running, unknown
    review_requested_from TEXT DEFAULT '',  -- comma-separated usernames
    assigned_to TEXT DEFAULT '',            -- comma-separated usernames
    jira_key TEXT DEFAULT '',
    additions INTEGER DEFAULT 0,
    deletions INTEGER DEFAULT 0,
    comments_count INTEGER DEFAULT 0,
    review_state TEXT DEFAULT '',           -- approved, changes_requested, or empty
    approved_by TEXT DEFAULT '',            -- comma-separated approver usernames
    polled_at TEXT DEFAULT '',              -- ISO timestamp of last poll that saw this PR
    ci_checks TEXT DEFAULT '',             -- JSON array of individual check run details
    author_avatar TEXT DEFAULT ''          -- URL to author's avatar image
);

CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pr_id TEXT NOT NULL,
    event_type TEXT NOT NULL,       -- comment, approval, change_request, ci_fail, ci_pass, merge
    actor TEXT NOT NULL,
    body TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (pr_id) REFERENCES pull_requests(id)
);

CREATE INDEX IF NOT EXISTS idx_pr_author ON pull_requests(author);
CREATE INDEX IF NOT EXISTS idx_pr_state ON pull_requests(state);
CREATE INDEX IF NOT EXISTS idx_pr_review ON pull_requests(review_requested_from);
CREATE INDEX IF NOT EXISTS idx_activity_pr ON activities(pr_id);
CREATE INDEX IF NOT EXISTS idx_activity_time ON activities(created_at);

CREATE TABLE IF NOT EXISTS jira_issues (
    key TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL,
    status_category TEXT NOT NULL,     -- new, in_progress, in_review, done
    issue_type TEXT DEFAULT '',
    priority TEXT DEFAULT '',
    assignee TEXT DEFAULT '',
    reporter TEXT DEFAULT '',
    sprint_name TEXT DEFAULT '',
    sprint_state TEXT DEFAULT '',       -- active, closed, future, or empty (backlog)
    url TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    role TEXT DEFAULT '',               -- assignee, reporter, both
    polled_at TEXT DEFAULT ''           -- ISO timestamp of last poll that saw this issue
);

CREATE INDEX IF NOT EXISTS idx_jira_status_cat ON jira_issues(status_category);
CREATE INDEX IF NOT EXISTS idx_jira_role ON jira_issues(role);
CREATE INDEX IF NOT EXISTS idx_jira_sprint ON jira_issues(sprint_state);
CREATE INDEX IF NOT EXISTS idx_jira_project ON jira_issues(project);

CREATE TABLE IF NOT EXISTS yearly_completions (
    year INTEGER PRIMARY KEY,
    completed INTEGER NOT NULL DEFAULT 0,
    same_period INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS active_sprints (
    project TEXT PRIMARY KEY,
    sprint_id INTEGER NOT NULL,
    board_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    state TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    goal TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS calendar_events (
    event_id TEXT PRIMARY KEY,
    calendar_id TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    meet_link TEXT DEFAULT '',
    attendee_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'confirmed',
    is_all_day INTEGER DEFAULT 0,
    location TEXT DEFAULT '',
    polled_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cal_start ON calendar_events(start_time);

-- Review Intelligence: merged PRs with review data
CREATE TABLE IF NOT EXISTS ri_pull_requests (
    id TEXT PRIMARY KEY,              -- "konflux-ci/release-service:142"
    repo TEXT NOT NULL,
    number INTEGER NOT NULL,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    merged_at TEXT NOT NULL,
    base_branch TEXT NOT NULL,
    files_changed INTEGER DEFAULT 0,
    additions INTEGER DEFAULT 0,
    deletions INTEGER DEFAULT 0,
    description TEXT DEFAULT '',
    collected_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ri_pr_repo ON ri_pull_requests(repo);
CREATE INDEX IF NOT EXISTS idx_ri_pr_merged ON ri_pull_requests(merged_at);

-- Review Intelligence: individual review comments from humans
CREATE TABLE IF NOT EXISTS ri_review_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pr_id TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    file_path TEXT DEFAULT '',
    line_number INTEGER DEFAULT 0,
    body TEXT NOT NULL,
    review_state TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    category TEXT DEFAULT '',
    node_id TEXT DEFAULT '',
    FOREIGN KEY (pr_id) REFERENCES ri_pull_requests(id)
);

CREATE INDEX IF NOT EXISTS idx_ri_comment_pr ON ri_review_comments(pr_id);
CREATE INDEX IF NOT EXISTS idx_ri_comment_reviewer ON ri_review_comments(reviewer);
CREATE INDEX IF NOT EXISTS idx_ri_comment_category ON ri_review_comments(category);

-- Review Intelligence: extracted patterns
CREATE TABLE IF NOT EXISTS ri_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    pattern TEXT NOT NULL,
    example_comment TEXT NOT NULL,
    frequency INTEGER DEFAULT 1,
    reviewer TEXT DEFAULT '',
    repo TEXT DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ri_pattern_cat ON ri_patterns(category);

-- Review Intelligence: per-reviewer profiles
CREATE TABLE IF NOT EXISTS ri_reviewer_profiles (
    reviewer TEXT PRIMARY KEY,
    total_reviews INTEGER DEFAULT 0,
    total_comments INTEGER DEFAULT 0,
    top_categories TEXT DEFAULT '',
    common_phrases TEXT DEFAULT '',
    avg_comments_per_pr REAL DEFAULT 0,
    focus_areas TEXT DEFAULT '',
    updated_at TEXT NOT NULL
);

-- AI Readiness scan history
CREATE TABLE IF NOT EXISTS readiness_scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_url TEXT NOT NULL,
    owner TEXT NOT NULL,
    repo TEXT NOT NULL,
    score_total INTEGER DEFAULT 0,
    score_agent_config INTEGER DEFAULT 0,
    score_documentation INTEGER DEFAULT 0,
    score_ci_quality INTEGER DEFAULT 0,
    score_code_structure INTEGER DEFAULT 0,
    score_security INTEGER DEFAULT 0,
    grade TEXT DEFAULT '',
    findings TEXT DEFAULT '',
    scanned_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_readiness_repo ON readiness_scans(owner, repo);
"""


async def get_db() -> aiosqlite.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    return db


async def init_db() -> None:
    db = await get_db()
    try:
        await db.executescript(SCHEMA)
        # Migrations for pre-existing DBs
        cursor = await db.execute("PRAGMA table_info(yearly_completions)")
        cols = {row[1] for row in await cursor.fetchall()}
        if "same_period" not in cols:
            await db.execute("ALTER TABLE yearly_completions ADD COLUMN same_period INTEGER NOT NULL DEFAULT 0")
        for table in ("pull_requests", "jira_issues"):
            cursor = await db.execute(f"PRAGMA table_info({table})")
            cols = {row[1] for row in await cursor.fetchall()}
            if "polled_at" not in cols:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN polled_at TEXT DEFAULT ''")
        cursor = await db.execute("PRAGMA table_info(pull_requests)")
        pr_cols = {row[1] for row in await cursor.fetchall()}
        if "ci_checks" not in pr_cols:
            await db.execute("ALTER TABLE pull_requests ADD COLUMN ci_checks TEXT DEFAULT ''")
        if "author_avatar" not in pr_cols:
            await db.execute("ALTER TABLE pull_requests ADD COLUMN author_avatar TEXT DEFAULT ''")
        # node_id for comment deduplication
        cursor = await db.execute("PRAGMA table_info(ri_review_comments)")
        ri_cols = {row[1] for row in await cursor.fetchall()}
        if "node_id" not in ri_cols:
            await db.execute("ALTER TABLE ri_review_comments ADD COLUMN node_id TEXT DEFAULT ''")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_ri_comment_node_id ON ri_review_comments(node_id)")
        # score_security column for readiness scans
        cursor = await db.execute("PRAGMA table_info(readiness_scans)")
        rs_cols = {row[1] for row in await cursor.fetchall()}
        if "score_security" not in rs_cols:
            await db.execute("ALTER TABLE readiness_scans ADD COLUMN score_security INTEGER DEFAULT 0")
        await db.commit()
    finally:
        await db.close()


async def upsert_pr(pr: dict) -> None:
    from datetime import datetime, timezone

    pr.setdefault("assigned_to", "")
    pr.setdefault("review_state", "")
    pr.setdefault("approved_by", "")
    pr.setdefault("ci_checks", "")
    pr.setdefault("author_avatar", "")
    pr["polled_at"] = datetime.now(timezone.utc).isoformat()
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO pull_requests
               (id, platform, repo_full_name, number, title, author, state,
                is_draft, url, created_at, updated_at, ci_status,
                review_requested_from, assigned_to, jira_key, additions, deletions,
                comments_count, review_state, approved_by, polled_at, ci_checks,
                author_avatar)
               VALUES (:id, :platform, :repo_full_name, :number, :title, :author,
                       :state, :is_draft, :url, :created_at, :updated_at, :ci_status,
                       :review_requested_from, :assigned_to, :jira_key, :additions, :deletions,
                       :comments_count, :review_state, :approved_by, :polled_at, :ci_checks,
                       :author_avatar)
               ON CONFLICT(id) DO UPDATE SET
                   title=excluded.title, state=excluded.state, is_draft=excluded.is_draft,
                   updated_at=excluded.updated_at, ci_status=excluded.ci_status,
                   review_requested_from=excluded.review_requested_from,
                   assigned_to=CASE WHEN excluded.assigned_to != '' THEN excluded.assigned_to ELSE pull_requests.assigned_to END,
                   jira_key=excluded.jira_key, additions=excluded.additions,
                   deletions=excluded.deletions, comments_count=excluded.comments_count,
                   review_state=CASE WHEN excluded.review_state != '' THEN excluded.review_state ELSE pull_requests.review_state END,
                   approved_by=CASE WHEN excluded.approved_by != '' THEN excluded.approved_by ELSE pull_requests.approved_by END,
                   polled_at=excluded.polled_at,
                   ci_checks=CASE WHEN excluded.ci_checks != '' THEN excluded.ci_checks ELSE pull_requests.ci_checks END,
                   author_avatar=CASE WHEN excluded.author_avatar != '' THEN excluded.author_avatar ELSE pull_requests.author_avatar END
            """,
            pr,
        )
        await db.commit()
    finally:
        await db.close()


async def insert_activity(activity: dict) -> None:
    db = await get_db()
    try:
        await db.execute(
            """INSERT OR IGNORE INTO activities
               (pr_id, event_type, actor, body, created_at)
               VALUES (:pr_id, :event_type, :actor, :body, :created_at)
            """,
            activity,
        )
        await db.commit()
    finally:
        await db.close()


async def get_my_prs(username_github: str, username_gitlab: str, include_closed: bool = False) -> list[dict]:
    db = await get_db()
    try:
        state_filter = "" if include_closed else "AND state IN ('open', 'draft')"
        cursor = await db.execute(
            f"""SELECT * FROM pull_requests
               WHERE ((platform='github' AND author=:gh)
                   OR (platform='gitlab' AND author=:gl))
               {state_filter}
               ORDER BY updated_at DESC""",
            {"gh": username_github, "gl": username_gitlab},
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_assigned_prs(username_github: str, username_gitlab: str) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT * FROM pull_requests
               WHERE state IN ('open', 'draft')
                 AND (assigned_to LIKE :gh OR assigned_to LIKE :gl)
               ORDER BY updated_at DESC""",
            {"gh": f"%{username_github}%", "gl": f"%{username_gitlab}%"},
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_review_requests(username_github: str, username_gitlab: str) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT * FROM pull_requests
               WHERE state IN ('open', 'draft')
                 AND (review_requested_from LIKE :gh
                      OR review_requested_from LIKE :gl)
               ORDER BY created_at ASC""",
            {"gh": f"%{username_github}%", "gl": f"%{username_gitlab}%"},
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def upsert_jira_issue(issue: dict) -> None:
    from datetime import datetime, timezone

    issue["polled_at"] = datetime.now(timezone.utc).isoformat()
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO jira_issues
               (key, project, summary, status, status_category, issue_type,
                priority, assignee, reporter, sprint_name, sprint_state,
                url, created_at, updated_at, role, polled_at)
               VALUES (:key, :project, :summary, :status, :status_category,
                       :issue_type, :priority, :assignee, :reporter,
                       :sprint_name, :sprint_state, :url, :created_at,
                       :updated_at, :role, :polled_at)
               ON CONFLICT(key) DO UPDATE SET
                   summary=excluded.summary, status=excluded.status,
                   status_category=excluded.status_category,
                   issue_type=excluded.issue_type, priority=excluded.priority,
                   assignee=excluded.assignee, reporter=excluded.reporter,
                   sprint_name=excluded.sprint_name, sprint_state=excluded.sprint_state,
                   url=excluded.url, updated_at=excluded.updated_at,
                   polled_at=excluded.polled_at,
                   role=CASE
                       WHEN jira_issues.role != excluded.role AND jira_issues.role != 'both' AND excluded.role != ''
                       THEN 'both'
                       ELSE COALESCE(NULLIF(excluded.role, ''), jira_issues.role)
                   END
            """,
            issue,
        )
        await db.commit()
    finally:
        await db.close()


async def get_jira_tasks(role_filter: str = "all", status_category: str = "all", sprint: str = "all") -> list[dict]:
    db = await get_db()
    try:
        conditions = []
        params: dict = {}

        if role_filter == "assignee":
            conditions.append("role IN ('assignee', 'both')")
        elif role_filter == "reporter":
            conditions.append("role IN ('reporter', 'both')")

        if status_category != "all":
            conditions.append("status_category = :status_category")
            params["status_category"] = status_category

        if sprint == "active":
            conditions.append("sprint_state = 'active'")
        elif sprint == "backlog":
            conditions.append("(sprint_state = '' OR sprint_state IS NULL)")

        where = " AND ".join(conditions) if conditions else "1=1"
        cursor = await db.execute(
            f"SELECT * FROM jira_issues WHERE {where} ORDER BY updated_at DESC",
            params,
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_jira_stats() -> dict:
    db = await get_db()
    try:
        result: dict = {"by_status": {}, "by_role": {}, "total": 0}

        cursor = await db.execute("SELECT status_category, COUNT(*) as cnt FROM jira_issues GROUP BY status_category")
        for row in await cursor.fetchall():
            result["by_status"][row["status_category"]] = row["cnt"]

        cursor = await db.execute("SELECT COUNT(*) as cnt FROM jira_issues WHERE role IN ('assignee', 'both')")
        row = await cursor.fetchone()
        result["by_role"]["assignee"] = row["cnt"] if row else 0

        cursor = await db.execute("SELECT COUNT(*) as cnt FROM jira_issues WHERE role IN ('reporter', 'both')")
        row = await cursor.fetchone()
        result["by_role"]["reporter"] = row["cnt"] if row else 0

        cursor = await db.execute("SELECT COUNT(*) as cnt FROM jira_issues")
        row = await cursor.fetchone()
        result["total"] = row["cnt"] if row else 0

        cursor = await db.execute("SELECT COUNT(*) as cnt FROM jira_issues WHERE sprint_state = 'active'")
        row = await cursor.fetchone()
        result["in_sprint"] = row["cnt"] if row else 0

        return result
    finally:
        await db.close()


async def upsert_yearly_completion(year: int, completed: int, same_period: int = 0) -> None:
    from datetime import datetime, timezone

    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO yearly_completions (year, completed, same_period, updated_at)
               VALUES (:year, :completed, :same_period, :updated_at)
               ON CONFLICT(year) DO UPDATE SET
                   completed=excluded.completed,
                   same_period=excluded.same_period,
                   updated_at=excluded.updated_at""",
            {
                "year": year,
                "completed": completed,
                "same_period": same_period,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        await db.commit()
    finally:
        await db.close()


async def get_yearly_completions() -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT year, completed, same_period FROM yearly_completions ORDER BY year DESC LIMIT 2"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def upsert_active_sprint(sprint: dict) -> None:
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO active_sprints
               (project, sprint_id, board_id, name, state, start_date, end_date, goal)
               VALUES (:project, :sprint_id, :board_id, :name, :state,
                       :start_date, :end_date, :goal)
               ON CONFLICT(project) DO UPDATE SET
                   sprint_id=excluded.sprint_id, board_id=excluded.board_id,
                   name=excluded.name, state=excluded.state,
                   start_date=excluded.start_date, end_date=excluded.end_date,
                   goal=excluded.goal
            """,
            sprint,
        )
        await db.commit()
    finally:
        await db.close()


async def get_active_sprints() -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM active_sprints WHERE state = 'active' ORDER BY project")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_sprint_tasks(project: str) -> dict:
    """Get task counts for the active sprint of a given project, assigned to current user."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT status_category, COUNT(*) as cnt
               FROM jira_issues
               WHERE project = :project
                 AND sprint_state = 'active'
                 AND role IN ('assignee', 'both')
               GROUP BY status_category""",
            {"project": project},
        )
        counts = {"new": 0, "in_progress": 0, "in_review": 0, "done": 0, "total": 0}
        for row in await cursor.fetchall():
            counts[row["status_category"]] = row["cnt"]
            counts["total"] += row["cnt"]
        return counts
    finally:
        await db.close()


async def get_recent_activities(limit: int = 50) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT a.*, p.title as pr_title, p.repo_full_name, p.number, p.url as pr_url
               FROM activities a
               JOIN pull_requests p ON a.pr_id = p.id
               ORDER BY a.created_at DESC
               LIMIT :limit""",
            {"limit": limit},
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def upsert_calendar_event(event: dict) -> None:
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO calendar_events
               (event_id, calendar_id, summary, start_time, end_time,
                meet_link, attendee_count, status, is_all_day, location, polled_at)
               VALUES (:event_id, :calendar_id, :summary, :start_time, :end_time,
                       :meet_link, :attendee_count, :status, :is_all_day, :location, :polled_at)
               ON CONFLICT(event_id) DO UPDATE SET
                   summary=excluded.summary, start_time=excluded.start_time,
                   end_time=excluded.end_time, meet_link=excluded.meet_link,
                   attendee_count=excluded.attendee_count, status=excluded.status,
                   is_all_day=excluded.is_all_day, location=excluded.location,
                   polled_at=excluded.polled_at
            """,
            event,
        )
        await db.commit()
    finally:
        await db.close()


async def cleanup_stale_prs(cycle_start: str) -> int:
    """Mark open/draft PRs not seen since cycle_start as 'closed'."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """UPDATE pull_requests SET state = 'closed'
               WHERE state IN ('open', 'draft')
                 AND (polled_at < :cutoff OR polled_at = '' OR polled_at IS NULL)""",
            {"cutoff": cycle_start},
        )
        await db.commit()
        return cursor.rowcount
    finally:
        await db.close()


async def cleanup_stale_jira_issues(cycle_start: str) -> int:
    """Remove Jira issues not seen since cycle_start (they've been resolved or unassigned)."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """DELETE FROM jira_issues
               WHERE status_category != 'done'
                 AND (polled_at < :cutoff OR polled_at = '' OR polled_at IS NULL)""",
            {"cutoff": cycle_start},
        )
        await db.commit()
        return cursor.rowcount
    finally:
        await db.close()


async def clear_calendar_events() -> None:
    db = await get_db()
    try:
        await db.execute("DELETE FROM calendar_events")
        await db.commit()
    finally:
        await db.close()


async def get_events_for_date(target_date=None) -> list[dict]:
    from datetime import datetime

    if target_date is None:
        target_date = datetime.now().date()
    day_start = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0).isoformat()
    day_end = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59).isoformat()

    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT * FROM calendar_events
               WHERE start_time >= :start AND start_time <= :end
                 AND status != 'cancelled'
               ORDER BY is_all_day ASC, start_time ASC""",
            {"start": day_start, "end": day_end},
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_today_events() -> list[dict]:
    return await get_events_for_date()


async def get_tomorrow_events() -> list[dict]:
    from datetime import datetime, timedelta

    tomorrow = (datetime.now() + timedelta(days=1)).date()
    return await get_events_for_date(tomorrow)


async def insert_readiness_scan(scan_data: dict) -> int:
    db = await get_db()
    try:
        cursor = await db.execute(
            """INSERT INTO readiness_scans
               (repo_url, owner, repo, score_total, score_agent_config,
                score_documentation, score_ci_quality, score_code_structure,
                score_security, grade, findings, scanned_at)
               VALUES (:repo_url, :owner, :repo, :score_total, :score_agent_config,
                       :score_documentation, :score_ci_quality, :score_code_structure,
                       :score_security, :grade, :findings, :scanned_at)""",
            scan_data,
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def get_readiness_history(limit: int = 20) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM readiness_scans ORDER BY scanned_at DESC LIMIT :limit",
            {"limit": limit},
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()
