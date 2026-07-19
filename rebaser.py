"""PR rebase engine.

Rebases pull request branches onto their base branch (or a custom target)
via the platform API (GitLab) or local git operations (GitHub).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from urllib.parse import quote_plus

import httpx

from config import settings

logger = logging.getLogger("dashboard.rebaser")

GITHUB_API = "https://api.github.com"
_REBASE_TIMEOUT = 120
_GITLAB_POLL_TIMEOUT = 60
_GITLAB_POLL_INTERVAL = 2


def _parse_pr_id(pr_id: str) -> tuple[str, str, int]:
    parts = pr_id.split(":")
    if len(parts) < 3:
        raise ValueError(f"Invalid PR ID format: {pr_id}")
    return parts[0], parts[1], int(parts[2])


# ---------------------------------------------------------------------------
# Branch info (shared by UI to pre-populate the rebase modal)
# ---------------------------------------------------------------------------


async def get_pr_branch_info(pr_id: str) -> dict:
    """Fetch head branch, base branch, and default branch for a PR."""
    platform, repo, number = _parse_pr_id(pr_id)
    if platform == "github":
        return await _github_branch_info(repo, number)
    if platform == "gitlab":
        return await _gitlab_branch_info(repo, number)
    return {"error": f"Unsupported platform: {platform}"}


async def _github_branch_info(repo: str, number: int) -> dict:
    headers = {
        "Authorization": f"Bearer {settings.github_pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(base_url=GITHUB_API, headers=headers, timeout=30) as client:
        pr_resp = await client.get(f"/repos/{repo}/pulls/{number}")
        if pr_resp.status_code != 200:
            return {"error": f"Cannot fetch PR: HTTP {pr_resp.status_code}"}
        pr_data = pr_resp.json()

        repo_resp = await client.get(f"/repos/{repo}")
        default_branch = "main"
        if repo_resp.status_code == 200:
            default_branch = repo_resp.json().get("default_branch", "main")

    base_ref = pr_data.get("base", {}).get("ref", "")
    head_ref = pr_data.get("head", {}).get("ref", "")
    behind_by = 0
    mergeable = pr_data.get("mergeable")
    merge_status = pr_data.get("mergeable_state", "")

    return {
        "platform": "github",
        "repo": repo,
        "number": number,
        "head_branch": head_ref,
        "base_branch": base_ref,
        "default_branch": default_branch,
        "behind_by": behind_by,
        "mergeable": mergeable,
        "merge_status": merge_status,
        "head_sha": pr_data.get("head", {}).get("sha", ""),
    }


async def _gitlab_branch_info(project_path: str, mr_iid: int) -> dict:
    encoded = quote_plus(project_path)
    headers = {"PRIVATE-TOKEN": settings.gitlab_pat}
    async with httpx.AsyncClient(
        base_url=settings.gitlab_url,
        headers=headers,
        timeout=30,
        verify=False,
        follow_redirects=True,
    ) as client:
        resp = await client.get(
            f"/api/v4/projects/{encoded}/merge_requests/{mr_iid}",
            params={"include_rebase_in_progress": "true"},
        )
        if resp.status_code != 200:
            return {"error": f"Cannot fetch MR: HTTP {resp.status_code}"}
        mr = resp.json()

    return {
        "platform": "gitlab",
        "repo": project_path,
        "number": mr_iid,
        "head_branch": mr.get("source_branch", ""),
        "base_branch": mr.get("target_branch", ""),
        "default_branch": mr.get("target_branch", ""),
        "behind_by": 0,
        "mergeable": mr.get("merge_status") not in ("cannot_be_merged",),
        "merge_status": mr.get("detailed_merge_status", mr.get("merge_status", "")),
        "rebase_in_progress": mr.get("rebase_in_progress", False),
    }


# ---------------------------------------------------------------------------
# Rebase dispatch
# ---------------------------------------------------------------------------


async def rebase_pr(pr_id: str, target_branch: str | None = None) -> dict:
    """Rebase a PR's head branch onto target_branch (default: PR's base)."""
    platform, repo, number = _parse_pr_id(pr_id)
    if platform == "github":
        return await _rebase_github(repo, number, target_branch)
    if platform == "gitlab":
        return await _rebase_gitlab(repo, number, target_branch)
    return {"status": "error", "message": f"Unsupported platform: {platform}"}


# ---------------------------------------------------------------------------
# GitHub: local git clone + rebase + force-push
# ---------------------------------------------------------------------------


async def _run_git(
    *args: str,
    cwd: str,
    timeout: int = 60,
) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": "Workstream",
            "GIT_COMMITTER_NAME": "Workstream",
            "PATH": "/usr/bin:/usr/local/bin:/opt/homebrew/bin",
            "HOME": str(__import__("pathlib").Path.home()),
        },
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return proc.returncode or 0, stdout.decode(), stderr.decode()


async def _rebase_github(repo: str, number: int, target_branch: str | None) -> dict:
    if not settings.github_pat:
        return {"status": "error", "message": "GITHUB_PAT not configured"}

    headers = {
        "Authorization": f"Bearer {settings.github_pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(base_url=GITHUB_API, headers=headers, timeout=30) as client:
        pr_resp = await client.get(f"/repos/{repo}/pulls/{number}")
        if pr_resp.status_code != 200:
            return {
                "status": "error",
                "message": f"Cannot fetch PR #{number}: HTTP {pr_resp.status_code}",
            }
        pr_data = pr_resp.json()

    head_branch = pr_data.get("head", {}).get("ref", "")
    base_branch = pr_data.get("base", {}).get("ref", "")
    head_repo_full = pr_data.get("head", {}).get("repo", {}).get("full_name", repo)

    if not head_branch:
        return {"status": "error", "message": "Cannot determine head branch"}

    rebase_onto = target_branch or base_branch
    if not rebase_onto:
        return {"status": "error", "message": "Cannot determine target branch"}

    is_fork = head_repo_full != repo
    clone_url = f"https://x-access-token:{settings.github_pat}@github.com/{repo}.git"

    tmpdir = tempfile.mkdtemp(prefix="ws-rebase-")
    logger.info(
        "Rebasing %s/%s#%d: %s onto %s",
        repo,
        head_branch,
        number,
        head_branch,
        rebase_onto,
    )

    try:
        rc, _, err = await _run_git(
            "clone",
            "--filter=blob:none",
            "--no-tags",
            clone_url,
            tmpdir + "/repo",
            cwd=tmpdir,
            timeout=60,
        )
        if rc != 0:
            logger.error("Clone failed: %s", err)
            return {"status": "error", "message": "Failed to clone repository"}

        work = tmpdir + "/repo"

        if is_fork:
            fork_url = f"https://x-access-token:{settings.github_pat}@github.com/{head_repo_full}.git"
            await _run_git("remote", "add", "fork", fork_url, cwd=work)
            rc, _, err = await _run_git("fetch", "fork", head_branch, cwd=work, timeout=60)
            if rc != 0:
                return {"status": "error", "message": "Failed to fetch fork branch"}
            rc, _, err = await _run_git("checkout", "-b", head_branch, f"fork/{head_branch}", cwd=work)
        else:
            rc, _, err = await _run_git("fetch", "origin", head_branch, cwd=work, timeout=30)
            if rc != 0:
                return {
                    "status": "error",
                    "message": f"Failed to fetch branch '{head_branch}'",
                }
            rc, _, err = await _run_git("checkout", "-b", head_branch, f"origin/{head_branch}", cwd=work)

        if rc != 0:
            return {"status": "error", "message": f"Failed to checkout '{head_branch}'"}

        rc, _, err = await _run_git("fetch", "origin", rebase_onto, cwd=work, timeout=30)
        if rc != 0:
            return {
                "status": "error",
                "message": f"Failed to fetch target branch '{rebase_onto}'",
            }

        rc, _, err = await _run_git("rebase", f"origin/{rebase_onto}", cwd=work, timeout=_REBASE_TIMEOUT)
        if rc != 0:
            await _run_git("rebase", "--abort", cwd=work, timeout=10)
            logger.warning("Rebase conflict for %s#%d: %s", repo, number, err[:300])
            return {
                "status": "conflict",
                "message": (
                    "Conflicts detected during rebase. "
                    "Please rebase and resolve conflicts manually "
                    "— this is not supported by Workstream yet."
                ),
            }

        push_remote = "fork" if is_fork else "origin"
        rc, _, err = await _run_git(
            "push",
            "--force-with-lease",
            push_remote,
            head_branch,
            cwd=work,
            timeout=30,
        )
        if rc != 0:
            logger.error("Push failed for %s#%d: %s", repo, number, err[:300])
            return {
                "status": "error",
                "message": ("Rebase succeeded but push failed. Someone may have pushed to this branch concurrently."),
            }

        logger.info("Rebase complete for %s#%d onto %s", repo, number, rebase_onto)
        return {
            "status": "ok",
            "message": f"Rebased '{head_branch}' onto '{rebase_onto}' successfully.",
        }

    except asyncio.TimeoutError:
        logger.error("Rebase timed out for %s#%d", repo, number)
        return {"status": "error", "message": "Rebase operation timed out (120s)"}
    except Exception as exc:
        logger.exception("Rebase failed for %s#%d", repo, number)
        return {"status": "error", "message": str(exc)}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# GitLab: native rebase API
# ---------------------------------------------------------------------------


async def _rebase_gitlab(project_path: str, mr_iid: int, target_branch: str | None) -> dict:
    if not settings.gitlab_pat:
        return {"status": "error", "message": "GITLAB_PAT not configured"}

    encoded = quote_plus(project_path)
    headers = {"PRIVATE-TOKEN": settings.gitlab_pat}

    async with httpx.AsyncClient(
        base_url=settings.gitlab_url,
        headers=headers,
        timeout=30,
        verify=False,
        follow_redirects=True,
    ) as client:
        mr_resp = await client.get(f"/api/v4/projects/{encoded}/merge_requests/{mr_iid}")
        if mr_resp.status_code != 200:
            return {
                "status": "error",
                "message": f"Cannot fetch MR !{mr_iid}: HTTP {mr_resp.status_code}",
            }
        mr_data = mr_resp.json()
        current_target = mr_data.get("target_branch", "")

        if target_branch and target_branch != current_target:
            update_resp = await client.put(
                f"/api/v4/projects/{encoded}/merge_requests/{mr_iid}",
                json={"target_branch": target_branch},
            )
            if update_resp.status_code not in (200, 201):
                return {
                    "status": "error",
                    "message": (f"Failed to update target branch to '{target_branch}': HTTP {update_resp.status_code}"),
                }
            logger.info(
                "Updated MR !%d target branch: %s -> %s",
                mr_iid,
                current_target,
                target_branch,
            )

        rebase_resp = await client.put(f"/api/v4/projects/{encoded}/merge_requests/{mr_iid}/rebase")

        if rebase_resp.status_code == 409:
            return {
                "status": "conflict",
                "message": (
                    "Conflicts detected during rebase. "
                    "Please rebase and resolve conflicts manually "
                    "— this is not supported by Workstream yet."
                ),
            }
        if rebase_resp.status_code == 403:
            return {
                "status": "error",
                "message": "Permission denied. You may not have push access.",
            }
        if rebase_resp.status_code not in (200, 202):
            return {
                "status": "error",
                "message": f"Rebase request failed: HTTP {rebase_resp.status_code}",
            }

        elapsed = 0
        while elapsed < _GITLAB_POLL_TIMEOUT:
            await asyncio.sleep(_GITLAB_POLL_INTERVAL)
            elapsed += _GITLAB_POLL_INTERVAL
            poll_resp = await client.get(
                f"/api/v4/projects/{encoded}/merge_requests/{mr_iid}",
                params={"include_rebase_in_progress": "true"},
            )
            if poll_resp.status_code != 200:
                continue
            poll_data = poll_resp.json()
            if not poll_data.get("rebase_in_progress", False):
                if poll_data.get("merge_error"):
                    return {
                        "status": "conflict",
                        "message": (
                            "Conflicts detected during rebase. "
                            "Please rebase and resolve conflicts manually "
                            "— this is not supported by Workstream yet."
                        ),
                    }
                rebase_target = target_branch or current_target
                logger.info(
                    "GitLab rebase complete for %s!%d onto %s",
                    project_path,
                    mr_iid,
                    rebase_target,
                )
                return {
                    "status": "ok",
                    "message": (f"Rebased onto '{rebase_target}' successfully."),
                }

        return {
            "status": "error",
            "message": "Rebase is still in progress after 60s. Check GitLab for status.",
        }
