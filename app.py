from __future__ import annotations

import asyncio
import logging
import logging.handlers
import os
import signal
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from database import (
    get_active_sprints,
    get_assigned_prs,
    get_jira_stats,
    get_jira_tasks,
    get_my_prs,
    get_recent_activities,
    get_review_requests,
    get_sprint_tasks,
    get_today_events,
    get_tomorrow_events,
    get_yearly_completions,
    init_db,
)
from pollers import poll_all
from reviewer import (
    build_review_prompt,
    fetch_pr_diff,
    get_available_providers,
    post_review,
    review_pr,
    sanitize_diff,
)

LOG_DIR = settings.log_dir
LOG_DIR.mkdir(parents=True, exist_ok=True)

handlers: list[logging.Handler] = [
    logging.StreamHandler(sys.stdout),
    logging.handlers.RotatingFileHandler(
        LOG_DIR / "workstream.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
    ),
]
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=handlers,
)
logger = logging.getLogger("dashboard")

STATIC_DIR = Path(__file__).parent / "static"

poll_task: asyncio.Task | None = None


async def _poll_loop() -> None:
    from agents.activity_stream import emit_event

    while True:
        try:
            emit_event("tool_start", "workstream", category="operation", data={"tool": "poll_all"})
            await poll_all()
            emit_event("tool_end", "workstream", category="operation", data={"tool": "poll_all", "status": "success"})
        except Exception:
            logger.exception("Poll loop error")
            emit_event("tool_end", "workstream", category="operation", data={"tool": "poll_all", "status": "error"})
        await asyncio.sleep(settings.poll_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global poll_task
    await init_db()
    poll_task = asyncio.create_task(_poll_loop())
    logger.info(
        "Workstream started -- polling every %ds. Open http://localhost:8080",
        settings.poll_interval_seconds,
    )
    yield
    if poll_task:
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Workstream", lifespan=lifespan)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Optional bearer-token gate. Active only when WORKSTREAM_AUTH_TOKEN is set."""
    token = os.getenv("WORKSTREAM_AUTH_TOKEN", "")
    if not token:
        return await call_next(request)

    if request.url.path in ("/api/health",):
        return await call_next(request)

    auth_header = request.headers.get("authorization", "")
    query_token = request.query_params.get("token", "")

    if auth_header == f"Bearer {token}" or query_token == token:
        return await call_next(request)

    return JSONResponse({"error": "unauthorized"}, status_code=401)


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/health")
async def api_health():
    """Health check endpoint for container orchestration and monitoring."""
    return JSONResponse({"status": "ok"})


@app.get("/api/config")
async def api_config():
    """Expose non-secret configuration to the frontend."""
    return JSONResponse(
        {
            "jira_url": settings.jira_url,
            "jira_board_projects": settings.jira_board_projects,
            "display_name": settings.display_name,
        }
    )


@app.get("/api/my-prs")
async def api_my_prs():
    prs = await get_my_prs(settings.github_username, settings.gitlab_username)
    return JSONResponse(prs)


@app.get("/api/assigned")
async def api_assigned():
    prs = await get_assigned_prs(settings.github_username, settings.gitlab_username)
    return JSONResponse(prs)


@app.get("/api/review-requests")
async def api_review_requests():
    prs = await get_review_requests(settings.github_username, settings.gitlab_username)
    return JSONResponse(prs)


@app.get("/api/activity")
async def api_activity():
    activities = await get_recent_activities(limit=100)
    return JSONResponse(activities)


@app.get("/api/jira-tasks")
async def api_jira_tasks(role: str = "all", status: str = "all", sprint: str = "all"):
    tasks = await get_jira_tasks(role_filter=role, status_category=status, sprint=sprint)
    return JSONResponse(tasks)


@app.get("/api/jira-stats")
async def api_jira_stats():
    stats = await get_jira_stats()
    return JSONResponse(stats)


@app.get("/api/sprint-info")
async def api_sprint_info():
    sprints = await get_active_sprints()
    seen_sprint_ids: set[int] = set()
    result = []
    for s in sprints:
        sid = s["sprint_id"]
        if sid in seen_sprint_ids:
            continue
        seen_sprint_ids.add(sid)
        # Aggregate tasks across all projects sharing this sprint
        matching = [sp for sp in sprints if sp["sprint_id"] == sid]
        projects = [sp["project"] for sp in matching]
        boards = {sp["project"]: sp["board_id"] for sp in matching}
        merged_tasks = {"new": 0, "in_progress": 0, "in_review": 0, "done": 0, "total": 0}
        for proj in projects:
            t = await get_sprint_tasks(proj)
            for k in merged_tasks:
                merged_tasks[k] += t.get(k, 0)
        result.append(
            {
                **s,
                "projects": projects,
                "boards": boards,
                "my_tasks": merged_tasks,
            }
        )
    return JSONResponse(result)


@app.get("/api/yearly-completions")
async def api_yearly_completions():
    rows = await get_yearly_completions()
    return JSONResponse(rows)


@app.get("/api/calendar/today")
async def api_calendar_today():
    events = await get_today_events()
    return JSONResponse(events)


@app.get("/api/calendar/tomorrow")
async def api_calendar_tomorrow():
    events = await get_tomorrow_events()
    return JSONResponse(events)


@app.post("/api/refresh")
async def api_refresh():
    await poll_all()
    return JSONResponse({"status": "ok"})


@app.get("/api/stats")
async def api_stats():
    all_my_prs = await get_my_prs(settings.github_username, settings.gitlab_username, include_closed=True)
    assigned = await get_assigned_prs(settings.github_username, settings.gitlab_username)
    reviews = await get_review_requests(settings.github_username, settings.gitlab_username)
    jira = await get_jira_stats()

    open_count = sum(1 for p in all_my_prs if p["state"] in ("open", "draft"))
    merged_count = sum(1 for p in all_my_prs if p["state"] == "merged")
    draft_count = sum(1 for p in all_my_prs if p["is_draft"] and p["state"] == "draft")
    ci_failing = sum(1 for p in all_my_prs if p["ci_status"] == "failing" and p["state"] in ("open", "draft"))

    return JSONResponse(
        {
            "open_prs": open_count,
            "merged_prs": merged_count,
            "draft_prs": draft_count,
            "ci_failing": ci_failing,
            "assigned_prs": len(assigned),
            "pending_reviews": len(reviews),
            "jira_tasks": jira.get("total", 0),
            "jira_in_sprint": jira.get("in_sprint", 0),
        }
    )


@app.get("/api/review/providers")
async def api_review_providers():
    providers = await get_available_providers()
    return JSONResponse(providers)


@app.post("/api/review/prompt")
async def api_review_prompt(request: Request):
    """Return the full review prompt so the user can paste it into any LLM."""
    body = await request.json()
    pr_id = body.get("pr_id", "")
    if not pr_id:
        return JSONResponse({"error": "pr_id is required"}, status_code=400)
    try:
        diff_raw, metadata = await fetch_pr_diff(pr_id)
        diff_clean = sanitize_diff(diff_raw)
        system, user = build_review_prompt(metadata, diff_clean, pr_id=pr_id)
        full_prompt = f"{system}\n\n---\n\n{user}"
        return JSONResponse({"prompt": full_prompt, "metadata": metadata})
    except Exception as exc:
        logger.exception("Failed to generate review prompt for %s", pr_id)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/review")
async def api_review(request: Request):
    body = await request.json()
    pr_id = body.get("pr_id", "")
    provider = body.get("provider", "")
    if not pr_id or not provider:
        return JSONResponse({"error": "pr_id and provider are required"}, status_code=400)
    try:
        result = await review_pr(pr_id, provider)
        return JSONResponse(result)
    except Exception as exc:
        logger.exception("AI review failed for %s via %s", pr_id, provider)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/review/post")
async def api_review_post(request: Request):
    body = await request.json()
    pr_id = body.get("pr_id", "")
    comments = body.get("comments", [])
    if not pr_id or not comments:
        return JSONResponse({"error": "pr_id and comments are required"}, status_code=400)
    try:
        result = await post_review(pr_id, comments)
        return JSONResponse(result)
    except Exception as exc:
        logger.exception("Failed to post review for %s", pr_id)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# AI Readiness endpoints
# ---------------------------------------------------------------------------


@app.post("/api/readiness/scan")
async def api_readiness_scan(request: Request):
    """Scan a GitHub repo for AI/agentic readiness and return score."""
    import json

    from agentic_readiness.scanner import scan_repo
    from agentic_readiness.scorer import score_repo
    from database import insert_readiness_scan

    body = await request.json()
    repo_url = body.get("repo_url", "").strip()
    if not repo_url:
        return JSONResponse({"error": "repo_url is required"}, status_code=400)
    try:
        scan_result = await scan_repo(repo_url)
        score_result = score_repo(scan_result)

        await insert_readiness_scan({
            "repo_url": repo_url,
            "owner": scan_result["owner"],
            "repo": scan_result["repo"],
            "score_total": score_result["total"],
            "score_agent_config": score_result["categories"]["agent_config"]["score"],
            "score_documentation": score_result["categories"]["documentation"]["score"],
            "score_ci_quality": score_result["categories"]["ci_quality"]["score"],
            "score_code_structure": score_result["categories"]["code_structure"]["score"],
            "score_security": score_result["categories"]["security"]["score"],
            "score_fullsend": score_result["categories"].get("fullsend_readiness", {}).get("score", 0),
            "grade": score_result["grade"],
            "findings": json.dumps(score_result),
            "scanned_at": scan_result["scanned_at"],
        })

        return JSONResponse(
            {
                "scan": {
                    "full_name": scan_result["full_name"],
                    "description": scan_result["description"],
                    "primary_language": scan_result["primary_language"],
                    "languages": scan_result["languages"],
                    "default_branch": scan_result["default_branch"],
                    "visibility": scan_result["visibility"],
                    "has_ci": scan_result["has_ci"],
                    "ci_workflows": scan_result["ci_workflows"],
                },
                "score": score_result,
            }
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        logger.exception("Readiness scan failed for %s", repo_url)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/readiness/generate")
async def api_readiness_generate(request: Request):
    """Generate AI-ready files for a repo based on scan."""
    from agentic_readiness.generator import generate_files
    from agentic_readiness.scanner import scan_repo
    from agentic_readiness.scorer import score_repo

    body = await request.json()
    repo_url = body.get("repo_url", "").strip()
    if not repo_url:
        return JSONResponse({"error": "repo_url is required"}, status_code=400)
    try:
        scan_result = await scan_repo(repo_url)
        score_result = score_repo(scan_result)
        files = generate_files(scan_result, score_result)
        return JSONResponse({"files": files, "full_name": scan_result["full_name"]})
    except Exception as exc:
        logger.exception("File generation failed for %s", repo_url)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/readiness/create-pr")
async def api_readiness_create_pr(request: Request):
    """Create a draft PR with generated AI-readiness files."""
    from agentic_readiness.generator import create_draft_pr
    from agentic_readiness.scanner import parse_repo_url

    body = await request.json()
    repo_url = body.get("repo_url", "").strip()
    files = body.get("files", {})
    branch = body.get("branch", "add-ai-readiness-files")
    if not repo_url or not files:
        return JSONResponse({"error": "repo_url and files are required"}, status_code=400)
    try:
        owner, repo = parse_repo_url(repo_url)
        result = await create_draft_pr(owner, repo, files, branch_name=branch)
        if "error" in result:
            return JSONResponse(result, status_code=400)
        return JSONResponse(result)
    except Exception as exc:
        logger.exception("PR creation failed for %s", repo_url)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/readiness/history")
async def api_readiness_history():
    """Return recent scan history."""
    from database import get_readiness_history

    rows = await get_readiness_history()
    return JSONResponse(rows)


@app.get("/api/intelligence/stats")
async def api_intelligence_stats():
    from intelligence.db import get_ri_statistics

    stats = await get_ri_statistics()
    return JSONResponse(stats)


@app.get("/api/intelligence/patterns")
async def api_intelligence_patterns(category: str = "", repo: str = ""):
    from intelligence.db import get_patterns

    patterns = await get_patterns(category=category, repo=repo)
    return JSONResponse(patterns)


@app.get("/api/intelligence/reviewers")
async def api_intelligence_reviewers():
    from intelligence.db import get_all_reviewer_profiles

    profiles = await get_all_reviewer_profiles()
    return JSONResponse(profiles)


# ---------------------------------------------------------------------------
# Intelligence collection endpoints (background tasks)
# ---------------------------------------------------------------------------

_intel_tasks: dict[str, dict] = {}


async def _run_intel_collection(task_id: str, repo_slug: str):
    """Background coroutine for intelligence collection + analysis."""
    from intelligence.analyzer import generate_tool_insights, run_full_analysis
    from intelligence.collector import collect_repo

    task = _intel_tasks[task_id]
    try:
        task["stage"] = "collecting"
        task["message"] = f"Collecting PRs and reviews for {repo_slug}..."

        def progress_cb(repo, done, total, comments):
            task["prs_done"] = done
            task["prs_total"] = total
            task["comments"] = comments
            task["percent"] = round(done / max(total, 1) * 60)
            task["message"] = f"Collected {done}/{total} PRs, {comments} comments..."

        stats = await collect_repo(repo_slug, progress_callback=progress_cb)
        task["collect_stats"] = stats

        task["stage"] = "analyzing"
        task["percent"] = 65
        task["message"] = "Classifying comments and extracting patterns..."
        analysis = await run_full_analysis()
        task["analysis"] = analysis

        task["stage"] = "insights"
        task["percent"] = 85
        task["message"] = "Generating tool-specific insights..."
        insights = await generate_tool_insights(repo_slug)
        task["insights"] = insights

        task["stage"] = "done"
        task["percent"] = 100
        task["done"] = True
        task["message"] = "Collection and analysis complete"

    except Exception as exc:
        logger.exception("Intelligence collection failed for %s", repo_slug)
        task["stage"] = "error"
        task["error"] = str(exc)
        task["done"] = True


@app.post("/api/intelligence/collect")
async def api_intelligence_collect(request: Request):
    """Start background collection for any GitHub repo."""
    import uuid

    from intelligence.collector import parse_repo_url

    body = await request.json()
    repo_url = body.get("repo_url", "").strip()
    if not repo_url:
        return JSONResponse({"error": "repo_url is required"}, status_code=400)

    try:
        repo_slug = parse_repo_url(repo_url)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    task_id = str(uuid.uuid4())[:8]
    _intel_tasks[task_id] = {
        "task_id": task_id,
        "repo": repo_slug,
        "stage": "queued",
        "message": "Starting...",
        "percent": 0,
        "prs_done": 0,
        "prs_total": 0,
        "comments": 0,
        "done": False,
        "error": None,
    }

    asyncio.create_task(_run_intel_collection(task_id, repo_slug))
    return JSONResponse({"task_id": task_id, "repo": repo_slug})


@app.get("/api/intelligence/progress/{task_id}")
async def api_intelligence_progress(task_id: str):
    """Poll collection progress."""
    task = _intel_tasks.get(task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)
    return JSONResponse(task)


@app.get("/api/intelligence/repo/{owner}/{repo}")
async def api_intelligence_repo(owner: str, repo: str):
    """Return full intelligence data for a specific repo."""
    from intelligence.analyzer import generate_tool_insights
    from intelligence.db import get_repo_intelligence

    repo_slug = f"{owner}/{repo}"
    intel = await get_repo_intelligence(repo_slug)

    if intel.get("pr_count", 0) > 0:
        insights = await generate_tool_insights(repo_slug)
        intel["insights"] = insights

    return JSONResponse(intel)


@app.get("/api/intelligence/repos")
async def api_intelligence_repos():
    """Return list of repos with collection stats."""
    from intelligence.db import get_collected_repos

    repos = await get_collected_repos()
    return JSONResponse(repos)


# ---------------------------------------------------------------------------
# Agents Dashboard endpoints
# ---------------------------------------------------------------------------


@app.get("/api/agents")
async def api_agents():
    """Return all discovered agents with current status."""
    from agents.registry import get_all_agents

    return JSONResponse(get_all_agents())


@app.post("/api/agents/refresh")
async def api_agents_refresh():
    """Re-scan MCP config, check health, return updated list."""
    from agents.activity_stream import emit_event
    from agents.registry import refresh_registry

    emit_event("tool_start", "agent-registry", category="operation", data={"tool": "refresh_registry"})
    agents = await refresh_registry()
    running = sum(1 for a in agents if a.get("status") == "running")
    emit_event(
        "tool_end",
        "agent-registry",
        category="operation",
        data={
            "tool": "refresh_registry",
            "total": len(agents),
            "running": running,
        },
    )
    return JSONResponse(agents)


@app.post("/api/agents/register")
async def api_agents_register(request: Request):
    """Register an external A2A agent by base URL or agent card URL."""
    from agents.registry import fetch_a2a_agent_card, register_a2a_agent

    body = await request.json()
    url = body.get("url", "").strip()
    if not url:
        return JSONResponse({"error": "url is required"}, status_code=400)
    try:
        base = url.rstrip("/")
        if base.endswith("/.well-known/agent-card.json"):
            base = base[: -len("/.well-known/agent-card.json")].rstrip("/") or base
        card = await fetch_a2a_agent_card(base)
        if not card:
            return JSONResponse(
                {"error": f"Could not fetch agent card from {base}/.well-known/agent-card.json"}, status_code=400
            )
        agent = register_a2a_agent(base, card)
        return JSONResponse(agent)
    except Exception as exc:
        logger.exception("Failed to register A2A agent from %s", url)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.delete("/api/agents/{agent_id:path}")
async def api_agents_remove(agent_id: str):
    """Remove a manually registered A2A agent."""
    from agents.registry import remove_agent

    if remove_agent(agent_id):
        return JSONResponse({"status": "removed"})
    return JSONResponse({"error": "Agent not found or is an MCP server (cannot remove)"}, status_code=404)


@app.get("/api/agents/{agent_id:path}/history")
async def api_agent_history(agent_id: str):
    """Return status history for a specific agent."""
    from agents.registry import get_agent_status_history

    rows = get_agent_status_history(agent_id, limit=50)
    return JSONResponse(rows)


@app.get("/api/agents/telemetry/summary")
async def api_telemetry_summary():
    """Return aggregated telemetry data (token usage, costs, latency)."""
    from agents.telemetry import get_telemetry_summary

    return JSONResponse(get_telemetry_summary())


@app.get("/api/agents/activity/recent")
async def api_agents_activity_recent():
    """Return recent agent activity events."""
    from agents.activity_stream import get_recent_events

    return JSONResponse(get_recent_events(limit=50))


@app.get("/api/agents/activity/stream")
async def api_agents_activity_stream():
    """SSE endpoint for real-time agent activity (AOP-compatible)."""
    import json

    from agents.activity_stream import subscribe, unsubscribe

    queue = subscribe()

    async def event_generator():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import uvicorn

    def _handle_signal(signum, _frame):
        sig_name = signal.Signals(signum).name
        logger.info("Received %s — shutting down gracefully", sig_name)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    host = os.getenv("WORKSTREAM_HOST", "127.0.0.1")
    port = int(os.getenv("WORKSTREAM_PORT", "8080"))
    logger.info("Workstream PID %d starting on http://%s:%d", os.getpid(), host, port)
    uvicorn.run("app:app", host=host, port=port)
