from __future__ import annotations

import re
import logging
from datetime import datetime, timezone

import httpx

from config import settings
from database import (
    upsert_pr, insert_activity, upsert_jira_issue,
    upsert_active_sprint, upsert_yearly_completion,
    upsert_calendar_event, clear_calendar_events,
    cleanup_stale_prs, cleanup_stale_jira_issues,
)

logger = logging.getLogger("dashboard.pollers")

JIRA_KEY_PATTERN = re.compile(r"[A-Z][A-Z0-9]+-\d+")


def _extract_jira_key(title: str) -> str:
    match = JIRA_KEY_PATTERN.search(title)
    return match.group(0) if match else ""


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

async def poll_github() -> None:
    if not settings.github_pat or not settings.github_username:
        logger.warning("GitHub credentials not configured, skipping poll")
        return

    headers = {
        "Authorization": f"Bearer {settings.github_pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(base_url="https://api.github.com", headers=headers, timeout=30) as client:
        await _poll_github_authored(client)
        await _poll_github_recently_merged(client)
        await _poll_github_assigned(client)
        await _poll_github_review_requests(client)


async def _poll_github_authored(client: httpx.AsyncClient) -> None:
    query = f"is:pr author:{settings.github_username} state:open"
    resp = await client.get("/search/issues", params={"q": query, "per_page": 50})
    if resp.status_code != 200:
        logger.error("GitHub search failed: %s", resp.text)
        return

    for item in resp.json().get("items", []):
        repo_full = item["repository_url"].replace("https://api.github.com/repos/", "")
        pr_number = item["number"]

        pr_detail = await client.get(f"/repos/{repo_full}/pulls/{pr_number}")
        pr_data = pr_detail.json() if pr_detail.status_code == 200 else {}
        if pr_detail.status_code == 403:
            logger.debug("GitHub 403 for %s#%s (token may lack org access), using search data only", repo_full, pr_number)

        reviewers = ",".join(
            r["login"] for r in pr_data.get("requested_reviewers", [])
        )

        ci_info = await _get_github_checks(client, repo_full, pr_data.get("head", {}).get("sha", ""))

        review_info = {"review_state": "", "approved_by": ""}
        if pr_detail.status_code == 200:
            review_info = await _poll_github_pr_events(client, repo_full, pr_number)

        await upsert_pr({
            "id": f"github:{repo_full}:{pr_number}",
            "platform": "github",
            "repo_full_name": repo_full,
            "number": pr_number,
            "title": item["title"],
            "author": item["user"]["login"],
            "state": "draft" if pr_data.get("draft") else item["state"],
            "is_draft": 1 if pr_data.get("draft") else 0,
            "url": item["html_url"],
            "created_at": item["created_at"],
            "updated_at": item["updated_at"],
            "ci_status": ci_info["ci_status"],
            "review_requested_from": reviewers,
            "jira_key": _extract_jira_key(item["title"]),
            "additions": pr_data.get("additions", 0),
            "deletions": pr_data.get("deletions", 0),
            "comments_count": item.get("comments", 0),
            "review_state": review_info["review_state"],
            "approved_by": review_info["approved_by"],
            "ci_checks": ci_info["ci_checks"],
            "author_avatar": item.get("user", {}).get("avatar_url", ""),
        })


async def _poll_github_recently_merged(client: httpx.AsyncClient) -> None:
    """Fetch PRs merged in the last 30 days so the Merged stat is accurate."""
    from datetime import timedelta
    since = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    query = f"is:pr author:{settings.github_username} is:merged merged:>={since}"
    resp = await client.get("/search/issues", params={"q": query, "per_page": 50})
    if resp.status_code != 200:
        logger.error("GitHub merged search failed: %s", resp.text)
        return
    for item in resp.json().get("items", []):
        repo_full = item["repository_url"].replace("https://api.github.com/repos/", "")
        await upsert_pr({
            "id": f"github:{repo_full}:{item['number']}",
            "platform": "github",
            "repo_full_name": repo_full,
            "number": item["number"],
            "title": item["title"],
            "author": item["user"]["login"],
            "state": "merged",
            "is_draft": 0,
            "url": item["html_url"],
            "created_at": item["created_at"],
            "updated_at": item["updated_at"],
            "ci_status": "passing",
            "review_requested_from": "",
            "jira_key": _extract_jira_key(item["title"]),
            "additions": 0,
            "deletions": 0,
            "comments_count": item.get("comments", 0),
            "review_state": "",
            "approved_by": "",
            "author_avatar": item.get("user", {}).get("avatar_url", ""),
        })


async def _poll_github_assigned(client: httpx.AsyncClient) -> None:
    query = f"is:pr is:open assignee:{settings.github_username}"
    resp = await client.get("/search/issues", params={"q": query, "per_page": 50})
    if resp.status_code != 200:
        logger.error("GitHub assigned search failed: %s", resp.text)
        return

    for item in resp.json().get("items", []):
        repo_full = item["repository_url"].replace("https://api.github.com/repos/", "")
        pr_number = item["number"]

        pr_detail = await client.get(f"/repos/{repo_full}/pulls/{pr_number}")
        pr_data = pr_detail.json() if pr_detail.status_code == 200 else {}

        assignees = ",".join(
            a["login"] for a in pr_data.get("assignees", item.get("assignees", []))
        )
        reviewers = ",".join(
            r["login"] for r in pr_data.get("requested_reviewers", [])
        )

        ci_info = await _get_github_checks(client, repo_full, pr_data.get("head", {}).get("sha", ""))

        review_info = {"review_state": "", "approved_by": ""}
        if pr_detail.status_code == 200:
            review_info = await _poll_github_pr_events(client, repo_full, pr_number)

        await upsert_pr({
            "id": f"github:{repo_full}:{pr_number}",
            "platform": "github",
            "repo_full_name": repo_full,
            "number": pr_number,
            "title": item["title"],
            "author": item["user"]["login"],
            "state": "draft" if pr_data.get("draft") else item["state"],
            "is_draft": 1 if pr_data.get("draft") else 0,
            "url": item["html_url"],
            "created_at": item["created_at"],
            "updated_at": item["updated_at"],
            "ci_status": ci_info["ci_status"],
            "review_requested_from": reviewers,
            "assigned_to": assignees,
            "jira_key": _extract_jira_key(item["title"]),
            "additions": pr_data.get("additions", 0),
            "deletions": pr_data.get("deletions", 0),
            "comments_count": item.get("comments", 0),
            "review_state": review_info["review_state"],
            "approved_by": review_info["approved_by"],
            "ci_checks": ci_info["ci_checks"],
            "author_avatar": item.get("user", {}).get("avatar_url", ""),
        })


IGNORED_REVIEW_REPOS = set(settings.ignored_repos)

async def _poll_github_review_requests(client: httpx.AsyncClient) -> None:
    query = f"is:pr is:open review-requested:{settings.github_username}"
    resp = await client.get("/search/issues", params={"q": query, "per_page": 50})
    if resp.status_code != 200:
        logger.error("GitHub review-request search failed: %s", resp.text)
        return

    for item in resp.json().get("items", []):
        repo_full = item["repository_url"].replace("https://api.github.com/repos/", "")
        if repo_full in IGNORED_REVIEW_REPOS:
            continue
        pr_number = item["number"]

        pr_detail = await client.get(f"/repos/{repo_full}/pulls/{pr_number}")
        pr_data = pr_detail.json() if pr_detail.status_code == 200 else {}

        reviewers = ",".join(
            r["login"] for r in pr_data.get("requested_reviewers", [])
        )

        ci_info = await _get_github_checks(client, repo_full, pr_data.get("head", {}).get("sha", ""))

        review_info = {"review_state": "", "approved_by": ""}
        if pr_detail.status_code == 200:
            review_info = await _poll_github_pr_events(client, repo_full, pr_number)

        await upsert_pr({
            "id": f"github:{repo_full}:{pr_number}",
            "platform": "github",
            "repo_full_name": repo_full,
            "number": pr_number,
            "title": item["title"],
            "author": item["user"]["login"],
            "state": "draft" if pr_data.get("draft") else item["state"],
            "is_draft": 1 if pr_data.get("draft") else 0,
            "url": item["html_url"],
            "created_at": item["created_at"],
            "updated_at": item["updated_at"],
            "ci_status": ci_info["ci_status"],
            "review_requested_from": reviewers,
            "jira_key": _extract_jira_key(item["title"]),
            "additions": pr_data.get("additions", 0),
            "deletions": pr_data.get("deletions", 0),
            "comments_count": item.get("comments", 0),
            "review_state": review_info["review_state"],
            "approved_by": review_info["approved_by"],
            "ci_checks": ci_info["ci_checks"],
            "author_avatar": item.get("user", {}).get("avatar_url", ""),
        })


async def _get_github_checks(client: httpx.AsyncClient, repo: str, sha: str) -> dict:
    """Return {"ci_status": str, "ci_checks": str(JSON)} from GitHub Check Runs API."""
    import json as _json
    result = {"ci_status": "unknown", "ci_checks": ""}
    if not sha:
        return result
    resp = await client.get(
        f"/repos/{repo}/commits/{sha}/check-runs",
        params={"per_page": 100},
    )
    if resp.status_code != 200:
        return result

    runs = resp.json().get("check_runs", [])
    if not runs:
        return result

    checks = []
    for r in runs:
        conclusion = r.get("conclusion") or ""
        status = r.get("status", "queued")
        if status == "completed":
            normalized = {"success": "passing", "failure": "failing", "neutral": "passing",
                          "skipped": "skipped", "cancelled": "cancelled"}.get(conclusion, "unknown")
        else:
            normalized = "running"
        checks.append({
            "name": r.get("name", ""),
            "status": normalized,
            "url": r.get("html_url", ""),
        })

    failing = sum(1 for c in checks if c["status"] == "failing")
    running = sum(1 for c in checks if c["status"] == "running")
    if failing > 0:
        overall = "failing"
    elif running > 0:
        overall = "running"
    else:
        overall = "passing"

    result["ci_status"] = overall
    result["ci_checks"] = _json.dumps(checks)
    return result


async def _poll_github_pr_events(client: httpx.AsyncClient, repo: str, pr_number: int) -> dict:
    """Fetch reviews, store as activities, and return review summary."""
    result = {"review_state": "", "approved_by": ""}
    resp = await client.get(f"/repos/{repo}/pulls/{pr_number}/reviews")
    if resp.status_code != 200:
        return result

    latest_by_user: dict[str, str] = {}
    for review in resp.json():
        event_map = {
            "APPROVED": "approval",
            "CHANGES_REQUESTED": "change_request",
            "COMMENTED": "comment",
        }
        state = review.get("state", "")
        event_type = event_map.get(state, "comment")
        user = review["user"]["login"]

        if state in ("APPROVED", "CHANGES_REQUESTED"):
            latest_by_user[user] = state

        await insert_activity({
            "pr_id": f"github:{repo}:{pr_number}",
            "event_type": event_type,
            "actor": user,
            "body": (review.get("body") or "")[:500],
            "created_at": review["submitted_at"],
        })

    approvers = [u for u, s in latest_by_user.items() if s == "APPROVED"]
    has_changes_requested = any(s == "CHANGES_REQUESTED" for s in latest_by_user.values())

    if has_changes_requested:
        result["review_state"] = "changes_requested"
    elif approvers:
        result["review_state"] = "approved"

    result["approved_by"] = ",".join(approvers)
    return result


# ---------------------------------------------------------------------------
# GitLab
# ---------------------------------------------------------------------------

async def poll_gitlab() -> None:
    if not settings.gitlab_pat or not settings.gitlab_username:
        logger.warning("GitLab credentials not configured, skipping poll")
        return

    headers = {"PRIVATE-TOKEN": settings.gitlab_pat}
    base = settings.gitlab_url.rstrip("/")
    api = f"{base}/api/v4"

    async with httpx.AsyncClient(headers=headers, timeout=30, verify=False) as client:
        await _poll_gitlab_authored(client, api)
        await _poll_gitlab_recently_merged(client, api)
        await _poll_gitlab_assigned(client, api)
        await _poll_gitlab_review_requests(client, api)


async def _get_gitlab_approval_state(client: httpx.AsyncClient, api: str, project_id: int, mr_iid: int) -> dict:
    """Fetch MR approval info from GitLab."""
    result = {"review_state": "", "approved_by": ""}
    resp = await client.get(f"{api}/projects/{project_id}/merge_requests/{mr_iid}/approvals")
    if resp.status_code != 200:
        return result
    data = resp.json()
    approvers = [a["user"]["username"] for a in data.get("approved_by", [])]
    if approvers:
        result["review_state"] = "approved"
        result["approved_by"] = ",".join(approvers)
    return result


async def _get_gitlab_checks(client: httpx.AsyncClient, api: str, project_id: int, pipeline: dict) -> dict:
    """Return {"ci_status": str, "ci_checks": str(JSON)} from GitLab pipeline jobs."""
    import json as _json
    ci_map = {"success": "passing", "failed": "failing", "running": "running", "pending": "running"}
    overall = ci_map.get(pipeline.get("status", ""), "unknown")
    result = {"ci_status": overall, "ci_checks": ""}

    pid = pipeline.get("id")
    if not pid:
        return result

    resp = await client.get(f"{api}/projects/{project_id}/pipelines/{pid}/jobs", params={"per_page": 100})
    if resp.status_code != 200:
        return result

    gl_map = {"success": "passing", "failed": "failing", "running": "running",
              "pending": "running", "canceled": "cancelled", "skipped": "skipped",
              "manual": "skipped", "created": "running"}
    checks = []
    for job in resp.json():
        checks.append({
            "name": job.get("name", ""),
            "status": gl_map.get(job.get("status", ""), "unknown"),
            "url": job.get("web_url", ""),
        })

    if checks:
        result["ci_checks"] = _json.dumps(checks)
    return result


async def _poll_gitlab_authored(client: httpx.AsyncClient, api: str) -> None:
    resp = await client.get(
        f"{api}/merge_requests",
        params={"scope": "created_by_me", "state": "opened", "per_page": 50},
    )
    if resp.status_code != 200:
        logger.error("GitLab authored MRs failed: %s", resp.text)
        return

    for mr in resp.json():
        project_path = mr["references"]["full"].rsplit("!", 1)[0]
        reviewers = ",".join(r["username"] for r in mr.get("reviewers", []))

        pipeline = mr.get("head_pipeline") or {}
        ci_info = await _get_gitlab_checks(client, api, mr["project_id"], pipeline)

        approval = await _get_gitlab_approval_state(client, api, mr["project_id"], mr["iid"])

        await upsert_pr({
            "id": f"gitlab:{project_path}:{mr['iid']}",
            "platform": "gitlab",
            "repo_full_name": project_path,
            "number": mr["iid"],
            "title": mr["title"],
            "author": mr["author"]["username"],
            "state": "draft" if mr.get("draft") else mr["state"],
            "is_draft": 1 if mr.get("draft") else 0,
            "url": mr["web_url"],
            "created_at": mr["created_at"],
            "updated_at": mr["updated_at"],
            "ci_status": ci_info["ci_status"],
            "review_requested_from": reviewers,
            "jira_key": _extract_jira_key(mr["title"]),
            "additions": mr.get("changes_count", 0) if isinstance(mr.get("changes_count"), int) else 0,
            "deletions": 0,
            "comments_count": mr.get("user_notes_count", 0),
            "review_state": approval["review_state"],
            "approved_by": approval["approved_by"],
            "ci_checks": ci_info["ci_checks"],
            "author_avatar": mr.get("author", {}).get("avatar_url", ""),
        })


async def _poll_gitlab_recently_merged(client: httpx.AsyncClient, api: str) -> None:
    """Fetch MRs merged in the last 30 days."""
    from datetime import timedelta
    since = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")
    resp = await client.get(
        f"{api}/merge_requests",
        params={"scope": "created_by_me", "state": "merged", "updated_after": since, "per_page": 50},
    )
    if resp.status_code != 200:
        logger.error("GitLab merged MRs failed: %s", resp.text)
        return
    for mr in resp.json():
        project_path = mr["references"]["full"].rsplit("!", 1)[0]
        await upsert_pr({
            "id": f"gitlab:{project_path}:{mr['iid']}",
            "platform": "gitlab",
            "repo_full_name": project_path,
            "number": mr["iid"],
            "title": mr["title"],
            "author": mr["author"]["username"],
            "state": "merged",
            "is_draft": 0,
            "url": mr["web_url"],
            "created_at": mr["created_at"],
            "updated_at": mr["updated_at"],
            "ci_status": "passing",
            "review_requested_from": "",
            "jira_key": _extract_jira_key(mr["title"]),
            "additions": 0,
            "deletions": 0,
            "comments_count": mr.get("user_notes_count", 0),
            "review_state": "",
            "approved_by": "",
            "author_avatar": mr.get("author", {}).get("avatar_url", ""),
        })


async def _poll_gitlab_assigned(client: httpx.AsyncClient, api: str) -> None:
    resp = await client.get(
        f"{api}/merge_requests",
        params={"scope": "assigned_to_me", "state": "opened", "per_page": 50},
    )
    if resp.status_code != 200:
        logger.error("GitLab assigned MRs failed: %s", resp.text)
        return

    for mr in resp.json():
        project_path = mr["references"]["full"].rsplit("!", 1)[0]
        assignees = ",".join(a["username"] for a in mr.get("assignees", []))
        reviewers = ",".join(r["username"] for r in mr.get("reviewers", []))

        pipeline = mr.get("head_pipeline") or {}
        ci_info = await _get_gitlab_checks(client, api, mr["project_id"], pipeline)

        approval = await _get_gitlab_approval_state(client, api, mr["project_id"], mr["iid"])

        await upsert_pr({
            "id": f"gitlab:{project_path}:{mr['iid']}",
            "platform": "gitlab",
            "repo_full_name": project_path,
            "number": mr["iid"],
            "title": mr["title"],
            "author": mr["author"]["username"],
            "state": "draft" if mr.get("draft") else mr["state"],
            "is_draft": 1 if mr.get("draft") else 0,
            "url": mr["web_url"],
            "created_at": mr["created_at"],
            "updated_at": mr["updated_at"],
            "ci_status": ci_info["ci_status"],
            "review_requested_from": reviewers,
            "assigned_to": assignees,
            "jira_key": _extract_jira_key(mr["title"]),
            "additions": mr.get("changes_count", 0) if isinstance(mr.get("changes_count"), int) else 0,
            "deletions": 0,
            "comments_count": mr.get("user_notes_count", 0),
            "review_state": approval["review_state"],
            "approved_by": approval["approved_by"],
            "ci_checks": ci_info["ci_checks"],
            "author_avatar": mr.get("author", {}).get("avatar_url", ""),
        })


async def _poll_gitlab_review_requests(client: httpx.AsyncClient, api: str) -> None:
    resp = await client.get(
        f"{api}/merge_requests",
        params={"scope": "all", "reviewer_username": settings.gitlab_username, "state": "opened", "per_page": 50},
    )
    if resp.status_code != 200:
        logger.error("GitLab review MRs failed: %s", resp.text)
        return

    for mr in resp.json():
        project_path = mr["references"]["full"].rsplit("!", 1)[0]
        reviewers = ",".join(r["username"] for r in mr.get("reviewers", []))

        pipeline = mr.get("head_pipeline") or {}
        ci_info = await _get_gitlab_checks(client, api, mr["project_id"], pipeline)

        approval = await _get_gitlab_approval_state(client, api, mr["project_id"], mr["iid"])

        await upsert_pr({
            "id": f"gitlab:{project_path}:{mr['iid']}",
            "platform": "gitlab",
            "repo_full_name": project_path,
            "number": mr["iid"],
            "title": mr["title"],
            "author": mr["author"]["username"],
            "state": "draft" if mr.get("draft") else mr["state"],
            "is_draft": 1 if mr.get("draft") else 0,
            "url": mr["web_url"],
            "created_at": mr["created_at"],
            "updated_at": mr["updated_at"],
            "ci_status": ci_info["ci_status"],
            "review_requested_from": reviewers,
            "jira_key": _extract_jira_key(mr["title"]),
            "additions": mr.get("changes_count", 0) if isinstance(mr.get("changes_count"), int) else 0,
            "deletions": 0,
            "comments_count": mr.get("user_notes_count", 0),
            "review_state": approval["review_state"],
            "approved_by": approval["approved_by"],
            "ci_checks": ci_info["ci_checks"],
            "author_avatar": mr.get("author", {}).get("avatar_url", ""),
        })


# ---------------------------------------------------------------------------
# Jira issue polling
# ---------------------------------------------------------------------------

STATUS_CATEGORY_MAP = {
    "new": "new", "to do": "new", "open": "new", "backlog": "new",
    "refinement": "new",
    "in progress": "in_progress", "in development": "in_progress",
    "review": "in_review", "in review": "in_review", "code review": "in_review",
    "release pending": "release_pending",
    "done": "done", "closed": "done", "resolved": "done",
}


def _normalize_status(status_name: str) -> str:
    return STATUS_CATEGORY_MAP.get(status_name.lower().strip(), "new")


def _parse_sprint(fields: dict) -> tuple[str, str]:
    """Extract the most relevant sprint name and state from the issue fields."""
    sprint_field = fields.get("sprint")
    if sprint_field and isinstance(sprint_field, dict):
        return sprint_field.get("name", ""), sprint_field.get("state", "")
    # customfield_10020 is the common sprint field in Jira Cloud
    sprints = fields.get("customfield_10020")
    if sprints and isinstance(sprints, list):
        for s in reversed(sprints):
            if isinstance(s, dict) and s.get("state") == "active":
                return s.get("name", ""), "active"
        last = sprints[-1] if sprints else None
        if isinstance(last, dict):
            return last.get("name", ""), last.get("state", "")
    return "", ""


async def poll_jira_issues() -> None:
    if not settings.jira_url or not settings.jira_api_token or not settings.jira_projects:
        logger.warning("Jira issue polling not configured, skipping")
        return

    projects = ", ".join(settings.jira_projects)
    auth = httpx.BasicAuth(settings.jira_email, settings.jira_api_token)
    base = settings.jira_url.rstrip("/")
    fields = "summary,status,issuetype,priority,assignee,reporter,sprint,customfield_10020,updated,created"

    async with httpx.AsyncClient(auth=auth, timeout=30) as client:
        # Query 1: assigned to current user
        jql_assigned = (
            f"project IN ({projects}) AND assignee = currentUser() "
            f"AND statusCategory != Done ORDER BY updated DESC"
        )
        await _fetch_jira_issues(client, base, jql_assigned, fields, "assignee")

        # Query 2: reported by current user
        jql_reporter = (
            f"project IN ({projects}) AND reporter = currentUser() "
            f"AND statusCategory != Done ORDER BY updated DESC"
        )
        await _fetch_jira_issues(client, base, jql_reporter, fields, "reporter")

        # Query 3: release pending assigned to current user
        jql_release_pending = (
            f"project IN ({projects}) AND assignee = currentUser() "
            f'AND status = "Release Pending" ORDER BY updated DESC'
        )
        await _fetch_jira_issues(client, base, jql_release_pending, fields, "assignee")

        # Query 4: recently done (last 7 days) for the done tab
        jql_done = (
            f"project IN ({projects}) AND (assignee = currentUser() OR reporter = currentUser()) "
            f'AND statusCategory = Done AND status != "Release Pending" '
            f"AND updated >= -7d ORDER BY updated DESC"
        )
        await _fetch_jira_issues(client, base, jql_done, fields, "")


async def _fetch_jira_issues(client: httpx.AsyncClient, base: str,
                              jql: str, fields: str, role: str) -> None:
    start_at = 0
    while True:
        resp = await client.get(
            f"{base}/rest/api/3/search/jql",
            params={"jql": jql, "fields": fields, "maxResults": 50, "startAt": start_at},
        )
        if resp.status_code != 200:
            logger.error("Jira search failed (%s): %s", resp.status_code, resp.text[:300])
            return

        data = resp.json()
        issues = data.get("issues", [])
        if not issues:
            break

        for issue in issues:
            f = issue.get("fields", {})
            status_name = f.get("status", {}).get("name", "")
            sprint_name, sprint_state = _parse_sprint(f)

            assignee_obj = f.get("assignee") or {}
            reporter_obj = f.get("reporter") or {}

            issue_role = role
            if not issue_role:
                acct = settings.jira_account_name.lower()
                email_prefix = settings.jira_email.split("@")[0].lower() if settings.jira_email else acct

                def _user_matches(user_obj: dict) -> bool:
                    name = user_obj.get("displayName", "").lower()
                    email = user_obj.get("emailAddress", "").lower()
                    return (acct in email or email_prefix in email
                            or acct in name or email_prefix in name)

                is_assignee = _user_matches(assignee_obj)
                is_reporter = _user_matches(reporter_obj)
                if is_assignee and is_reporter:
                    issue_role = "both"
                elif is_assignee:
                    issue_role = "assignee"
                elif is_reporter:
                    issue_role = "reporter"

            await upsert_jira_issue({
                "key": issue["key"],
                "project": issue["key"].rsplit("-", 1)[0],
                "summary": f.get("summary", ""),
                "status": status_name,
                "status_category": _normalize_status(status_name),
                "issue_type": f.get("issuetype", {}).get("name", ""),
                "priority": f.get("priority", {}).get("name", ""),
                "assignee": assignee_obj.get("displayName", ""),
                "reporter": reporter_obj.get("displayName", ""),
                "sprint_name": sprint_name,
                "sprint_state": sprint_state,
                "url": f"{base}/browse/{issue['key']}",
                "created_at": f.get("created", ""),
                "updated_at": f.get("updated", ""),
                "role": issue_role,
            })

        logger.info("Jira fetched %d issues (startAt=%d, role=%s)", len(issues), start_at, role or "done")
        if start_at + len(issues) >= data.get("total", 0):
            break
        start_at += len(issues)


# ---------------------------------------------------------------------------
# Jira yearly completion counts
# ---------------------------------------------------------------------------

async def _count_jira_issues(client, base, jql) -> int:
    total = 0
    next_token: str | None = None
    while True:
        params: dict = {"jql": jql, "fields": "key", "maxResults": 100}
        if next_token:
            params["nextPageToken"] = next_token
        resp = await client.get(f"{base}/rest/api/3/search/jql", params=params)
        if resp.status_code != 200:
            logger.error("Jira count query failed: %s", resp.text[:200])
            break
        data = resp.json()
        total += len(data.get("issues", []))
        if data.get("isLast", True):
            break
        next_token = data.get("nextPageToken")
        if not next_token:
            break
    return total


async def poll_yearly_completions() -> None:
    if not settings.jira_url or not settings.jira_api_token or not settings.jira_projects:
        return

    projects = ", ".join(settings.jira_projects)
    auth = httpx.BasicAuth(settings.jira_email, settings.jira_api_token)
    base = settings.jira_url.rstrip("/")
    now = datetime.now(timezone.utc)
    done_statuses = '"Done", "Closed", "Resolved", "Release Pending"'
    same_date_last_year = f"{now.year - 1}-{now.month:02d}-{now.day:02d}"

    async with httpx.AsyncClient(auth=auth, timeout=30) as client:
        # Current year (full so far)
        jql_this = (
            f"project IN ({projects}) AND assignee = currentUser() "
            f"AND status IN ({done_statuses}) "
            f'AND updated >= "{now.year}-01-01" AND updated < "{now.year + 1}-01-01"'
        )
        this_total = await _count_jira_issues(client, base, jql_this)
        await upsert_yearly_completion(now.year, this_total, same_period=0)
        logger.info("Jira completions %d: %d issues", now.year, this_total)

        # Last year full + same period
        last_year = now.year - 1
        jql_last_full = (
            f"project IN ({projects}) AND assignee = currentUser() "
            f"AND status IN ({done_statuses}) "
            f'AND updated >= "{last_year}-01-01" AND updated < "{last_year + 1}-01-01"'
        )
        last_full = await _count_jira_issues(client, base, jql_last_full)

        jql_last_same = (
            f"project IN ({projects}) AND assignee = currentUser() "
            f"AND status IN ({done_statuses}) "
            f'AND updated >= "{last_year}-01-01" AND updated <= "{same_date_last_year}"'
        )
        last_same_period = await _count_jira_issues(client, base, jql_last_same)

        await upsert_yearly_completion(last_year, last_full, same_period=last_same_period)
        logger.info("Jira completions %d: %d full, %d by same date", last_year, last_full, last_same_period)


# ---------------------------------------------------------------------------
# Jira active sprint polling (Agile API)
# ---------------------------------------------------------------------------

async def poll_active_sprints() -> None:
    if not settings.jira_url or not settings.jira_api_token or not settings.jira_projects:
        return

    auth = httpx.BasicAuth(settings.jira_email, settings.jira_api_token)
    base = settings.jira_url.rstrip("/")

    async with httpx.AsyncClient(auth=auth, timeout=30) as client:
        for project in settings.jira_projects:
            try:
                board_resp = await client.get(
                    f"{base}/rest/agile/1.0/board",
                    params={"projectKeyOrId": project, "type": "scrum"},
                )
                if board_resp.status_code != 200:
                    logger.debug("No scrum board for %s: %s", project, board_resp.status_code)
                    continue

                boards = board_resp.json().get("values", [])
                if not boards:
                    continue

                board_id = boards[0]["id"]

                sprint_resp = await client.get(
                    f"{base}/rest/agile/1.0/board/{board_id}/sprint",
                    params={"state": "active"},
                )
                if sprint_resp.status_code != 200:
                    logger.debug("No active sprint for board %s: %s", board_id, sprint_resp.status_code)
                    continue

                sprints = sprint_resp.json().get("values", [])
                if not sprints:
                    continue

                s = sprints[0]
                await upsert_active_sprint({
                    "project": project,
                    "sprint_id": s["id"],
                    "board_id": board_id,
                    "name": s.get("name", ""),
                    "state": s.get("state", "active"),
                    "start_date": s.get("startDate", ""),
                    "end_date": s.get("endDate", ""),
                    "goal": s.get("goal", "") or "",
                })
                logger.info("Sprint for %s: %s (ends %s)", project, s.get("name"), s.get("endDate", "")[:10])

            except Exception:
                logger.exception("Failed to fetch sprint for project %s", project)


# ---------------------------------------------------------------------------
# Jira enrichment (adds ticket status to PRs that have a jira_key)
# ---------------------------------------------------------------------------

async def enrich_jira() -> None:
    if not settings.jira_url or not settings.jira_api_token:
        logger.warning("Jira credentials not configured, skipping enrichment")
        return

    import aiosqlite
    from database import DB_PATH

    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    try:
        cursor = await db.execute(
            "SELECT DISTINCT jira_key FROM pull_requests WHERE jira_key != ''"
        )
        keys = [row["jira_key"] for row in await cursor.fetchall()]
    finally:
        await db.close()

    if not keys:
        return

    auth = httpx.BasicAuth(settings.jira_email, settings.jira_api_token)
    base = settings.jira_url.rstrip("/")

    async with httpx.AsyncClient(auth=auth, timeout=30) as client:
        for key in keys:
            resp = await client.get(
                f"{base}/rest/api/3/issue/{key}",
                params={"fields": "status,priority"},
            )
            if resp.status_code != 200:
                continue
            data = resp.json()
            status = data.get("fields", {}).get("status", {}).get("name", "")
            logger.info("Jira %s status: %s", key, status)


# ---------------------------------------------------------------------------
# Google Calendar
# ---------------------------------------------------------------------------

GCAL_SCOPES = ["https://www.googleapis.com/auth/calendar.events.readonly"]


def _get_google_credentials():
    """Load or create Google OAuth2 credentials. Returns None if not configured."""
    from pathlib import Path
    creds_path = settings.google_credentials_path
    token_path = settings.google_token_path

    if not creds_path.exists():
        logger.info("Google Calendar: no credentials file at %s, skipping", creds_path)
        return None

    creds = None
    if token_path.exists():
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_file(str(token_path), GCAL_SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        try:
            creds.refresh(Request())
            token_path.write_text(creds.to_json())
            return creds
        except Exception:
            logger.warning("Google Calendar: token refresh failed, re-authenticating")

    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), GCAL_SCOPES)
    creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json())
    logger.info("Google Calendar: authenticated successfully, token saved")
    return creds


