#!/usr/bin/env python3
"""Create a professionally formatted Workstream Solution Architecture Google Doc."""

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

PROJECT_DIR = Path(__file__).resolve().parent.parent
CREDS_PATH = PROJECT_DIR / "google_credentials.json"
TOKEN_PATH = PROJECT_DIR / "google_token_docs.json"
SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
]

DARK_BLUE = {"red": 0.11, "green": 0.27, "blue": 0.53}
MEDIUM_BLUE = {"red": 0.20, "green": 0.40, "blue": 0.65}
DARK_GREY = {"red": 0.20, "green": 0.20, "blue": 0.20}
LIGHT_GREY_BG = {"red": 0.94, "green": 0.94, "blue": 0.94}
WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}
ACCENT_GREEN = {"red": 0.13, "green": 0.55, "blue": 0.13}


def _get_creds():
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json())
    if not creds or not creds.valid:
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
        creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())
    return creds


def _ins(text: str) -> dict:
    return {"insertText": {"location": {"index": 1}, "text": text}}


class DocBuilder:
    """Accumulates content bottom-up (insert at index 1) then applies styles."""

    def __init__(self, service, doc_id: str):
        self.svc = service
        self.doc_id = doc_id
        self._sections: list[dict] = []  # {text, style, bold, color, bg, font_size, ...}

    # ── helpers to queue content ──────────────────────────────────
    def title(self, text):
        self._sections.append({"text": text + "\n", "style": "TITLE"})
        return self

    def subtitle(self, text):
        self._sections.append({"text": text + "\n", "style": "SUBTITLE"})
        return self

    def h1(self, text):
        self._sections.append({"text": text + "\n", "style": "HEADING_1"})
        return self

    def h2(self, text):
        self._sections.append({"text": text + "\n", "style": "HEADING_2"})
        return self

    def h3(self, text):
        self._sections.append({"text": text + "\n", "style": "HEADING_3"})
        return self

    def body(self, text):
        self._sections.append({"text": text + "\n", "style": "NORMAL_TEXT"})
        return self

    def bold_body(self, text):
        self._sections.append({"text": text + "\n", "style": "NORMAL_TEXT", "bold": True})
        return self

    def bullet(self, text):
        self._sections.append({"text": text + "\n", "style": "NORMAL_TEXT", "bullet": True})
        return self

    def spacer(self):
        self._sections.append({"text": "\n", "style": "NORMAL_TEXT"})
        return self

    def hr(self):
        self._sections.append({"text": "━" * 60 + "\n", "style": "NORMAL_TEXT", "color": MEDIUM_BLUE})
        return self

    def code_block(self, text):
        self._sections.append(
            {
                "text": text + "\n",
                "style": "NORMAL_TEXT",
                "font": "Roboto Mono",
                "font_size": 9,
                "bg": LIGHT_GREY_BG,
            }
        )
        return self

    def table_row(self, cells: list[str], header: bool = False):
        self._sections.append(
            {
                "text": "  |  ".join(cells) + "\n",
                "style": "NORMAL_TEXT",
                "font": "Roboto Mono" if not header else None,
                "font_size": 10,
                "bold": header,
                "bg": DARK_BLUE if header else None,
                "color": WHITE if header else DARK_GREY,
            }
        )
        return self

    # ── flush everything to the API ───────────────────────────────
    def build(self):
        full_text = "".join(s["text"] for s in self._sections)
        requests = [{"insertText": {"location": {"index": 1}, "text": full_text}}]

        idx = 1
        for sec in self._sections:
            length = len(sec["text"])
            end = idx + length

            para_end = end - 1 if sec["text"].endswith("\n") else end
            if para_end < idx:
                para_end = idx

            named = sec["style"]
            requests.append(
                {
                    "updateParagraphStyle": {
                        "range": {"startIndex": idx, "endIndex": para_end},
                        "paragraphStyle": {"namedStyleType": named},
                        "fields": "namedStyleType",
                    }
                }
            )

            if sec.get("bullet"):
                requests.append(
                    {
                        "createParagraphBullets": {
                            "range": {"startIndex": idx, "endIndex": para_end},
                            "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                        }
                    }
                )

            text_style: dict = {}
            fields = []

            if sec.get("bold"):
                text_style["bold"] = True
                fields.append("bold")
            if sec.get("color"):
                text_style["foregroundColor"] = {"color": {"rgbColor": sec["color"]}}
                fields.append("foregroundColor")
            if sec.get("bg"):
                text_style["backgroundColor"] = {"color": {"rgbColor": sec["bg"]}}
                fields.append("backgroundColor")
            if sec.get("font"):
                text_style["weightedFontFamily"] = {"fontFamily": sec["font"]}
                fields.append("weightedFontFamily")
            if sec.get("font_size"):
                text_style["fontSize"] = {"magnitude": sec["font_size"], "unit": "PT"}
                fields.append("fontSize")

            if fields:
                requests.append(
                    {
                        "updateTextStyle": {
                            "range": {"startIndex": idx, "endIndex": end - 1},
                            "textStyle": text_style,
                            "fields": ",".join(fields),
                        }
                    }
                )

            idx = end

        # Update heading styles globally for corporate look
        requests.append(
            {
                "updateDocumentStyle": {
                    "documentStyle": {
                        "marginTop": {"magnitude": 36, "unit": "PT"},
                        "marginBottom": {"magnitude": 36, "unit": "PT"},
                        "marginLeft": {"magnitude": 54, "unit": "PT"},
                        "marginRight": {"magnitude": 54, "unit": "PT"},
                    },
                    "fields": "marginTop,marginBottom,marginLeft,marginRight",
                }
            }
        )

        self.svc.documents().batchUpdate(
            documentId=self.doc_id,
            body={"requests": requests},
        ).execute()

        print(f"Document formatted: https://docs.google.com/document/d/{self.doc_id}/edit")


def populate(b: DocBuilder):
    b.title("Workstream — Solution Architecture Document")
    b.subtitle("A Local-First AI-Powered Developer Command Center  |  Version 1.0  |  April 2026")
    b.spacer()

    # ── 1 ──
    b.h1("1. Executive Summary")
    b.body(
        "Workstream is an open-source, local-first developer command center that unifies "
        "pull requests, code reviews, Jira tasks, sprint tracking, calendar events, "
        "AI-powered code review, repository AI-readiness scanning, agent management, "
        "and cost analytics into a single dashboard running at localhost:8080."
    )
    b.spacer()
    b.body(
        "It solves the core problem modern developers face: context-switching across "
        "5+ tools (GitHub, GitLab, Jira, Google Calendar, AI assistants) that fragments "
        "attention and causes missed reviews, overlooked CI failures, and lost situational awareness."
    )
    b.spacer()
    b.bold_body("Key Design Principles")
    b.bullet("Local-first — all data stays on your machine; no cloud dependency")
    b.bullet("Privacy-preserving — no telemetry sent externally; SQLite database on disk")
    b.bullet("Zero infrastructure cost — runs as a macOS LaunchAgent; no containers needed")
    b.bullet("AI-native — built with and for AI-assisted development workflows")
    b.bullet("Extensible — modular Python backend, vanilla JS frontend, open API surface")
    b.spacer()

    # ── 2 ──
    b.h1("2. Problem Statement")
    b.body("Developers on distributed platform teams face six key challenges:")
    b.spacer()
    b.bold_body("2.1 Tool Sprawl")
    b.body(
        "PRs on GitHub and GitLab, tasks on Jira, meetings on Google Calendar, CI on "
        "GitHub Actions, AI tools in separate windows — no unified view exists."
    )
    b.bold_body("2.2 AI Opacity")
    b.body(
        "AI coding assistants (Cursor, Claude, Copilot, ChatGPT) consume tokens and cost money, "
        "but there is no dashboard tracking spend across tools."
    )
    b.bold_body("2.3 Repository Readiness Gap")
    b.body(
        "As AI agents become part of the SDLC (triage, code, review), repositories need "
        "specific configuration files (AGENTS.md, CLAUDE.md, skills, backpressure mechanisms). "
        "Teams lack tooling to assess and generate them."
    )
    b.bold_body("2.4 Review Fatigue")
    b.body(
        "Developers assigned 15-20 PRs miss changes pushed after their review, with no "
        'mechanism to surface "what changed since I last looked."'
    )
    b.bold_body("2.5 Silent Service Failures")
    b.body(
        "When GitHub Search degrades or Jira goes down, developers don't know why their "
        "dashboard is empty — failures are invisible."
    )
    b.bold_body("2.6 Stale Context")
    b.body(
        "Sprint progress, yearly trends, and upcoming meetings require visiting multiple tools "
        'to assemble a mental model of "where do I stand?"'
    )
    b.spacer()

    # ── 3 ──
    b.h1("3. High-Level Architecture")
    b.spacer()
    b.code_block(
        "┌─────────────────────────────────────────────────────────┐\n"
        "│            PRESENTATION LAYER                          │\n"
        "│  Single-Page App  (Vanilla JS + CSS)                   │\n"
        "│  Tabs: PRs | Readiness | AI Costs | Agents             │\n"
        "│  Sidebar: Calendar · Sprint · Stats · Service Status   │\n"
        "└──────────────────────────┬──────────────────────────────┘\n"
        "                           │  HTTP / REST\n"
        "┌──────────────────────────┴──────────────────────────────┐\n"
        "│            APPLICATION LAYER  (FastAPI)                 │\n"
        "│  app.py  ·  22+ REST endpoints  ·  Auth middleware      │\n"
        "│  Lifespan: start/stop pollers                           │\n"
        "├─────────────────────────────────────────────────────────┤\n"
        "│  reviewer.py  ·  pollers.py  ·  database.py             │\n"
        "│  reports.py  ·  model_registry.py  ·  response_validator│\n"
        "│  claude_code_importer.py                                │\n"
        "└──────────────────────────┬──────────────────────────────┘\n"
        "                           │\n"
        "┌──────────────────────────┴──────────────────────────────┐\n"
        "│            DATA LAYER  (SQLite + aiosqlite)             │\n"
        "│  pull_requests · jira_issues · calendar_events          │\n"
        "│  readiness_scans · ai_telemetry · model_pricing         │\n"
        "└──────────────────────────┬──────────────────────────────┘\n"
        "                           │\n"
        "┌──────────────────────────┴──────────────────────────────┐\n"
        "│            INTELLIGENCE LAYER                           │\n"
        "│  agentic_readiness/  (scanner · scorer · generator)     │\n"
        "│  intelligence/analyzer.py  ·  agents/ (registry+telem)  │\n"
        "└──────────────────────────┬──────────────────────────────┘\n"
        "                           │\n"
        "┌──────────────────────────┴──────────────────────────────┐\n"
        "│            EXTERNAL INTEGRATIONS                        │\n"
        "│  GitHub API · GitLab API · Jira Cloud · Google Calendar │\n"
        "│  Statuspage.io (GitHub/Atlassian) · OpenAI / Anthropic  │\n"
        "└─────────────────────────────────────────────────────────┘"
    )
    b.spacer()

    # ── 4 ──
    b.h1("4. Component Details")
    b.spacer()

    # 4.1
    b.h2("4.1 Presentation Layer — static/index.html")
    b.table_row(["Property", "Value"], header=True)
    b.table_row(["Technology", "Single HTML file, Vanilla JS, CSS custom properties"])
    b.table_row(["Build Step", "None — zero npm dependencies"])
    b.table_row(["Theme", "Dark theme with CSS variables"])
    b.table_row(["Auto-refresh", "Every 5 minutes"])
    b.spacer()
    b.bold_body("UI Structure")
    b.bullet("Header: Logo + Service Status Dot (green/yellow/red) + Last Updated timestamp")
    b.bullet("Left Sidebar: Today's Calendar, Tomorrow's Calendar, Sprint Progress bar, Stats cards")
    b.bullet(
        'Main Area — Tab: Pull Requests (My PRs with CI badges, Review Requests with "since-review" badges, Assigned PRs)'
    )
    b.bullet("Main Area — Tab: AI Readiness (Scan form, category radar, scan history with per-row delete)")
    b.bullet(
        "Main Area — Tab: AI Costs (Usage charts via Chart.js, cost breakdown table, manual entry, report generation)"
    )
    b.bullet("Main Area — Tab: Agents (Registered agents list, health checks, A2A protocol support)")
    b.bullet("Collapsible Service Status Banner with component-level health details")
    b.bullet("One-click review prompt generation — copies rich context prompt to clipboard")
    b.spacer()

    # 4.2
    b.h2("4.2 Application Layer — app.py")
    b.table_row(["Property", "Value"], header=True)
    b.table_row(["Framework", "FastAPI (Python 3.11+)"])
    b.table_row(["Server", "Uvicorn (single-worker, async)"])
    b.table_row(["Port", "8080 (configurable)"])
    b.table_row(["Auth", "PAT-based middleware (X-Auth-Token header)"])
    b.spacer()
    b.bold_body("Lifespan Management")
    b.bullet("On startup: initialize database schema + migrations, start background polling loop")
    b.bullet("On shutdown: gracefully stop pollers, close database connections")
    b.spacer()
    b.bold_body("API Endpoints (22+)")
    b.spacer()
    b.h3("Pull Requests")
    b.code_block(
        "GET  /api/my-prs           → PRs authored by the user\n"
        "GET  /api/reviews           → PRs where user's review is requested\n"
        "GET  /api/assigned          → PRs assigned to the user\n"
        "GET  /api/stats             → Dashboard statistics\n"
        "POST /api/refresh           → Trigger manual poll cycle"
    )
    b.h3("Code Review")
    b.code_block(
        "POST /api/review/prompt     → Generate AI review prompt (URL-based, no raw diff)\n"
        "POST /api/review/run        → Execute AI-powered review internally"
    )
    b.h3("AI Readiness")
    b.code_block(
        "POST /api/readiness/scan    → Scan a repository for agent readiness\n"
        "POST /api/readiness/generate→ Generate missing agent-ready files\n"
        "GET  /api/readiness/history  → Past scan results\n"
        "DELETE /api/readiness/history/{id} → Delete a scan result\n"
        "POST /api/readiness/history/delete-bulk → Bulk delete"
    )
    b.h3("AI Costs & Telemetry")
    b.code_block(
        "GET  /api/ai/costs          → Cost summary for period (7d/30d/90d)\n"
        "POST /api/ai/event          → Record a telemetry event\n"
        "GET  /api/ai/models         → List model pricing\n"
        "POST /api/ai/import-claude  → Import Claude Code sessions\n"
        "POST /api/ai/report         → Generate cost report"
    )
    b.h3("Agents")
    b.code_block(
        "GET  /api/agents            → List registered agents\n"
        "POST /api/agents/register   → Register a new agent\n"
        "GET  /api/agents/{id}/health→ Agent health check"
    )
    b.h3("Calendar, Jira & System")
    b.code_block(
        "GET  /api/calendar/today    → Today's events\n"
        "GET  /api/calendar/tomorrow → Tomorrow's events\n"
        "GET  /api/jira/sprint       → Active sprint progress\n"
        "GET  /api/health            → Health check\n"
        "GET  /api/service-status    → Dependency service health"
    )
    b.spacer()

    # 4.3
    b.h2("4.3 Data Layer — database.py + SQLite")
    b.table_row(["Property", "Value"], header=True)
    b.table_row(["Engine", "SQLite via aiosqlite (async, WAL mode)"])
    b.table_row(["File", "data.db in project root"])
    b.table_row(["Migration", "Auto-applied on startup (ALTER TABLE IF NOT EXISTS)"])
    b.spacer()
    b.bold_body("Database Schema")
    b.spacer()
    b.h3("Table: pull_requests")
    b.code_block(
        "id INTEGER PRIMARY KEY\n"
        "platform TEXT              -- 'github' | 'gitlab'\n"
        "repo TEXT                  -- 'org/repo'\n"
        "number INTEGER\n"
        "title TEXT\n"
        "author TEXT\n"
        "state TEXT                 -- 'open' | 'draft' | 'merged' | 'closed'\n"
        "ci_status TEXT             -- 'success' | 'failure' | 'pending' | ''\n"
        "url TEXT\n"
        "assigned_to TEXT\n"
        "review_requested_from TEXT\n"
        "labels TEXT                -- JSON array\n"
        "updated_at TEXT\n"
        "polled_at TEXT\n"
        "my_last_review_at TEXT     -- Timestamp of user's last review\n"
        "commits_since_review INT   -- Commits pushed after last review\n"
        "comments_since_review INT  -- Comments added after last review"
    )
    b.h3("Table: jira_issues")
    b.code_block(
        "id INTEGER PRIMARY KEY\n"
        "key TEXT UNIQUE, summary TEXT, status TEXT\n"
        "assignee TEXT, sprint TEXT, story_points REAL, updated_at TEXT"
    )
    b.h3("Table: calendar_events")
    b.code_block(
        "id INTEGER PRIMARY KEY\n"
        "event_id TEXT UNIQUE, title TEXT, start_time TEXT\n"
        "end_time TEXT, event_date TEXT, location TEXT, polled_at TEXT"
    )
    b.h3("Table: readiness_scans")
    b.code_block(
        "id INTEGER PRIMARY KEY\n"
        "repo TEXT, score INT, score_docs INT, score_ci INT\n"
        "score_testing INT, score_structure INT, score_fullsend INT\n"
        "details TEXT (JSON), scanned_at TEXT"
    )
    b.h3("Table: ai_telemetry")
    b.code_block(
        "id INTEGER PRIMARY KEY\n"
        "timestamp TEXT, tool TEXT, model TEXT\n"
        "input_tokens INT, output_tokens INT, cost_usd REAL\n"
        "latency_ms INT, operation TEXT, metadata TEXT (JSON)"
    )
    b.h3("Table: model_pricing")
    b.code_block(
        "model TEXT PRIMARY KEY\ninput_cost_per_1k REAL, output_cost_per_1k REAL\nprovider TEXT, updated_at TEXT"
    )
    b.spacer()

    # 4.4
    b.h2("4.4 Polling Engine — pollers.py")
    b.body(
        "A background async loop runs every 5 minutes (configurable) and polls all "
        "external data sources. Each poller is wrapped in a try/except to ensure "
        "one failure does not block others."
    )
    b.spacer()
    b.bold_body("Pollers")
    b.table_row(["Poller", "Source", "Data Written"], header=True)
    b.table_row(["poll_github_prs", "GitHub Search API", "pull_requests (authored, review-requested, assigned)"])
    b.table_row(["poll_github_pr_events", "GitHub PR Reviews API", "my_last_review_at, commits/comments since"])
    b.table_row(["poll_gitlab_mrs", "GitLab MRs API", "pull_requests (merge requests)"])
    b.table_row(["poll_jira_sprint", "Jira Agile API", "jira_issues (active sprint)"])
    b.table_row(["poll_google_calendar", "Google Calendar API", "calendar_events (today + tomorrow)"])
    b.table_row(["poll_service_status", "Statuspage.io + GitLab", "In-memory service health cache"])
    b.table_row(["cleanup_stale_prs", "Local DB", "Marks un-refreshed PRs as closed"])
    b.spacer()
    b.bold_body('"Changes Since Last Review" Tracking')
    b.body(
        "After fetching PRs, the poller calls the GitHub Reviews API to find the user's "
        "most recent review timestamp on each PR. It then counts commits pushed and "
        "non-self comments posted after that timestamp. This data powers the "
        '"since-review" badge on the dashboard — e.g., "3 commits, 2 comments since your review."'
    )
    b.spacer()

    # 4.5
    b.h2("4.5 Code Review Engine — reviewer.py")
    b.body("Generates context-rich prompts for AI-assisted code review. Two modes:")
    b.spacer()
    b.bold_body("Internal Review (build_review_prompt)")
    b.bullet("Fetches full diff from GitHub/GitLab API")
    b.bullet("Includes PR metadata (title, author, branch, labels, stats)")
    b.bullet("Includes team review context (historical patterns, recurring themes)")
    b.bullet("Sends to configured LLM (OpenAI, Anthropic, Ollama)")
    b.bullet("Validates response via response_validator.py")
    b.spacer()
    b.bold_body("External / Clipboard Review (build_copy_prompt)")
    b.bullet("URL-based — no raw diff included (AI tool fetches diff itself)")
    b.bullet("Rich PR metadata and team context included")
    b.bullet("Optimized for pasting into Cursor, Claude, or ChatGPT")
    b.spacer()

    # 4.6
    b.h2("4.6 AI Readiness Scanner — agentic_readiness/")
    b.body(
        "Evaluates a GitHub repository's readiness for AI agent workflows across "
        "five categories, totaling 150 raw points normalized to 0-100."
    )
    b.spacer()
    b.bold_body("Components")
    b.spacer()
    b.h3("scanner.py — Data Collection")
    b.bullet("Fetches repo metadata, file tree, languages, CI workflows, README, key files")
    b.bullet("Key files checked: AGENTS.md, CLAUDE.md, CONTRIBUTING.md, CODEOWNERS, Makefile, BOOKMARKS.md")
    b.bullet("Extracts CI commands from GitHub Actions YAML")
    b.bullet("Extracts Makefile targets")
    b.spacer()
    b.h3("scorer.py — Scoring Engine")
    b.table_row(["Category", "Max Points", "Evaluates"], header=True)
    b.table_row(["Documentation", "30", "README quality, CONTRIBUTING, AGENTS.md presence & depth"])
    b.table_row(["CI Quality", "30", "Workflow count, linters, type checkers, formatters"])
    b.table_row(["Testing", "30", "Test directory, test commands, coverage config"])
    b.table_row(["Structure", "30", "Directory layout, .gitignore, Makefile, issue templates"])
    b.table_row(["Fullsend Readiness", "30", "Skills, backpressure, CLAUDE.md, BOOKMARKS.md, CODEOWNERS"])
    b.spacer()
    b.h3("generator.py — File Generation")
    b.bullet("Auto-generates AGENTS.md, CLAUDE.md, BOOKMARKS.md, skills (SKILL.md)")
    b.bullet('Skills are CSO-optimized (descriptions start with "Use when...")')
    b.bullet("Enriched with CI commands and Makefile targets")
    b.bullet("Can generate PRs with generated files to target repositories")
    b.spacer()

    # 4.7
    b.h2("4.7 AI Cost Analytics")
    b.body("Tracks token usage, latency, and estimated cost across all AI interactions.")
    b.spacer()
    b.bold_body("Components")
    b.bullet("model_registry.py / model_registry.json — Pricing for 24+ models (GPT-4o, Claude 3.5, Llama 3, etc.)")
    b.bullet("claude_code_importer.py — Discovers and imports Claude Code sessions into telemetry")
    b.bullet("agents/telemetry.py — Records events from registered agents, mirrors to ai_telemetry table")
    b.bullet("reports.py — Generates weekly digests, cost reports, and review summaries (Markdown + HTML)")
    b.spacer()
    b.bold_body("Dashboard Features")
    b.bullet("Time-series cost chart (Chart.js)")
    b.bullet("Breakdown by tool, model, and operation")
    b.bullet("Manual event entry for tools without API integration")
    b.bullet("One-click report generation (weekly digest, cost report, review summary)")
    b.spacer()

    # 4.8
    b.h2("4.8 Service Dependency Status Tracker")
    b.body(
        "Monitors the health of external services Workstream depends on, "
        "preventing confusion when third-party outages cause empty dashboards."
    )
    b.spacer()
    b.bold_body("Monitored Services")
    b.table_row(["Service", "Method", "Components Tracked"], header=True)
    b.table_row(["GitHub", "Statuspage.io API", "Pull Requests, Actions, API Requests, Issues, Git Operations"])
    b.table_row(["Atlassian (Jira)", "Statuspage.io API", "Jira, Jira Service Management"])
    b.table_row(["GitLab", "Authenticated API call", "API availability (with self-signed cert support)"])
    b.spacer()
    b.bold_body("UI Behavior")
    b.bullet("Green dot in header: all services operational")
    b.bullet("Yellow dot: degraded performance on one or more services")
    b.bullet("Red dot: partial or major outage detected")
    b.bullet("Click dot to expand banner with per-component details and active incidents")
    b.spacer()

    # ── 5 ──
    b.h1("5. Data Flow Diagrams")
    b.spacer()

    b.h2("5.1 Background Polling Flow")
    b.code_block(
        "Every 5 min\n"
        "    │\n"
        "    ├── poll_github_prs() ──→ GitHub Search API ──→ upsert pull_requests\n"
        "    │       └── poll_github_pr_events() ──→ Reviews API ──→ update since-review\n"
        "    ├── poll_gitlab_mrs() ──→ GitLab MRs API ──→ upsert pull_requests\n"
        "    ├── poll_jira_sprint() ──→ Jira Agile API ──→ upsert jira_issues\n"
        "    ├── poll_google_calendar() ──→ Calendar API ──→ upsert calendar_events\n"
        "    ├── poll_service_status() ──→ Statuspage/GitLab ──→ in-memory cache\n"
        "    └── cleanup_stale_prs() ──→ mark un-refreshed PRs as closed"
    )
    b.spacer()

    b.h2("5.2 AI Readiness Scan Flow")
    b.code_block(
        "User submits repo URL\n"
        "    │\n"
        "    ├── scanner.scan_repo() ──→ GitHub API\n"
        "    │       ├── fetch metadata, tree, languages\n"
        "    │       ├── fetch CI workflow YAML files\n"
        "    │       ├── fetch key files (AGENTS.md, Makefile, etc.)\n"
        "    │       └── return scan_result dict\n"
        "    │\n"
        "    ├── scorer.score_repo(scan_result)\n"
        "    │       ├── score 5 categories (0-30 each)\n"
        "    │       ├── normalize to 0-100\n"
        "    │       ├── build recommendations list\n"
        "    │       └── return score + breakdown\n"
        "    │\n"
        "    └── database.insert_readiness_scan()\n"
        "            └── persist for history"
    )
    b.spacer()

    b.h2("5.3 Code Review Prompt Flow")
    b.code_block(
        'User clicks "Generate Review Prompt"\n'
        "    │\n"
        "    ├── reviewer.build_copy_prompt(pr_url)\n"
        "    │       ├── fetch PR metadata (title, author, labels, stats)\n"
        "    │       ├── fetch team review context (historical patterns)\n"
        "    │       ├── compose prompt (NO raw diff — URL-based)\n"
        "    │       └── return prompt string\n"
        "    │\n"
        "    └── Copied to clipboard → Paste into AI assistant"
    )
    b.spacer()

    # ── 6 ──
    b.h1("6. Deployment Architecture")
    b.spacer()
    b.h2("6.1 Local Development / Production")
    b.code_block(
        "┌───────────────────────────────────────────────────┐\n"
        "│                macOS Host Machine                 │\n"
        "│                                                   │\n"
        "│  LaunchAgent (com.workstream.dashboard)           │\n"
        "│      │                                            │\n"
        "│      └── uvicorn app:app --host 0.0.0.0 --port 8080│\n"
        "│              │                                    │\n"
        "│              ├── FastAPI (app.py)                  │\n"
        "│              ├── SQLite (data.db)                  │\n"
        "│              └── Static files (static/)           │\n"
        "│                                                   │\n"
        "│  Browser → http://localhost:8080                   │\n"
        "└───────────────────────────────────────────────────┘"
    )
    b.spacer()
    b.bold_body("Installation")
    b.code_block(
        "git clone https://github.com/happybhati/workstream\n"
        "cd workstream\n"
        "pip install -r requirements.txt\n"
        "cp .env.example .env   # configure PATs, API keys\n"
        "bash install.sh        # installs macOS LaunchAgent"
    )
    b.spacer()
    b.bold_body("The install.sh script:")
    b.bullet("Resolves the project directory path dynamically")
    b.bullet("Substitutes __DASHBOARD_DIR__ placeholder in the plist template")
    b.bullet("Installs plist to ~/Library/LaunchAgents/")
    b.bullet("Bootstraps the service via launchctl")
    b.spacer()

    b.h2("6.2 Container Deployment")
    b.body(
        "Workstream includes a Dockerfile and CI pipeline for container builds. "
        "The a2a_servers module import is wrapped in try/except for container compatibility."
    )
    b.spacer()

    # ── 7 ──
    b.h1("7. Security Architecture")
    b.spacer()
    b.bold_body("Authentication")
    b.bullet("All API endpoints (except /api/health and /api/service-status) require X-Auth-Token header")
    b.bullet("Token validated against DASHBOARD_AUTH_TOKEN environment variable")
    b.bullet("Static files served without authentication")
    b.spacer()
    b.bold_body("Secrets Management")
    b.bullet("All secrets stored in .env file (gitignored)")
    b.bullet("GITHUB_PAT — GitHub personal access token (repo, read:org scopes)")
    b.bullet("GITLAB_PAT — GitLab personal access token")
    b.bullet("JIRA_TOKEN — Jira API token (email:token base64)")
    b.bullet("GOOGLE_CREDENTIALS_PATH / GOOGLE_TOKEN_PATH — OAuth2 credentials for Calendar")
    b.bullet("DASHBOARD_AUTH_TOKEN — Dashboard access token")
    b.spacer()
    b.bold_body("Network Security")
    b.bullet("Runs on localhost only by default — not exposed to network")
    b.bullet("GitLab integration supports self-signed SSL certificates (verify=False with dedicated client)")
    b.bullet("All external API calls use HTTPS")
    b.spacer()
    b.bold_body("Data Privacy")
    b.bullet("All data stored locally in SQLite — never leaves the machine")
    b.bullet("No analytics, no telemetry sent to third parties")
    b.bullet("User controls what repositories, calendars, and Jira boards are tracked")
    b.spacer()

    # ── 8 ──
    b.h1("8. Configuration")
    b.spacer()
    b.bold_body("config.py — Settings class with environment variable overrides")
    b.spacer()
    b.table_row(["Variable", "Default", "Purpose"], header=True)
    b.table_row(["GITHUB_PAT", "(required)", "GitHub API authentication"])
    b.table_row(["GITHUB_USERNAME", "(required)", "Identify user's PRs"])
    b.table_row(["GITLAB_PAT", "(optional)", "GitLab API authentication"])
    b.table_row(["GITLAB_USERNAME", "(optional)", "GitLab MR filtering"])
    b.table_row(["GITLAB_URL", "https://gitlab.com", "Self-hosted GitLab support"])
    b.table_row(["JIRA_URL", "(optional)", "Jira instance base URL"])
    b.table_row(["JIRA_TOKEN", "(optional)", "Jira API token"])
    b.table_row(["JIRA_BOARD_ID", "(optional)", "Sprint board ID"])
    b.table_row(["GOOGLE_CREDENTIALS_PATH", "google_credentials.json", "OAuth2 client credentials"])
    b.table_row(["GOOGLE_TOKEN_PATH", "google_token.json", "OAuth2 access/refresh token"])
    b.table_row(["GOOGLE_CALENDAR_IDS", "primary", "Comma-separated calendar IDs"])
    b.table_row(["DASHBOARD_AUTH_TOKEN", "(required)", "API authentication"])
    b.table_row(["POLL_INTERVAL_SECONDS", "300", "Background poll frequency"])
    b.table_row(["AI_OLLAMA_URL", "http://localhost:11434", "Local LLM endpoint"])
    b.table_row(["REPOS_YAML", "repos.yaml", "Repository configuration file"])
    b.spacer()

    # ── 9 ──
    b.h1("9. Testing & Quality")
    b.spacer()
    b.bold_body("Test Framework")
    b.bullet("pytest + pytest-asyncio for async database and API tests")
    b.bullet("httpx.AsyncClient for FastAPI endpoint testing")
    b.bullet("Coverage threshold: 30% minimum (enforced in CI)")
    b.spacer()
    b.bold_body("Test Suites")
    b.table_row(["Suite", "Covers"], header=True)
    b.table_row(["test_api_health.py", "API health, auth middleware, endpoint responses"])
    b.table_row(["test_new_modules.py", "response_validator, model_registry, claude_code_importer, reports"])
    b.spacer()
    b.bold_body("CI Pipeline (GitHub Actions)")
    b.bullet("Lint: ruff format --check + ruff check")
    b.bullet("Test: pytest across Python 3.11, 3.12, 3.13")
    b.bullet("Container Build: Docker build verification")
    b.bullet("Pre-commit hook: ruff-format auto-fix")
    b.spacer()

    # ── 10 ──
    b.h1("10. Technology Stack Summary")
    b.spacer()
    b.table_row(["Layer", "Technology"], header=True)
    b.table_row(["Language", "Python 3.11+"])
    b.table_row(["Web Framework", "FastAPI + Uvicorn"])
    b.table_row(["Database", "SQLite (aiosqlite, WAL mode)"])
    b.table_row(["Frontend", "Vanilla JS + CSS (single HTML file)"])
    b.table_row(["Charts", "Chart.js"])
    b.table_row(["HTTP Client", "httpx (async)"])
    b.table_row(["Process Manager", "macOS LaunchAgent (launchctl)"])
    b.table_row(["Container", "Docker (OCI image)"])
    b.table_row(["CI/CD", "GitHub Actions"])
    b.table_row(["Linter/Formatter", "Ruff"])
    b.table_row(["Test Framework", "pytest + pytest-asyncio"])
    b.table_row(["OAuth2", "google-auth-oauthlib (Calendar)"])
    b.spacer()

    # ── 11 ──
    b.h1("11. Future Roadmap")
    b.spacer()
    b.bullet("Multi-user support with role-based access")
    b.bullet("Team-wide AI readiness leaderboard")
    b.bullet("Slack / Teams notifications for PR activity")
    b.bullet("GitHub Webhooks for real-time updates (replace polling)")
    b.bullet("Plugin system for custom integrations")
    b.bullet("Browser extension for one-click PR review trigger")
    b.bullet("Mobile-responsive layout")
    b.bullet("Integration with Konflux/Fullsend platform for enterprise agent workflows")
    b.spacer()

    # ── 12 ──
    b.h1("12. Appendix")
    b.spacer()
    b.h2("A. Repository Structure")
    b.code_block(
        "workstream/\n"
        "├── app.py                    # FastAPI application entry point\n"
        "├── config.py                 # Settings with env var overrides\n"
        "├── database.py               # SQLite schema, migrations, queries\n"
        "├── pollers.py                # Background polling engine\n"
        "├── reviewer.py               # Code review prompt generation\n"
        "├── reports.py                # Report generation (Markdown + HTML)\n"
        "├── model_registry.py         # AI model pricing registry\n"
        "├── model_registry.json       # Default pricing data (24 models)\n"
        "├── response_validator.py     # AI response validation & cleanup\n"
        "├── claude_code_importer.py   # Claude Code session importer\n"
        "├── install.sh                # macOS LaunchAgent installer\n"
        "├── com.workstream.dashboard.plist  # LaunchAgent template\n"
        "├── requirements.txt          # Python dependencies\n"
        "├── Dockerfile                # Container build\n"
        "├── .env.example              # Environment variable template\n"
        "├── repos.yaml                # Repository configuration\n"
        "├── static/\n"
        "│   └── index.html            # Single-page dashboard UI\n"
        "├── agentic_readiness/\n"
        "│   ├── scanner.py            # GitHub repo data collector\n"
        "│   ├── scorer.py             # AI readiness scoring engine\n"
        "│   └── generator.py          # Agent-ready file generator\n"
        "├── intelligence/\n"
        "│   └── analyzer.py           # Repository intelligence analysis\n"
        "├── agents/\n"
        "│   ├── registry.py           # Agent registration & management\n"
        "│   └── telemetry.py          # Agent telemetry tracking\n"
        "├── tests/\n"
        "│   ├── test_api_health.py    # API & auth tests\n"
        "│   └── test_new_modules.py   # Module-level tests\n"
        "└── docs/\n"
        "    ├── article-workstream-ai-developer-command-center.md\n"
        "    └── DEMO_SCRIPT.md"
    )
    b.spacer()

    b.h2("B. Related Publications")
    b.bullet('"AI-Augmented Code Review: Lessons from an Enterprise PR Workflow" — Published on arXiv, April 2026')
    b.bullet('"Observability for AI-Assisted Software Development" — Published on arXiv, April 2026')
    b.spacer()

    b.h2("C. Contact")
    b.body("Author: Happy Bhati")
    b.body("GitHub: https://github.com/happybhati")
    b.body("Repository: https://github.com/happybhati/workstream")


def main():
    creds = _get_creds()
    svc = build("docs", "v1", credentials=creds)

    doc = svc.documents().create(body={"title": "Workstream — Solution Architecture Document"}).execute()
    doc_id = doc["documentId"]
    print(f"Created: https://docs.google.com/document/d/{doc_id}/edit")

    b = DocBuilder(svc, doc_id)
    populate(b)
    b.build()


if __name__ == "__main__":
    main()
