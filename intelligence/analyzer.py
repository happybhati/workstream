"""Pattern analyzer for Review Intelligence.

Classifies review comments into categories, builds reviewer profiles,
and extracts recurring patterns from historical PR review data.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict

from intelligence.db import (
    batch_update_categories,
    clear_ri_patterns,
    get_unclassified_comments,
    upsert_reviewer_profile,
    upsert_ri_pattern,
)

logger = logging.getLogger("dashboard.intelligence.analyzer")

# ---------------------------------------------------------------------------
# Category keyword rules (applied in order; first match wins)
# ---------------------------------------------------------------------------

CATEGORY_RULES: list[tuple[str, re.Pattern]] = [
    (
        "bug",
        re.compile(
            r"(?i)\b(bug|incorrect|wrong|broken|crash|panic|nil\s*pointer|null\s*pointer"
            r"|nil\s+check|off.by.one|logic\s+error|typo\s+in\s+logic|data\s*loss"
            r"|infinite\s+loop|deadlock|segfault|undefined\s+behavior)\b"
        ),
    ),
    (
        "security",
        re.compile(
            r"(?i)\b(secur|vulnerab|inject|xss|csrf|auth[oz]|permission|privilege"
            r"|secret|credential|token\s+leak|sanitiz|escap|taint|CVE)\b"
        ),
    ),
    (
        "error_handling",
        re.compile(
            r"(?i)\b(error\s+handling|handle\s+error|unhandled|unchecked\s+(error|return)"
            r"|err\s*!=\s*nil|missing\s+error|swallow|ignore.*error|error\s+propagat"
            r"|wrap\s+error|return\s+err|fmt\.Errorf)\b"
        ),
    ),
    (
        "testing",
        re.compile(
            r"(?i)\b(test|coverage|assert|mock|fixture|unit\s*test|e2e|integration\s*test"
            r"|test\s*case|test\s*file|_test\.go|_test\.py|spec\.|describe\(|it\()\b"
        ),
    ),
    (
        "performance",
        re.compile(
            r"(?i)\b(perform|slow|latenc|efficien|optimi|allocat|memory\s+leak|O\(n"
            r"|complex|bottleneck|cache|pool|batch|concurrent|parallel|goroutine\s+leak)\b"
        ),
    ),
    (
        "concurrency",
        re.compile(
            r"(?i)\b(race\s+condition|mutex|lock|sync\.|atomic|channel|goroutine|thread"
            r"|concurrent|parallel|deadlock|wait\s*group|context\s+cancel)\b"
        ),
    ),
    (
        "api_design",
        re.compile(
            r"(?i)\b(api|endpoint|backward.compat|breaking\s+change|contract|interface"
            r"|signature|deprecat|versioning|schema\s+change|field\s+name|response\s+format)\b"
        ),
    ),
    (
        "documentation",
        re.compile(
            r"(?i)\b(doc|comment|readme|godoc|docstring|explain|clarif|description"
            r"|// |\/\*|TODO|FIXME|HACK|NOQA)\b"
        ),
    ),
    (
        "architecture",
        re.compile(
            r"(?i)\b(architect|design\s+pattern|separation|coupling|cohesion|abstraction"
            r"|refactor|restructur|modulari|dependency|layer|component|encapsulat"
            r"|single\s+responsibility)\b"
        ),
    ),
]

MIN_COMMENT_LENGTH = 15


def classify_comment(body: str) -> str:
    """Classify a single review comment body into a category via keyword matching."""
    if len(body.strip()) < MIN_COMMENT_LENGTH:
        return "other"

    for category, pattern in CATEGORY_RULES:
        if pattern.search(body):
            return category

    return "other"


async def classify_all_comments() -> dict:
    """Classify all unclassified comments using keyword rules.

    Returns stats on how many comments were classified into each category.
    """
    comments = await get_unclassified_comments(limit=10000)
    if not comments:
        logger.info("No unclassified comments found")
        return {"classified": 0}

    logger.info("Classifying %d comments", len(comments))

    updates: list[tuple[int, str]] = []
    category_counts: Counter = Counter()

    for c in comments:
        cat = classify_comment(c["body"])
        updates.append((c["id"], cat))
        category_counts[cat] += 1

    updated = await batch_update_categories(updates)
    logger.info("Classified %d comments: %s", updated, dict(category_counts))

    return {"classified": updated, "categories": dict(category_counts)}


# ---------------------------------------------------------------------------
# Reviewer profiling
# ---------------------------------------------------------------------------


def _extract_phrases(comments: list[dict], top_n: int = 10) -> list[str]:
    """Extract frequently occurring multi-word phrases from comment bodies."""
    phrase_counter: Counter = Counter()
    stop_words = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "shall",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "i",
        "you",
        "we",
        "they",
        "he",
        "she",
        "my",
        "your",
        "our",
        "their",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "up",
        "about",
        "into",
        "through",
        "during",
        "before",
        "after",
        "and",
        "but",
        "or",
        "nor",
        "not",
        "no",
        "so",
        "if",
        "then",
        "than",
        "too",
        "very",
        "just",
        "also",
        "as",
        "here",
        "there",
        "what",
        "which",
        "who",
        "whom",
        "how",
        "when",
        "where",
        "why",
    }

    for c in comments:
        words = re.findall(r"[a-z]+(?:\s+[a-z]+){1,3}", c["body"].lower())
        for phrase in words:
            tokens = phrase.split()
            if all(t in stop_words for t in tokens):
                continue
            if len(phrase) < 8:
                continue
            phrase_counter[phrase] += 1

    return [phrase for phrase, count in phrase_counter.most_common(top_n) if count >= 2]


async def build_reviewer_profiles() -> int:
    """Analyze all comments to build per-reviewer profiles.

    Returns the number of profiles created/updated.
    """
    from intelligence.db import _get_db

    db = await _get_db()
    try:
        cursor = await db.execute(
            """SELECT c.reviewer,
                      COUNT(DISTINCT c.pr_id) as pr_count,
                      COUNT(*) as comment_count,
                      c.category
               FROM ri_review_comments c
               WHERE c.reviewer != ''
               GROUP BY c.reviewer, c.category"""
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()

    reviewer_data: dict[str, dict] = defaultdict(
        lambda: {
            "total_prs": 0,
            "total_comments": 0,
            "categories": Counter(),
            "pr_ids": set(),
        }
    )

    for row in rows:
        r = row["reviewer"]
        reviewer_data[r]["total_comments"] += row["comment_count"]
        reviewer_data[r]["categories"][row["category"]] += row["comment_count"]

    db = await _get_db()
    try:
        cursor = await db.execute(
            """SELECT reviewer, COUNT(DISTINCT pr_id) as pr_count
               FROM ri_review_comments
               WHERE reviewer != ''
               GROUP BY reviewer"""
        )
        for row in await cursor.fetchall():
            reviewer_data[row["reviewer"]]["total_prs"] = row["pr_count"]
    finally:
        await db.close()

    profiles_count = 0
    for reviewer, data in reviewer_data.items():
        total_comments = data["total_comments"]
        total_prs = data["total_prs"]
        if total_comments < 2:
            continue

        top_cats = dict(data["categories"].most_common(10))

        db = await _get_db()
        try:
            cursor = await db.execute(
                "SELECT body FROM ri_review_comments WHERE reviewer = :r",
                {"r": reviewer},
            )
            all_comments = [dict(row) for row in await cursor.fetchall()]
        finally:
            await db.close()

        common_phrases = _extract_phrases(all_comments)

        top_3 = data["categories"].most_common(3)
        focus = [cat for cat, _ in top_3 if cat != "other"]

        avg_per_pr = total_comments / total_prs if total_prs > 0 else 0

        await upsert_reviewer_profile(
            {
                "reviewer": reviewer,
                "total_reviews": total_prs,
                "total_comments": total_comments,
                "top_categories": top_cats,
                "common_phrases": common_phrases,
                "avg_comments_per_pr": round(avg_per_pr, 2),
                "focus_areas": focus,
            }
        )
        profiles_count += 1

    logger.info("Built %d reviewer profiles", profiles_count)
    return profiles_count


# ---------------------------------------------------------------------------
# Pattern extraction
# ---------------------------------------------------------------------------


async def extract_patterns() -> int:
    """Extract recurring review patterns from classified comments.

    Groups similar comments by category and reviewer, then surfaces
    the most frequent themes as patterns.
    """
    from intelligence.db import _get_db

    await clear_ri_patterns()

    db = await _get_db()
    try:
        cursor = await db.execute(
            """SELECT c.category, c.reviewer, c.body, p.repo
               FROM ri_review_comments c
               JOIN ri_pull_requests p ON c.pr_id = p.id
               WHERE c.category != '' AND c.category != 'other'
               ORDER BY c.category, c.reviewer"""
        )
        rows = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    grouped: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for row in rows:
        key = (row["category"], row["reviewer"], row["repo"])
        grouped[key].append(row["body"])

    pattern_count = 0
    for (category, reviewer, repo), bodies in grouped.items():
        if len(bodies) < 2:
            continue

        best_example = max(bodies, key=lambda b: len(b) if len(b) < 500 else 0)
        if not best_example:
            best_example = bodies[0][:500]

        pattern_desc = _summarize_pattern(category, bodies)

        await upsert_ri_pattern(
            {
                "category": category,
                "pattern": pattern_desc,
                "example_comment": best_example[:1000],
                "frequency": len(bodies),
                "reviewer": reviewer,
                "repo": repo,
            }
        )
        pattern_count += 1

    logger.info("Extracted %d patterns", pattern_count)
    return pattern_count


def _summarize_pattern(category: str, bodies: list[str]) -> str:
    """Generate a human-readable pattern description from a group of comments."""
    count = len(bodies)
    avg_len = sum(len(b) for b in bodies) / count if count else 0

    key_words: Counter = Counter()
    for body in bodies:
        words = re.findall(r"\b[a-z]{4,}\b", body.lower())
        key_words.update(words)

    stop = {
        "this",
        "that",
        "with",
        "from",
        "have",
        "will",
        "should",
        "could",
        "would",
        "been",
        "being",
        "were",
        "also",
        "just",
        "like",
        "need",
        "needs",
        "here",
        "there",
        "think",
        "make",
        "more",
        "some",
        "when",
        "then",
        "than",
        "what",
        "which",
        "where",
        "does",
    }
    top = [w for w, _ in key_words.most_common(20) if w not in stop][:5]

    category_labels = {
        "bug": "correctness and logic issues",
        "error_handling": "error handling practices",
        "security": "security concerns",
        "testing": "test coverage and quality",
        "performance": "performance optimizations",
        "concurrency": "concurrency and thread safety",
        "api_design": "API design and compatibility",
        "documentation": "documentation quality",
        "architecture": "architectural decisions",
    }

    label = category_labels.get(category, category)
    return f"Reviewer feedback on {label} ({count} occurrences). Key themes: {', '.join(top)}"


# ---------------------------------------------------------------------------
# Full analysis pipeline
# ---------------------------------------------------------------------------


async def run_full_analysis() -> dict:
    """Run the complete analysis pipeline: classify -> profile -> extract.

    Returns combined statistics.
    """
    logger.info("Starting full review intelligence analysis")

    classify_result = await classify_all_comments()
    logger.info("Classification: %s", classify_result)

    profiles_count = await build_reviewer_profiles()
    logger.info("Built %d reviewer profiles", profiles_count)

    patterns_count = await extract_patterns()
    logger.info("Extracted %d patterns", patterns_count)

    return {
        "classification": classify_result,
        "profiles_built": profiles_count,
        "patterns_extracted": patterns_count,
    }


# ---------------------------------------------------------------------------
# Tool-specific insight generation
# ---------------------------------------------------------------------------


async def generate_tool_insights(repo: str) -> dict:
    """Convert collected patterns and profiles into tool-specific guidance.

    Returns a dict with keys for each tool:
    {
        "claude_md_rules": [str, ...],
        "cursor_rules": [str, ...],
        "copilot_review": [str, ...],
        "agents_md_conventions": [str, ...],
        "patterns": [dict, ...],
    }
    """
    from intelligence.db import get_repo_intelligence

    intel = await get_repo_intelligence(repo)
    patterns = intel.get("patterns", [])
    categories = intel.get("categories", {})

    conventions = []
    claude_rules = []
    cursor_rules = []
    copilot_review = []

    category_instructions = {
        "error_handling": {
            "convention": "Handle all errors explicitly; do not swallow or ignore errors",
            "claude": "Always check and propagate errors. Never use blank identifier for errors.",
            "cursor": "Verify all error returns are checked; no ignored errors",
            "copilot": "Flag any unchecked error returns or swallowed exceptions",
        },
        "testing": {
            "convention": "Write tests for all new functionality; maintain test coverage",
            "claude": "Write tests for every new function. Use table-driven tests where applicable.",
            "cursor": "New code must include corresponding test cases",
            "copilot": "Check that new code paths have test coverage",
        },
        "security": {
            "convention": "Never commit secrets; validate all inputs; use parameterized queries",
            "claude": "Never hardcode secrets. Sanitize all user inputs.",
            "cursor": "No hardcoded credentials; validate inputs at boundaries",
            "copilot": "Flag potential secret leaks, injection vulnerabilities, or missing input validation",
        },
        "bug": {
            "convention": "Verify edge cases: nil/null checks, boundary conditions, off-by-one",
            "claude": "Check for nil pointer dereferences and boundary conditions.",
            "cursor": "Verify nil/null checks and edge cases in conditional logic",
            "copilot": "Look for potential nil/null pointer issues and off-by-one errors",
        },
        "performance": {
            "convention": "Avoid unnecessary allocations; use batching for bulk operations",
            "claude": "Minimize allocations in hot paths. Prefer batch operations.",
            "cursor": "Watch for N+1 queries and unnecessary memory allocations",
            "copilot": "Flag potential performance issues like N+1 queries or excessive allocations",
        },
        "concurrency": {
            "convention": "Protect shared state with proper synchronization; use context for cancellation",
            "claude": "Use proper locking for shared state. Pass context for cancellation.",
            "cursor": "Verify goroutine/thread safety for shared data access",
            "copilot": "Check for race conditions and proper context propagation",
        },
        "api_design": {
            "convention": "Maintain backward compatibility; document API changes",
            "claude": "Do not break existing API contracts without explicit migration.",
            "cursor": "New API changes must be backward compatible unless explicitly approved",
            "copilot": "Flag breaking API changes or missing backward compatibility",
        },
        "architecture": {
            "convention": "Follow separation of concerns; keep modules focused",
            "claude": "Respect module boundaries. Don't cross architectural layers.",
            "cursor": "Maintain clear separation between layers and modules",
            "copilot": "Check that changes respect existing module boundaries",
        },
        "documentation": {
            "convention": "Document non-obvious behavior; update docs with code changes",
            "claude": "Add comments for non-obvious logic. Update docs when behavior changes.",
            "cursor": "Non-obvious logic must have explanatory comments",
            "copilot": "Check that complex logic has adequate documentation",
        },
    }

    sorted_cats = sorted(categories.items(), key=lambda x: -x[1])
    for cat, count in sorted_cats:
        if cat in category_instructions and count >= 3:
            instr = category_instructions[cat]
            conventions.append(instr["convention"])
            claude_rules.append(instr["claude"])
            cursor_rules.append(instr["cursor"])
            copilot_review.append(instr["copilot"])

    for p in patterns[:10]:
        cat = p.get("category", "")
        if cat in category_instructions:
            continue
        pattern_text = p.get("pattern", "")
        if pattern_text and len(pattern_text) > 20:
            short = pattern_text[:200]
            conventions.append(short)

    if not conventions:
        conventions = ["Follow existing code patterns in this repository"]
        claude_rules = ["Follow existing code patterns"]
        cursor_rules = ["Follow existing code patterns"]
        copilot_review = ["Verify code follows existing patterns"]

    return {
        "claude_md_rules": claude_rules[:10],
        "cursor_rules": cursor_rules[:10],
        "copilot_review": copilot_review[:10],
        "agents_md_conventions": conventions[:10],
        "patterns": patterns[:10],
    }
