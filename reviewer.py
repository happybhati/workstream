"""AI-powered PR review engine.

Fetches diffs from GitHub/GitLab, sanitizes secrets, sends to a configured
AI provider, and returns structured review comments. Optionally posts
human-approved comments back to the VCS.
"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import quote_plus

import httpx

from config import settings

logger = logging.getLogger("dashboard.reviewer")

# ---------------------------------------------------------------------------
# Secret sanitization patterns
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(secret|token|api_key|apikey|api[-_]?secret)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(access_key|secret_key|aws_access|aws_secret)\s*[:=]\s*\S+"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)(connection[-_]?string|database[-_]?url|db[-_]?url)\s*[:=]\s*\S+"),
    re.compile(r"ghp_[A-Za-z0-9_]{36,}"),
    re.compile(r"glpat-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{32,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*"),
]


def sanitize_diff(diff: str) -> str:
    lines = diff.splitlines()
    cleaned = []
    for line in lines:
        sanitized = line
        for pat in _SECRET_PATTERNS:
            sanitized = pat.sub("[REDACTED]", sanitized)
        cleaned.append(sanitized)
    return "\n".join(cleaned)


# ---------------------------------------------------------------------------
# Provider availability
# ---------------------------------------------------------------------------


async def get_available_providers() -> list[dict]:
    """Return list of configured AI providers (names only, no keys)."""
    providers = []

    if settings.ai_claude_api_key:
        providers.append(
            {
                "id": "claude",
                "name": "Claude",
                "model": settings.ai_claude_model,
                "local": False,
            }
        )

    if settings.ai_gemini_api_key:
        providers.append(
            {
                "id": "gemini",
                "name": "Gemini",
                "model": settings.ai_gemini_model,
                "local": False,
            }
        )

    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{settings.ai_ollama_url}/api/tags")
            if resp.status_code == 200:
                providers.append(
                    {
                        "id": "ollama",
                        "name": "Ollama (local)",
                        "model": settings.ai_ollama_model,
                        "local": True,
                    }
                )
    except Exception:
        pass

    return providers


# ---------------------------------------------------------------------------
# Diff fetching
# ---------------------------------------------------------------------------


def _parse_pr_id(pr_id: str) -> tuple[str, str, int]:
    """Parse 'github:org/repo:42' into (platform, repo_full_name, number)."""
    parts = pr_id.split(":")
    if len(parts) < 3:
        raise ValueError(f"Invalid PR ID format: {pr_id}")
    platform = parts[0]
    repo = parts[1]
    number = int(parts[2])
    return platform, repo, number


async def _fetch_github_diff(repo: str, number: int) -> tuple[str, dict]:
    """Fetch unified diff and PR metadata from GitHub."""
    headers = {
        "Authorization": f"Bearer {settings.github_pat}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(
        base_url="https://api.github.com",
        headers=headers,
        timeout=60,
    ) as client:
        meta_resp = await client.get(
            f"/repos/{repo}/pulls/{number}",
            headers={"Accept": "application/vnd.github+json"},
        )
        meta_resp.raise_for_status()
        pr_data = meta_resp.json()

        diff_resp = await client.get(
            f"/repos/{repo}/pulls/{number}",
            headers={"Accept": "application/vnd.github.v3.diff"},
        )
        diff_resp.raise_for_status()

    metadata = {
        "title": pr_data.get("title", ""),
        "body": (pr_data.get("body") or "")[:2000],
        "author": pr_data.get("user", {}).get("login", ""),
        "base": pr_data.get("base", {}).get("ref", ""),
        "head": pr_data.get("head", {}).get("ref", ""),
        "additions": pr_data.get("additions", 0),
        "deletions": pr_data.get("deletions", 0),
        "changed_files": pr_data.get("changed_files", 0),
    }
    return diff_resp.text, metadata


async def _fetch_gitlab_diff(repo: str, number: int) -> tuple[str, dict]:
    """Fetch unified diff and MR metadata from GitLab."""
    headers = {"PRIVATE-TOKEN": settings.gitlab_pat}
    base = settings.gitlab_url.rstrip("/")
    api = f"{base}/api/v4"
    encoded = quote_plus(repo)

    async with httpx.AsyncClient(
        headers=headers,
        timeout=60,
        verify=False,
    ) as client:
        meta_resp = await client.get(
            f"{api}/projects/{encoded}/merge_requests/{number}",
        )
        meta_resp.raise_for_status()
        mr_data = meta_resp.json()

        changes_resp = await client.get(
            f"{api}/projects/{encoded}/merge_requests/{number}/diffs",
        )
        changes_resp.raise_for_status()

    diffs_list = changes_resp.json()
    diff_text_parts = []
    for d in diffs_list:
        header = f"diff --git a/{d.get('old_path', '')} b/{d.get('new_path', '')}\n"
        diff_text_parts.append(header + d.get("diff", ""))
    diff_text = "\n".join(diff_text_parts)

    metadata = {
        "title": mr_data.get("title", ""),
        "body": (mr_data.get("description") or "")[:2000],
        "author": mr_data.get("author", {}).get("username", ""),
        "base": mr_data.get("target_branch", ""),
        "head": mr_data.get("source_branch", ""),
        "additions": 0,
        "deletions": 0,
        "changed_files": len(diffs_list),
    }
    return diff_text, metadata


async def fetch_pr_diff(pr_id: str) -> tuple[str, dict]:
    platform, repo, number = _parse_pr_id(pr_id)
    if platform == "github":
        return await _fetch_github_diff(repo, number)
    elif platform == "gitlab":
        return await _fetch_gitlab_diff(repo, number)
    raise ValueError(f"Unsupported platform: {platform}")


# ---------------------------------------------------------------------------
# Review prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an expert senior software engineer performing a thorough code review.
Your goal is to catch real bugs, logic errors, race conditions, security issues,
and breaking changes that could affect production systems.

Rules:
- Focus on correctness, security, reliability, and maintainability.
- Flag missing error handling, unchecked edge cases, and test gaps.
- Do NOT comment on style, formatting, or naming unless it causes a real bug.
- Be specific: reference file names and line numbers from the diff.
- Explain WHY something is a problem and suggest a concrete fix.
- Be realistic — only flag genuine issues, not hypothetical nitpicks.

Return your review as valid JSON with this exact structure:
{
  "summary": "A 2-3 sentence overall assessment of the PR.",
  "comments": [
    {
      "file": "path/to/file.py",
      "line": 42,
      "body": "Explanation of the issue and suggested fix.",
      "severity": "critical"
    }
  ]
}

Severity levels:
- "critical": bugs, security vulnerabilities, data loss risks, breaking changes
- "warning": potential issues, missing error handling, race conditions
- "suggestion": improvements that would make the code more robust

If the PR looks good with no issues, return an empty comments array with a
positive summary. Always return valid JSON, nothing else.\
"""