async def poll_google_calendar() -> None:
    import asyncio
    creds = await asyncio.to_thread(_get_google_credentials)
    if not creds:
        return

    from googleapiclient.discovery import build

    from datetime import timedelta

    now = datetime.now(timezone.utc)
    local_now = datetime.now()
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_end = (day_start + timedelta(days=1)).replace(hour=23, minute=59, second=59)

    time_min = day_start.astimezone(timezone.utc).isoformat()
    time_max = tomorrow_end.astimezone(timezone.utc).isoformat()

    def _fetch_events():
        service = build("calendar", "v3", credentials=creds)
        all_events = []
        for cal_id in settings.google_calendar_ids:
            try:
                result = service.events().list(
                    calendarId=cal_id.strip(),
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=50,
                ).execute()
                all_events.extend(
                    (cal_id.strip(), e) for e in result.get("items", [])
                )
            except Exception:
                logger.exception("Google Calendar: failed to fetch calendar %s", cal_id)
        return all_events

    events = await asyncio.to_thread(_fetch_events)

    await clear_calendar_events()

    for cal_id, event in events:
        start = event.get("start", {})
        end_field = event.get("end", {})
        is_all_day = "date" in start

        start_time = start.get("dateTime", start.get("date", ""))
        end_time = end_field.get("dateTime", end_field.get("date", ""))

        meet_link = ""
        for ep in event.get("conferenceData", {}).get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                meet_link = ep.get("uri", "")
                break

        attendees = event.get("attendees", [])
        attendee_count = len([a for a in attendees if a.get("responseStatus") != "declined"])

        await upsert_calendar_event({
            "event_id": event["id"],
            "calendar_id": cal_id,
            "summary": event.get("summary", "(No title)"),
            "start_time": start_time,
            "end_time": end_time,
            "meet_link": meet_link,
            "attendee_count": attendee_count,
            "status": event.get("status", "confirmed"),
            "is_all_day": 1 if is_all_day else 0,
            "location": event.get("location", ""),
            "polled_at": now.isoformat(),
        })

    logger.info("Google Calendar: fetched %d events (today + tomorrow)", len(events))


