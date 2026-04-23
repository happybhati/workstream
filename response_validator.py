"""LLM response validation and cleanup for code reviews.

Adapted from the response_validator pattern in
rh-ai-quickstart/ai-observability-summarizer by Twinkll Sisodia.

Ensures AI review output is well-formed JSON, strips preamble and
conversational filler, validates expected sections, and truncates
runaway responses.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger("dashboard.response_validator")

PREAMBLE_PATTERNS: list[re.Pattern] = [
    re.compile(r"^(?:Sure|Okay|Alright|Of course|Absolutely|Certainly)[,!.\s]", re.I),
    re.compile(r"^(?:Here(?:'s| is) (?:my |the |a )?(?:review|analysis|code review))", re.I),
    re.compile(r"^(?:I'(?:ll|ve) (?:review|analyz|look))", re.I),
    re.compile(r"^(?:Let me (?:review|analyze|look))", re.I),
    re.compile(r"^(?:After (?:reviewing|analyzing|looking))", re.I),
    re.compile(r"^(?:Based on (?:my|the) (?:review|analysis))", re.I),
]

POSTAMBLE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\n\s*(?:Note:|Please note|Hope this helps|Feel free|Let me know|Overall,?\s+(?:the|this))", re.I),
    re.compile(r"\n\s*(?:If you (?:have|need|want)|Don't hesitate|Happy to (?:help|answer))", re.I),
    re.compile(r"\n\s*(?:In summary|To summarize|In conclusion|To conclude)\s*[,:]?", re.I),
]

MAX_COMMENT_BODY_LENGTH = 2000
MAX_SUMMARY_LENGTH = 1000
MAX_COMMENTS = 50


def validate_review(raw_text: str) -> dict:
    """Validate and clean an AI review response.

    Returns a dict with:
      - cleaned:  the validated review dict (summary + comments)
      - raw:      original text
      - warnings: list of issues found during validation
    """
    warnings: list[str] = []

    text = _strip_preamble(raw_text)
    text = _strip_postamble(text)

    review = _extract_json_object(text)
    if review is None:
        warnings.append("Could not parse JSON from response; returning raw text as summary")
        return {
            "cleaned": {"summary": raw_text.strip()[:MAX_SUMMARY_LENGTH], "comments": []},
            "raw": raw_text,
            "warnings": warnings,
        }

    if "summary" not in review or not isinstance(review.get("summary"), str):
        review["summary"] = "Review completed."
        warnings.append("Missing or invalid 'summary' field")

    if len(review["summary"]) > MAX_SUMMARY_LENGTH:
        review["summary"] = review["summary"][:MAX_SUMMARY_LENGTH] + "..."
        warnings.append("Summary truncated to max length")

    comments = review.get("comments")
    if not isinstance(comments, list):
        review["comments"] = []
        warnings.append("Missing or invalid 'comments' array")
    else:
        validated = []
        for i, c in enumerate(comments):
            if not isinstance(c, dict):
                warnings.append(f"Comment {i} is not an object, skipped")
                continue
            vc = _validate_comment(c, i, warnings)
            if vc:
                validated.append(vc)
        if len(validated) > MAX_COMMENTS:
            validated = validated[:MAX_COMMENTS]
            warnings.append(f"Truncated to {MAX_COMMENTS} comments")
        review["comments"] = validated

    return {"cleaned": review, "raw": raw_text, "warnings": warnings}


def clean_review_text(text: str) -> str:
    """Quick cleanup without JSON parsing; returns plain text."""
    text = _strip_preamble(text)
    text = _strip_postamble(text)
    text = _normalize_whitespace(text)
    return text.strip()


def _strip_preamble(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        start = 1
        end = len(lines)
        for i, line in enumerate(lines[1:], 1):
            if line.strip().startswith("```"):
                end = i
                break
        text = "\n".join(lines[start:end]).strip()

    for pat in PREAMBLE_PATTERNS:
        m = pat.match(text)
        if m:
            after = text[m.end() :].lstrip(" ,.:;-\n")
            if after:
                text = after
                break
    return text


def _strip_postamble(text: str) -> str:
    for pat in POSTAMBLE_PATTERNS:
        m = pat.search(text)
        if m:
            candidate = text[: m.start()].rstrip()
            if len(candidate) > 50:
                text = candidate
                break
    return text


def _extract_json_object(text: str) -> dict | None:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    brace_start = text.find("{")
    brace_end = text.rfind("}") + 1
    if brace_start >= 0 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start:brace_end])
        except json.JSONDecodeError:
            pass

    return None


def _validate_comment(c: dict, idx: int, warnings: list[str]) -> dict | None:
    body = c.get("body", "")
    if not body or not isinstance(body, str):
        warnings.append(f"Comment {idx} has empty body, skipped")
        return None

    if len(body) > MAX_COMMENT_BODY_LENGTH:
        body = body[:MAX_COMMENT_BODY_LENGTH] + "..."
        warnings.append(f"Comment {idx} body truncated")

    severity = c.get("severity", "suggestion")
    if severity not in ("critical", "warning", "suggestion"):
        severity = "suggestion"

    return {
        "file": str(c.get("file", "")),
        "line": c.get("line"),
        "body": body,
        "severity": severity,
    }


def _normalize_whitespace(text: str) -> str:
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    lines = text.split("\n")
    return "\n".join(line.rstrip() for line in lines).strip()