def _get_team_context(pr_id: str) -> str:
    """Load team review intelligence context for a PR, if available.

    Uses synchronous sqlite3 since this runs in the review flow which
    may be called from both sync and async contexts.
    """
    import sqlite3

    try:
        parts = pr_id.split(":")
        repo = parts[1] if len(parts) >= 3 else ""
        if not repo:
            return ""

        db_path = str(settings.db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Check if ri_patterns table exists (may not on first run)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "ri_patterns" not in tables:
            conn.close()
            return ""

        rows = conn.execute(
            "SELECT category, pattern FROM ri_patterns WHERE repo = ? ORDER BY frequency DESC LIMIT 5",
            (repo,),
        ).fetchall()
        repo_patterns = [dict(r) for r in rows]

        rows = conn.execute(
            "SELECT reviewer, focus_areas FROM ri_reviewer_profiles ORDER BY total_comments DESC LIMIT 3"
        ).fetchall()

        rows2 = conn.execute(
            "SELECT c.category, COUNT(*) as cnt FROM ri_review_comments c "
            "JOIN ri_pull_requests p ON c.pr_id = p.id WHERE p.repo = ? "
            "AND c.category != '' GROUP BY c.category ORDER BY cnt DESC",
            (repo,),
        ).fetchall()
        focus_areas = {r["category"]: r["cnt"] for r in rows2}

        conn.close()

        if not repo_patterns and not focus_areas:
            return ""

        lines = [
            f"\n--- TEAM REVIEW CONTEXT FOR {repo} ---",
            "Review patterns collected from past team reviews on this repository:",
        ]
        if focus_areas:
            top = sorted(focus_areas.items(), key=lambda x: x[1], reverse=True)[:3]
            lines.append("Historically, reviewers focus most on:")
            for cat, cnt in top:
                lines.append(f"  - {cat} ({cnt} past comments)")
        if repo_patterns:
            lines.append("Recurring patterns flagged in past reviews:")
            for p in repo_patterns[:3]:
                lines.append(f"  [{p['category']}] {p['pattern']}")
        if rows:
            import json as _json

            lines.append("Key reviewer expectations:")
            for r in rows:
                areas_raw = r["focus_areas"] if r["focus_areas"] else "[]"
                try:
                    areas = _json.loads(areas_raw)
                except Exception:
                    areas = []
                if areas:
                    lines.append(f"  - {r['reviewer']} focuses on: {', '.join(str(a) for a in areas[:3])}")
        lines.append("--- END TEAM CONTEXT ---\n")
        return "\n".join(lines)

    except Exception as exc:
        logger.debug("Could not load team context: %s", exc)
        return ""


def build_review_prompt(metadata: dict, diff: str, pr_id: str = "") -> tuple[str, str]:
    """Return (system_prompt, user_prompt).

    If pr_id is provided and review intelligence data exists, the prompt
    is enriched with team context, patterns, and reviewer expectations.
    """
    team_context = _get_team_context(pr_id) if pr_id else ""

    user_prompt = f"""\
Review the following pull request.

**Title:** {metadata.get("title", "")}
**Author:** {metadata.get("author", "")}
**Branch:** {metadata.get("head", "")} → {metadata.get("base", "")}
**Files changed:** {metadata.get("changed_files", "?")} | \
+{metadata.get("additions", "?")} −{metadata.get("deletions", "?")}

**Description:**
{metadata.get("body", "No description provided.")}
{team_context}
**Diff:**
```
{diff[:80000]}
```"""
    return SYSTEM_PROMPT, user_prompt


# ---------------------------------------------------------------------------
# AI provider callers
# ---------------------------------------------------------------------------


def _extract_json(text: str) -> dict:
    """Extract JSON object from AI response that may include markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        start = 1
        end = len(lines)
        for i, line in enumerate(lines[1:], 1):
            if line.strip().startswith("```"):
                end = i
                break
        text = "\n".join(lines[start:end])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        brace_start = text.find("{")
        brace_end = text.rfind("}") + 1
        if brace_start >= 0 and brace_end > brace_start:
            return json.loads(text[brace_start:brace_end])
        raise


async def call_claude(system: str, user: str) -> dict:
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.ai_claude_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": settings.ai_claude_model,
                "max_tokens": 4096,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        resp.raise_for_status()
        content = resp.json()["content"][0]["text"]
        return _extract_json(content)


async def call_gemini(system: str, user: str) -> dict:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"models/{settings.ai_gemini_model}:generateContent"
        f"?key={settings.ai_gemini_api_key}"
    )
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            url,
            json={
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"parts": [{"text": user}]}],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 4096},
            },
        )
        resp.raise_for_status()
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        return _extract_json(text)


async def call_ollama(system: str, user: str) -> dict:
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{settings.ai_ollama_url}/api/chat",
            json={
                "model": settings.ai_ollama_model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        resp.raise_for_status()
        text = resp.json()["message"]["content"]
        return _extract_json(text)


_PROVIDER_MAP = {
    "claude": call_claude,
    "gemini": call_gemini,
    "ollama": call_ollama,
}


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


async def review_pr(pr_id: str, provider: str) -> dict:
    """Fetch diff, sanitize, call AI, return structured review."""
    import time as _time

    if provider not in _PROVIDER_MAP:
        raise ValueError(f"Unknown provider: {provider}")

    diff_raw, metadata = await fetch_pr_diff(pr_id)
    diff_clean = sanitize_diff(diff_raw)
    system, user = build_review_prompt(metadata, diff_clean, pr_id=pr_id)

    logger.info(
        "Requesting review from %s for %s (%d chars of diff)",
        provider,
        pr_id,
        len(diff_clean),
    )

    t0 = _time.monotonic()
    error_msg = ""
    status = "success"
    try:
        result = await _PROVIDER_MAP[provider](system, user)
    except Exception as exc:
        status = "error"
        error_msg = str(exc)
        raise
    finally:
        latency = int((_time.monotonic() - t0) * 1000)
        try:
            from agents.telemetry import record_event

            input_chars = len(system) + len(user)
            est_input_tokens = input_chars // 4
            est_output_tokens = 500
            model = ""
            if provider == "claude":
                model = settings.ai_claude_model
            elif provider == "gemini":
                model = settings.ai_gemini_model
            elif provider == "ollama":
                model = settings.ai_ollama_model
            record_event(
                "ai-review",
                "review_pr",
                provider=provider,
                model=model,
                input_tokens=est_input_tokens,
                output_tokens=est_output_tokens,
                latency_ms=latency,
                status=status,
                error=error_msg,
                metadata={"pr_id": pr_id},
            )
        except Exception:
            logger.debug("Telemetry recording failed", exc_info=True)

    if "summary" not in result:
        result["summary"] = "Review completed."
    if "comments" not in result:
        result["comments"] = []

    result["provider"] = provider
    result["pr_id"] = pr_id
    result["metadata"] = metadata
    return result


# ---------------------------------------------------------------------------
# Post review to VCS
# ---------------------------------------------------------------------------


async def post_review_to_github(repo: str, number: int, comments: list[dict]) -> dict:
    """Post review comments to a GitHub PR."""
    headers = {
        "Authorization": f"Bearer {settings.github_pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    body_parts = []
    for c in comments:
        severity = c.get("severity", "suggestion").upper()
        file_ref = c.get("file", "")
        line = c.get("line", "")
        loc = f"**{file_ref}**" + (f" (line {line})" if line else "")
        body_parts.append(f"**[{severity}]** {loc}\n{c.get('body', '')}")

    review_body = "\n\n---\n\n".join(body_parts)
    review_body = f"## AI-Assisted Review\n\n{review_body}"

    async with httpx.AsyncClient(
        base_url="https://api.github.com",
        headers=headers,
        timeout=30,
    ) as client:
        resp = await client.post(
            f"/repos/{repo}/pulls/{number}/reviews",
            json={"body": review_body, "event": "COMMENT"},
        )
        resp.raise_for_status()
        return {"status": "posted", "url": resp.json().get("html_url", "")}


async def post_review_to_gitlab(repo: str, number: int, comments: list[dict]) -> dict:
    """Post review comments to a GitLab MR as a note."""
    headers = {"PRIVATE-TOKEN": settings.gitlab_pat}
    base = settings.gitlab_url.rstrip("/")
    api = f"{base}/api/v4"
    encoded = quote_plus(repo)

    body_parts = []
    for c in comments:
        severity = c.get("severity", "suggestion").upper()
        file_ref = c.get("file", "")
        line = c.get("line", "")
        loc = f"**{file_ref}**" + (f" (line {line})" if line else "")
        body_parts.append(f"**[{severity}]** {loc}\n{c.get('body', '')}")

    note_body = "\n\n---\n\n".join(body_parts)
    note_body = f"## AI-Assisted Review\n\n{note_body}"

    async with httpx.AsyncClient(
        headers=headers,
        timeout=30,
        verify=False,
    ) as client:
        resp = await client.post(
            f"{api}/projects/{encoded}/merge_requests/{number}/notes",
            json={"body": note_body},
        )
        resp.raise_for_status()
        return {"status": "posted", "url": ""}


async def post_review(pr_id: str, comments: list[dict]) -> dict:
    """Post human-approved review comments to the correct VCS."""
    platform, repo, number = _parse_pr_id(pr_id)
    if platform == "github":
        return await post_review_to_github(repo, number, comments)
    elif platform == "gitlab":
        return await post_review_to_gitlab(repo, number, comments)
    raise ValueError(f"Unsupported platform: {platform}")
