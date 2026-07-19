# Workstream: A Local-First Command Center for the AI-Native Developer

*By Happy Bhati*

---

## The Problem Nobody Talks About

Software engineering in 2026 doesn't look anything like it did even two years ago. AI coding assistants now generate pull requests, triage bugs, review code, and draft documentation. Platforms like Cursor, Claude Code, and GitHub Copilot have fundamentally changed how developers write software.

But here's the quiet crisis: **the tools that help us *manage* our work haven't kept up.**

A typical engineer's morning looks something like this: check GitHub for PR reviews, flip to GitLab for a cross-team MR, open Jira to update sprint tickets, glance at Google Calendar for the standup time, switch to Slack for review threads, check CI dashboards for a broken pipeline, and finally open Cursor to actually write code. By the time you start coding, you've context-switched six times and lost 20 minutes of deep focus.

Now add AI costs. You're running Claude reviews, Gemini summaries, and local Ollama models. How much is all of this costing? Which models are you actually using? Nobody knows, because that data lives in three different billing dashboards.

This is the problem Workstream solves.

## What Is Workstream?

Workstream is an open-source, local-first developer command center built with FastAPI and SQLite. It runs on your machine, polls your existing tools (GitHub, GitLab, Jira, Google Calendar), and presents a unified view of everything you need to know — in a single browser tab at `localhost:8080`.

No cloud infrastructure. No SaaS subscription. No data leaving your machine.

It was born out of a practical need: as our team at Red Hat began adopting AI-assisted development workflows with the Fullsend platform and Konflux CI, we realized we needed a single pane of glass that understood both traditional development workflows *and* the emerging AI layer on top of them.

## The Five Pillars

Workstream is organized around five core capabilities that together cover the full lifecycle of an AI-native developer's day.

### 1. Unified Work Visibility

The home dashboard gives you a single-glance picture of your entire workload:

- **7 stat cards** across the top: Open PRs, Drafts, Assigned PRs, Pending Reviews, CI Failing, Merged (30 days), and Jira Tasks.
- **Sprint banner** with days remaining, task chips by status, and a link to the Jira board.
- **Calendar widget** showing today's and tomorrow's meetings with Google Meet join links.
- **Weekly digest strip** summarizing PRs merged, reviews given, and tasks closed this week.
- **Yearly completion tracker** comparing Jira throughput year-over-year.

All of this updates automatically in the background. You don't refresh anything. You don't check five different websites. You open one tab.

The PR tabs (My PRs, Assigned, Review Requests) show CI status badges, staleness indicators (amber for 3+ days idle, red for 7+), Jira ticket links, reviewer avatars, and a new "changes since last review" badge that tells you when a PR you've already reviewed has new commits or comments.

### 2. AI-Assisted Code Review

Every PR card has a **Review** button that opens a review modal. You can:

- **Copy a review prompt** — a rich, structured prompt with the PR link, metadata (author, labels, reviewers, changed files), and repository-specific team review patterns. No raw diff is included; the prompt directs the AI tool to fetch the diff from the URL. This works with any LLM: paste it into Cursor, ChatGPT, Claude, or any tool you prefer.

- **Generate an AI review in-app** — select a provider (Claude, Gemini, or local Ollama), and Workstream fetches the diff, sanitizes secrets, sends it through the selected model, validates the response structure, and presents the findings. You review the AI's suggestions, then optionally post them as inline comments on GitHub or GitLab.

The human always approves before anything is posted. AI assists; you decide.

The review pipeline includes a **response validator** that strips LLM preamble ("Sure! Here's my review..."), extracts structured JSON, validates comment shapes, and truncates runaway responses. This means you get clean, actionable output regardless of which model you're using.

### 3. Review Intelligence

How do you know what your team actually cares about in code reviews? Workstream's Intelligence module answers this empirically.

Point it at any GitHub repository, and it will:

1. Collect merged PRs and their human review comments.
2. Classify each comment by category (bug, security, testing, documentation, performance, naming, etc.) using keyword analysis.
3. Extract recurring patterns and themes.
4. Build per-reviewer profiles showing what each person focuses on.
5. Optionally generate an AI narrative summary of the findings.

This isn't theoretical. We ran it against `konflux-ci/release-service-catalog` and discovered that reviewers overwhelmingly focus on testing patterns (test coverage, idempotency) and documentation quality. That insight was immediately useful for calibrating our own AI review prompts.

The output also feeds back into the review prompt generator: when you generate a review prompt for a repo that has intelligence data, the prompt includes a "Team Review Context" section with actual patterns from past reviews, so the AI reviewer knows what the team historically cares about.

### 4. AI Readiness Scanner

As organizations adopt AI-assisted development, a critical question emerges: **how ready is your repository for AI agents?**

Workstream includes a comprehensive readiness scanner that evaluates any GitHub repository across six categories:

| Category | What It Measures |
|----------|-----------------|
| Agent Configuration | Presence of AGENTS.md, CLAUDE.md, .cursorrules, MCP config |
| Documentation | README quality, CONTRIBUTING.md, ADRs, code of conduct |
| CI Quality | CI workflow coverage, CODEOWNERS, branch protection signals |
| Code Structure | Consistent layout, test directories, Makefile, scripts |
| Security | Secret scanning, dependency review, security policy |
| Fullsend Readiness | Skills directory, backpressure mechanisms (linters, type checkers, test suites), BOOKMARKS.md |

The scanner produces a 0-100 score with a letter grade and prioritized recommendations. But it goes further: it can **generate the missing files** for you. One click produces a complete AGENTS.md, CLAUDE.md, Cursor rules, agent skills (CSO-compliant with "Use when..." descriptions), and a BOOKMARKS.md. Another click opens a draft PR with all of them.

