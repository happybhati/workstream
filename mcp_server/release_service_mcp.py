"""Release Service MCP Server.

Exposes release-service domain knowledge, review intelligence, and
team coding standards to AI agents in Cursor via the Model Context Protocol.

Run via: python -m mcp_server.release_service_mcp
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure the dashboard root is on sys.path so config/intelligence imports work
_dashboard_root = str(Path(__file__).resolve().parent.parent)
if _dashboard_root not in sys.path:
    sys.path.insert(0, _dashboard_root)

from mcp.server.fastmcp import FastMCP

from mcp_server.tools import (
    generate_contextual_review_prompt,
    get_recent_prs,
    get_repo_context,
    get_review_patterns,
    get_review_statistics,
    get_reviewer_profile,
    get_similar_reviews,
    get_team_standards,
    list_release_repos,
    search_past_reviews,
)

mcp = FastMCP(
    "release-service",
    instructions=(
        "Release Service MCP server for the Konflux CI release platform. "
        "Provides domain knowledge about release-service repositories, "
        "historical PR review intelligence, reviewer profiles, and team "
        "coding standards. Use these tools when reviewing code, understanding "
        "release-service architecture, or preparing pull requests."
    ),
)


# ---------------------------------------------------------------------------
# Domain Knowledge Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def tool_list_release_repos() -> str:
    """List all release-service repositories with their language, purpose, and key files.

    Use this to understand the release platform's repository landscape.
    """
    repos = list_release_repos()
    return json.dumps(repos, indent=2)


@mcp.tool()
def tool_get_repo_context(repo: str) -> str:
    """Get rich context for a specific release-service repository.

    Returns the repo's purpose, tech stack, review intelligence stats,
    top reviewers, category distribution, and recent PRs.

    Args:
        repo: Full repo name, e.g. "konflux-ci/release-service"
    """
    result = get_repo_context(repo)
    return json.dumps(result, indent=2)


@mcp.tool()
def tool_get_recent_prs(repo: str, state: str = "open", limit: int = 10) -> str:
    """Get recent pull requests for a release-service repository.

    Args:
        repo: Full repo name, e.g. "konflux-ci/release-service"
        state: Filter by state: "open", "merged", "closed", or "all"
        limit: Maximum number of PRs to return (default 10)
    """
    prs = get_recent_prs(repo, state, limit)
    return json.dumps(prs, indent=2)


# ---------------------------------------------------------------------------
# Review Intelligence Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def tool_get_review_patterns(repo: str = "", category: str = "") -> str:
    """Get recurring review patterns from historical PR data.

    Shows what reviewers consistently flag, with example comments.

    Args:
        repo: Optional repo filter, e.g. "konflux-ci/release-service"
        category: Optional category filter. Valid: bug, error_handling,
                  security, testing, performance, concurrency, api_design,
                  documentation, architecture
    """
    patterns = get_review_patterns(repo, category)
    return json.dumps(patterns, indent=2)


@mcp.tool()
def tool_get_reviewer_profile(reviewer: str) -> str:
    """Get a detailed profile of a specific code reviewer.

    Shows their focus areas, comment frequency, common phrases,
    and recent review examples.

    Args:
        reviewer: GitHub username of the reviewer
    """
    profile = get_reviewer_profile(reviewer)
    return json.dumps(profile, indent=2)


@mcp.tool()
def tool_search_past_reviews(query: str, repo: str = "") -> str:
    """Search through historical review comments by keyword.

    Useful for finding how the team has handled specific patterns before.

    Args:
        query: Search keyword or phrase
        repo: Optional repo filter
    """
    results = search_past_reviews(query, repo)
    return json.dumps(results, indent=2)


@mcp.tool()
def tool_get_team_standards() -> str:
    """Get aggregated team coding standards derived from review patterns.

    Returns the most common review themes, category distribution,
    and a summary of what the team prioritizes during code review.
    """
    standards = get_team_standards()
    return json.dumps(standards, indent=2)


@mcp.tool()
def tool_get_similar_reviews(file_path: str) -> str:
    """Find past review comments on files with similar paths or extensions.

    Use this before reviewing a file to see what reviewers have flagged
    on similar files in the past.

    Args:
        file_path: Path to the file being reviewed, e.g. "controllers/release_controller.go"
    """
    results = get_similar_reviews(file_path)
    return json.dumps(results, indent=2)


@mcp.tool()
def tool_generate_contextual_review_prompt(pr_id: str) -> str:
    """Generate a review prompt enriched with team context and past patterns.

    Returns repo-specific review patterns, reviewer expectations, and
    focus areas that can be injected into an AI review prompt.

    Args:
        pr_id: PR identifier in format "github:org/repo:number"
    """
    result = generate_contextual_review_prompt(pr_id)
    return json.dumps(result, indent=2)


@mcp.tool()
def tool_get_review_statistics() -> str:
    """Get overview statistics about collected review intelligence data.

    Shows total PRs analyzed, comment counts by category, reviewer count,
    and top contributors.
    """
    stats = get_review_statistics()
    return json.dumps(stats, indent=2)


# ---------------------------------------------------------------------------
# MCP Resources
# ---------------------------------------------------------------------------


@mcp.resource("release://repos")
def resource_repos() -> str:
    """Catalog of all release-service repositories."""
    repos = list_release_repos()
    return json.dumps(repos, indent=2)


@mcp.resource("release://standards")
def resource_standards() -> str:
    """Team coding standards derived from historical review analysis."""
    standards = get_team_standards()
    return json.dumps(standards, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
