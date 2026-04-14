# Workstream Dashboard — Features

This document describes the features of the **Workstream** dashboard: a unified workspace for pull requests, Jira, calendar, AI-assisted review, and developer ergonomics. Each section below corresponds to a major capability exposed in the UI, via APIs, or through companion tooling.

---

## PR Dashboard

The PR Dashboard aggregates pull request activity across **GitHub** and **GitLab** in one place.

### What it tracks

- Open pull requests and draft PRs
- PRs assigned to you
- Review requests (where your review is needed)

### CI status

Continuous integration status is shown on each PR. Check details are **expandable** so you can drill into individual jobs or checks. **Hover** interactions surface per-check run information without cluttering the default card layout.

### Staleness indicators

PRs are color-coded by how long they have been open:

- **Yellow** — open for **3 or more days**
- **Red** — open for **7 or more days**

This makes aging work visible at a glance.

### Cards and filtering

- **User avatars** appear on PR cards for quick recognition of authors and participants.
- **Stat cards** at the summary level are **clickable**; selecting a stat applies a filter so the list matches that slice (for example, drafts only or items needing your review).

---

## Jira Integration

Jira data is woven into the dashboard for sprint awareness, workload signals, and historical comparison.

### Sprint banner

A **sprint tracking banner** shows how many days remain in the current sprint. The banner is **clickable** and deep-links to the sprint board in Jira.

### Task counts and roles

Task metrics support **role filters**, including:

- **Assignee** — work you own
- **Reviewer** — work where you are in a review capacity

Counts update based on the active filter.

### Yearly completion comparison

The integration compares **task completion for the current calendar year** against **the prior year**, with the prior year **pro-rated to the same date** so the comparison stays fair across partial years.

### Privacy and navigation

- Sensitive or distracting numbers can stay **hidden by default**; a **reveal** control toggles visibility.
- Relevant metrics link out to **Jira JQL views** when a deeper investigation in Jira is appropriate.

---

## Google Calendar

The calendar panel presents a **side-by-side** layout for **today** and **tomorrow**.

### Event details

For each event, the dashboard shows:

- Meeting **title**
- **Time**
- **Attendee count**
- **Direct join links** for **Google Meet** when available

### Data source

Events are loaded through the **Google Calendar API** using **OAuth 2.0** for authorized access to the user’s calendar.

---

## AI Code Review

Each PR card includes a **Review** action that runs or prepares an AI-assisted review of the change.

### Model backends

Reviews can be generated using:

- **Claude** (Anthropic API)
- **Gemini** (Google API)
- **Ollama** (local LLM)

### Copy prompt workflow

**Copy Prompt** exports a structured prompt so you can paste it into any external assistant (**Cursor**, **ChatGPT**, or similar) when you prefer not to use an integrated provider.

### Review lifecycle

- Reviews are shown **inside the dashboard** first so a human can **approve** or adjust before anything is published.
- There is an option to **post the review directly** to **GitHub** or **GitLab** after you are satisfied.

### Security

**Diffs are sanitized** before being sent to models or copied, reducing the risk of leaking **secrets** or credentials in review payloads.

---

## Review Intelligence

Review Intelligence builds a **historical picture** of how code review happens on repositories you care about.

### Data collection

It **collects merged PR review history** from **any GitHub repository** you configure, then stores and processes that corpus for analysis.

### Analysis outputs

The system surfaces:

- **Common review categories**
- **Recurring feedback themes**

Patterns help you understand what reviewers consistently care about on a given codebase.

### Configuration

- **UI**: paste **any repository URL** to add or target a repo.
- **CLI**: same workflows are available from the command line for scripting and automation.

### Progress and guidance

- **Real-time progress** is shown while collection runs.
- The feature **generates tool-specific guidance** tailored to assistants such as **Claude**, **Cursor**, **Copilot**, and others so recommendations match how those tools consume context.

---

## AI Readiness Scanner

The AI Readiness Scanner evaluates how well a repository is set up for **AI-assisted development** and agentic workflows.

### Input

You enter a **GitHub repository URL**. The scanner inspects the repository without requiring you to clone it manually for the basic flow.

### What it examines

The scan covers areas such as:

- Repository **structure**
- **Documentation**
- **CI/CD** configuration
- **Agent** and assistant **configuration files**
- **Security** posture signals relevant to safe automation

### Scoring

Results include scores across **five categories**:

1. Agent Config  
2. Documentation  
3. CI Quality  
4. Code Structure  
5. Security  

Each area contributes to an overall picture summarized with **letter grades** from **A** through **F**.

### Tool compatibility

The scanner checks for compatibility signals such as:

- `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`
- `.cursor/rules` and related Cursor conventions  
- Other common agent or IDE integration markers

### Bootstrapping and PRs