This directly supports the advice from Ralph Bean's recent note to Secure Flow engineers: get your repositories ready for agents, create agentskills.io-compliant skills, and give AI tools the context they need about your specific repository.

### 5. AI Cost & Telemetry Dashboard

This is the feature most teams don't know they need until they see it.

The **AI Costs** tab tracks every AI operation across your entire workflow:

- **Summary cards**: total API calls, tokens consumed, estimated cost, average latency.
- **Daily cost trend chart**: a canvas-based visualization showing spending over time.
- **Breakdown by model**: which models you're using and what each costs.
- **Breakdown by feature**: review costs vs. intelligence costs vs. manual entries.
- **Manual cost entry**: log your Cursor Pro subscription, ChatGPT Plus, or any external AI spend.
- **Claude Code importer**: automatically discovers local Claude Code sessions from `~/.claude/projects/` and imports their token usage for unified tracking.
- **Model registry**: 24 pre-configured models with per-million-token pricing, plus the ability to add custom models or override prices.
- **Report generation**: weekly digest, cost summary, and review summary — in Markdown and HTML, ready to share with your manager or attach to a quarterly review.

When every team member is using AI tools daily, visibility into aggregate cost and usage patterns becomes essential for budgeting, model selection, and identifying where AI assistance provides the most value.

## Architecture: Local-First by Design

```
Browser ──── FastAPI (localhost:8080) ──── SQLite (data.db)
                    │
                    ├── GitHub API (polling)
                    ├── GitLab API (polling)
                    ├── Jira REST API (polling)
                    ├── Google Calendar API (OAuth)
                    ├── AI Providers (Claude, Gemini, Ollama)
                    └── MCP Agent Registry
```

Workstream is a single Python process running as a macOS LaunchAgent (with Linux systemd support). It polls your configured services every 5 minutes (configurable), stores everything in a local SQLite database, and serves a single-page application on port 8080.

There is no cloud component. Your GitHub tokens, Jira credentials, and AI API keys never leave your machine. The entire state fits in a single `.db` file you can back up, inspect with `sqlite3`, or delete to start fresh.

The frontend is a single `index.html` file — no build step, no node_modules, no framework. Vanilla HTML, CSS, and JavaScript. It loads instantly and works offline against cached data.

## The Agent Management Layer

As the number of AI agents in a developer's toolkit grows, Workstream provides an **Agents** tab that serves as a registry and health monitor:

- **MCP server discovery**: automatically reads your Cursor MCP configuration and lists all configured servers with their health status.
- **A2A agent registration**: register any Agent-to-Agent (A2A) compatible agent by URL. Workstream fetches its agent card and monitors availability.
- **Telemetry aggregation**: per-agent operation counts, token usage, cost, and latency.
- **Live activity stream**: an SSE-powered real-time feed of agent operations (poll cycles, review runs, registry refreshes).

This matters because in the near future, developers won't just use one AI assistant — they'll have a constellation of specialized agents for different tasks. Workstream provides the control plane for that constellation.

## Why Local-First Matters

There's a reason Workstream doesn't run in the cloud:

1. **Privacy**: Your code diffs, Jira tickets, and calendar events stay on your machine. No third-party service sees your proprietary code.

2. **Speed**: No network round-trips for dashboard loads. The SPA renders from local SQLite in milliseconds.

3. **Cost**: Zero infrastructure spend. No Kubernetes cluster, no managed database, no SaaS per-seat pricing.

4. **Reliability**: Works offline (against cached data). No dependency on someone else's uptime.

5. **Customizability**: It's a Python app on your machine. Add an endpoint, tweak a poller, adjust the UI — it's your tool.

## Who Is This For?

Workstream was built for individual contributors and tech leads who:

- Work across multiple platforms (GitHub + GitLab + Jira is common in enterprise).
- Use or plan to use AI coding assistants and want visibility into cost and usage.
- Need to track "changes since I last reviewed" across many PRs.
- Want to understand their team's code review patterns empirically.
- Are evaluating or improving their repositories' readiness for AI agents.
- Simply want to stop context-switching between seven browser tabs every morning.

It's also valuable for engineering managers who need to answer questions like: "How much are we spending on AI tools?", "Which repositories are ready for agentic workflows?", and "What does our team actually focus on in code reviews?"

## Getting Started

```bash
git clone https://github.com/happybhati/workstream.git
cd workstream
cp .env.example .env
# Add your GITHUB_PAT (minimum)
./install.sh        # macOS: creates LaunchAgent, starts automatically
open http://localhost:8080
```

With just a GitHub token, you get the PR dashboard, AI readiness scanner, and review intelligence. Add Jira, GitLab, Google Calendar, and AI provider keys incrementally as you need them.

## What's Next

Workstream is actively developed. Upcoming areas include:

- **Linux systemd support** for non-macOS environments.
- **Container deployment** for team-shared instances (opt-in, privacy-conscious).
- **GitLab intelligence** parity with GitHub.
- **Deeper Fullsend integration** as the platform matures.
- **Plugin system** for custom pollers and dashboard panels.

## Closing Thought

The software industry is in the middle of the most significant tooling shift since the move to cloud-native development. AI assistants are becoming first-class participants in the development lifecycle — writing code, reviewing PRs, triaging bugs, and generating documentation.

But more tools means more complexity, more context-switching, and more cost opacity. The developers who thrive in this new era won't be the ones who adopt the most AI tools — they'll be the ones who maintain clarity and control over their entire workflow.

That's what Workstream is for. One tab. Full picture. Your machine.

---

*Workstream is open source under Apache 2.0. Contributions, feedback, and stars welcome at [github.com/happybhati/workstream](https://github.com/happybhati/workstream).*
