"""Historical PR review collector -- configurable for any GitHub repository.

Fetches merged PRs, their reviews, and inline comments from GitHub,
then stores them in the ri_* tables for pattern analysis.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

from config import settings
from intelligence.db import (
    upsert_ri_pr,
    bulk_insert_ri_comments,
    get_latest_merged_at,
    count_ri_prs,
    comment_node_ids_exist,
)

logger = logging.getLogger("dashboard.intelligence.collector")

DEFAULT_REPOS: list[str] = settings.intelligence_default_repos

REPO_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/(?P<owner>[^/]+)/(?P<repo>[^/\s#?]+)"
)


def parse_repo_url(url: str) -> str:
    """Convert a GitHub URL or owner/repo string to 'owner/repo' format."""
    url = url.strip().rstrip("/")
    m = REPO_URL_RE.search(url)
    if m:
        return f"{m.group('owner')}/{m.group('repo').removesuffix('.git')}"
    parts = url.split("/")
    if len(parts) == 2 and parts[0] and parts[1]:
        return f"{parts[0]}/{parts[1].removesuffix('.git')}"
    raise ValueError(f"Cannot parse GitHub repo from: {url}")

GITHUB_API = "https://api.github.com"
MAX_PER_PAGE = 100
RATE_LIMIT_BUFFER = 100


def _github_headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.github_pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def _check_rate_limit(client: httpx.AsyncClient) -> int:
    """Return remaining API calls. Sleep if close to limit."""
    resp = await client.get("/rate_limit")
    if resp.status_code != 200:
        return 5000
    data = resp.json().get("resources", {}).get("core", {})
    remaining = data.get("remaining", 5000)
    reset_at = data.get("reset", 0)

    if remaining < RATE_LIMIT_BUFFER:
        wait = max(reset_at - int(datetime.now(timezone.utc).timestamp()), 10)
        logger.warning("Rate limit low (%d remaining), sleeping %ds", remaining, wait)
        await asyncio.sleep(wait)
    return remaining


async def _fetch_merged_prs(
    client: httpx.AsyncClient,
    repo: str,
    since: str,
) -> list[dict]:
    """Fetch all merged PRs for a repo since a given date."""
    prs: list[dict] = []
    page = 1

    while True:
        resp = await client.get(
            f"/repos/{repo}/pulls",
            params={
                "state": "closed",
                "sort": "updated",
                "direction": "desc",
                "per_page": MAX_PER_PAGE,
                "page": page,
            },
        )

        if resp.status_code == 403:
            await _check_rate_limit(client)
            continue
        if resp.status_code != 200:
            logger.error("Failed to fetch PRs for %s page %d: %s", repo, page, resp.status_code)
            break

        items = resp.json()
        if not items:
            break

        found_old = False
        for pr in items:
            if not pr.get("merged_at"):
                continue
            if pr["merged_at"] < since:
                found_old = True
                continue
            prs.append({
                "id": f"{repo}:{pr['number']}",
                "repo": repo,
                "number": pr["number"],
                "title": pr["title"],
                "author": pr["user"]["login"],
                "merged_at": pr["merged_at"],
                "base_branch": pr["base"]["ref"],
                "files_changed": pr.get("changed_files", 0),
                "additions": pr.get("additions", 0),
                "deletions": pr.get("deletions", 0),
                "description": (pr.get("body") or "")[:3000],
            })

        if found_old or len(items) < MAX_PER_PAGE:
            break
        page += 1
        await asyncio.sleep(0.5)

    return prs


async def _fetch_reviews(
    client: httpx.AsyncClient,
    repo: str,
    pr_number: int,
) -> list[dict]:
    """Fetch review submissions (APPROVED, CHANGES_REQUESTED, COMMENTED)."""
    reviews = []
    page = 1
    while True:
        resp = await client.get(
            f"/repos/{repo}/pulls/{pr_number}/reviews",
            params={"per_page": MAX_PER_PAGE, "page": page},
        )
        if resp.status_code == 403:
            await _check_rate_limit(client)
            continue
        if resp.status_code != 200:
            break
        items = resp.json()
        if not items:
            break
        for r in items:
            body = (r.get("body") or "").strip()
            if body:
                node_id = r.get("node_id", "") or hashlib.sha256(
                    f"{repo}:{pr_number}:review:{r.get('id','')}".encode()
                ).hexdigest()[:40]
                reviews.append({
                    "reviewer": r["user"]["login"],
                    "body": body,
                    "review_state": r.get("state", ""),
                    "created_at": r.get("submitted_at", ""),
                    "file_path": "",
                    "line_number": 0,
                    "node_id": node_id,
                })
        if len(items) < MAX_PER_PAGE:
            break
        page += 1
    return reviews


async def _fetch_review_comments(
    client: httpx.AsyncClient,
    repo: str,
    pr_number: int,
) -> list[dict]:
    """Fetch inline review comments with file path and line info."""
    comments = []
    page = 1
    while True:
        resp = await client.get(
            f"/repos/{repo}/pulls/{pr_number}/comments",
            params={"per_page": MAX_PER_PAGE, "page": page},
        )
        if resp.status_code == 403:
            await _check_rate_limit(client)
            continue
        if resp.status_code != 200:
            break
        items = resp.json()
        if not items:
            break
        for c in items:
            body = (c.get("body") or "").strip()
            if not body:
                continue
            user = c.get("user", {})
            if user.get("type") == "Bot":
                continue
            node_id = c.get("node_id", "") or hashlib.sha256(
                f"{repo}:{pr_number}:{c.get('id','')}".encode()
            ).hexdigest()[:40]
            comments.append({
                "reviewer": user.get("login", ""),
                "body": body,
                "review_state": "",
                "created_at": c.get("created_at", ""),
                "file_path": c.get("path", ""),
                "line_number": c.get("original_line") or c.get("line") or 0,
                "node_id": node_id,
            })
        if len(items) < MAX_PER_PAGE:
            break
        page += 1
    return comments


async def collect_repo(
    repo: str,
    since: str | None = None,
    progress_callback=None,
) -> dict:
    """Collect merged PRs and their reviews for a single repo.

    Returns stats dict with counts.
    """
    if not settings.github_pat:
        raise RuntimeError("GITHUB_PAT not configured")

    if since is None:
        latest = await get_latest_merged_at(repo)
        if latest:
            since = latest
        else:
            one_year_ago = datetime.now(timezone.utc) - timedelta(days=365)
            since = one_year_ago.isoformat()

    logger.info("Collecting reviews for %s since %s", repo, since)

    stats = {"repo": repo, "prs": 0, "comments": 0, "skipped": 0}

    async with httpx.AsyncClient(
        base_url=GITHUB_API,
        headers=_github_headers(),
        timeout=30,
    ) as client:
        await _check_rate_limit(client)

        prs = await _fetch_merged_prs(client, repo, since)
        logger.info("Found %d merged PRs for %s", len(prs), repo)

        for i, pr in enumerate(prs):
            await upsert_ri_pr(pr)
            stats["prs"] += 1

            pr_id = pr["id"]
            all_comments = []

            reviews = await _fetch_reviews(client, repo, pr["number"])
            for r in reviews:
                r["pr_id"] = pr_id
                r["category"] = ""
                all_comments.append(r)
            await asyncio.sleep(0.3)

            inline = await _fetch_review_comments(client, repo, pr["number"])
            for c in inline:
                c["pr_id"] = pr_id
                c["category"] = ""
                all_comments.append(c)
            await asyncio.sleep(0.3)

            if all_comments:
                node_ids = [c.get("node_id", "") for c in all_comments if c.get("node_id")]
                existing_ids = await comment_node_ids_exist(node_ids) if node_ids else set()
                new_comments = [c for c in all_comments if c.get("node_id", "") not in existing_ids]
                inserted = await bulk_insert_ri_comments(new_comments)
                stats["comments"] += inserted
                stats["skipped"] += len(all_comments) - len(new_comments)
            else:
                inserted = 0

            if progress_callback:
                progress_callback(repo, i + 1, len(prs), stats["comments"])

            if (i + 1) % 20 == 0:
                remaining = await _check_rate_limit(client)
                logger.info(
                    "  %s: %d/%d PRs processed, %d comments, %d API calls remaining",
                    repo, i + 1, len(prs), stats["comments"], remaining,
                )

    logger.info(
        "Collection complete for %s: %d PRs, %d comments",
        repo, stats["prs"], stats["comments"],
    )
    return stats


async def collect_all(
    repos: list[str] | None = None,
    since: str | None = None,
    progress_callback=None,
) -> list[dict]:
    """Collect reviews from all configured repos sequentially."""
    target_repos = repos or DEFAULT_REPOS
    all_stats = []

    for repo in target_repos:
        try:
            stats = await collect_repo(repo, since=since, progress_callback=progress_callback)
            all_stats.append(stats)
        except Exception:
            logger.exception("Failed to collect reviews for %s", repo)
            all_stats.append({"repo": repo, "prs": 0, "comments": 0, "error": True})
        await asyncio.sleep(1)

    total_prs = sum(s.get("prs", 0) for s in all_stats)
    total_comments = sum(s.get("comments", 0) for s in all_stats)
    logger.info(
        "Collection complete: %d repos, %d PRs, %d comments",
        len(all_stats), total_prs, total_comments,
    )
    return all_stats