- The scanner can **generate bootstrapping files** that **fill gaps only**—it **adds what is missing** rather than overwriting existing, intentional configuration.
- You can optionally **open a draft pull request** that contains the generated files for team review.

---

## Focus Banner

The **Focus Banner** is a single, always-visible summary line at the **top** of the dashboard.

It aggregates high-signal items such as:

- **Pending reviews** you should address
- **Next meeting** time
- **CI failures** that need attention

The goal is to answer “what matters right now?” without switching tabs.

---

## Desktop Notifications

The dashboard can emit **browser (desktop) notifications** for timely events:

- A **PR was approved**
- **CI failed** on a tracked PR
- A **new review request** arrived
- A **meeting is starting in 5 minutes**

### Permissions

Notification permission is **requested on first visit** (or when the feature is first enabled), respecting browser policy and user choice.

---

## Search and Keyboard Shortcuts

### Global search

A **global search bar** filters content **across all tabs**, so one query can narrow PRs, Jira-related panels, and other regions that participate in search.

### Keyboard shortcuts

| Action | Shortcut |
|--------|----------|
| Switch to tab 1–5 | `1`–`5` |
| Refresh data | `r` |
| Close modals | `Esc` |
| Focus search | `/` |

Shortcuts are designed for frequent dashboard users who prefer the keyboard over repeated pointer travel.

---

## Weekly Digest

The **Weekly Digest** is a summary card aimed at **standups** and week-in-review habits.

It typically includes:

- **Merged PRs** in the current week
- **Reviews given** by you (or as configured)
- **Jira tasks closed** in the same period

The digest compresses activity into a scannable block so you can report progress without manual tallying.

---

## Weather Widget

The **header** includes a compact **weather** readout.

### Displayed information

- **Current temperature**
- **Weather condition** (e.g. clear, rain)
- **City name** derived from location

### APIs

- **Open-Meteo** provides forecast and current conditions without a proprietary weather key in many setups.
- **OpenStreetMap** reverse geocoding turns coordinates into a human-readable **city** label.

---

## Live Clock

The header also shows a **live clock** with **seconds**, updated smoothly so glancing at the dashboard doubles as a time check during deep work or meetings.

---

## Stretch Reminders

**Stretch Reminders** appear as an **hourly** popup suggesting a **yoga pose** or **stretch**.

- Reminders are **dismissible** so they never block work for long.
- The intent is to counter long seated sessions during review and coding blocks.

---

## Quick Notes

**Quick Notes** provides lightweight **inline note-taking** tied to the dashboard session.

### Retention options

Each note can be configured with a retention policy:

- **Forever**
- **Today**
- **1 hour**
- **4 hours**
- **This week**

### Lifecycle

- **Expired notes are removed automatically** according to their retention setting.
- A **delete** control removes a note immediately.
- Notes persist in **`localStorage`** in the browser (device-local, not synced to a server by default).

---

## Dark/Light Mode

The dashboard supports **dark** and **light** themes.

- A **toggle in the header** switches modes.
- The choice is **persisted** via **`localStorage`** so returning visits respect your preference.
- The UI uses **CSS variables** for **full theming**—colors, surfaces, and borders remain consistent across components in either mode.

---

## MCP Server

Workstream includes a **Model Context Protocol (MCP) server** that exposes **review intelligence** and **repository knowledge** to external AI tools such as **Cursor** and **Claude**.

### Typical tools

Depending on build and configuration, tools may include capabilities such as:

- **List repositories** known to the system
- **Get repository context** for grounding answers
- **Review patterns** and **category statistics**
- **Recent PRs** and related metadata

The MCP layer lets assistants query the same insights the dashboard uses, without scraping the UI.

---

## CLI (`workstream` command)

The **`workstream`** CLI is a full **command-line interface** for operating the dashboard stack and related jobs.

### Common command areas

- **Service control**: `start`, `stop`, `restart`, `status`
- **Developer convenience**: `open` (browser), **tail logs**
- **Review intelligence**: **collect reviews**, **analyze patterns**
- **Readiness**: **scan** repositories
- **Integration**: **check MCP status**

The CLI mirrors and extends UI workflows for automation, CI, and headless environments.

---

## macOS LaunchAgent

On **macOS**, Workstream can run as a **persistent background service** via a **LaunchAgent**.

### Behavior

- **Starts automatically on login**
- **Restarts on crash** so the dashboard and pollers recover without manual intervention

### Installation

**One-command** scripts (or documented equivalents) support **install** and **uninstall** of the LaunchAgent plist and associated paths, keeping setup repeatable across machines.

---

## Document maintenance

When adding or changing dashboard behavior, update this file so operators and contributors share a single, accurate description of product capabilities. Prefer concrete user-visible behavior over implementation detail unless the detail affects security or integration contracts.