# ---------------------------------------------------------------------------
# Main poll orchestrator
# ---------------------------------------------------------------------------

async def poll_all() -> None:
    cycle_start = datetime.now(timezone.utc).isoformat()
    logger.info("Starting poll cycle at %s", cycle_start)
    try:
        await poll_github()
    except Exception:
        logger.exception("GitHub poll failed")
    try:
        await poll_gitlab()
    except Exception:
        logger.exception("GitLab poll failed")
    try:
        await poll_jira_issues()
    except Exception:
        logger.exception("Jira issue poll failed")
    try:
        await poll_active_sprints()
    except Exception:
        logger.exception("Jira sprint poll failed")
    try:
        await poll_yearly_completions()
    except Exception:
        logger.exception("Jira yearly completions poll failed")
    try:
        await enrich_jira()
    except Exception:
        logger.exception("Jira enrichment failed")
    try:
        await poll_google_calendar()
    except Exception:
        logger.exception("Google Calendar poll failed")

    stale_prs = await cleanup_stale_prs(cycle_start)
    stale_jira = await cleanup_stale_jira_issues(cycle_start)
    if stale_prs or stale_jira:
        logger.info("Cleanup: marked %d stale PRs closed, removed %d stale Jira issues", stale_prs, stale_jira)
    logger.info("Poll cycle complete")
