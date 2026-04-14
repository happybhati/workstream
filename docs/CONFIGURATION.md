# Workstream configuration

## Overview

Workstream reads all integration and behavior settings from environment variables, typically via a `.env` file in the dashboard project directory. Copy `.env.example` to `.env`, then set values only for the integrations you plan to use. Leave optional entries unset or commented unless you need them.

The application loads these variables when it starts; restart the server or polling process after changing `.env`.

## GitHub (Required)

1. Go to **Settings** → **Developer settings** → **Personal access tokens** → **Fine-grained tokens**.
2. Create a token with these scopes: **Repository** read access (equivalent to classic `repo` read for the repositories you select), and **Pull requests** read/write (write is required for AI review posting as comments on pull requests).
3. Set `GITHUB_PAT` and `GITHUB_USERNAME` in `.env`.

## GitLab (Optional)

1. In GitLab, open **Preferences** → **Access Tokens** (or your instance’s equivalent personal access token page).
2. Create a token with the **read_api** scope (and any additional scopes your admin requires for API access to projects and merge requests).
3. In `.env`, set:
   - `GITLAB_PAT` — the token value.
   - `GITLAB_URL` — your GitLab base URL (defaults to `https://gitlab.com` if omitted).
   - `GITLAB_USERNAME` — your GitLab username used for filtering and display logic.

## Jira (Optional)

1. Go to [Atlassian account security — API tokens](https://id.atlassian.com/manage-profile/security/api-tokens).
2. Create an API token and copy it when shown (it is not displayed again).
3. In `.env`, set:
   - `JIRA_URL` — site base URL, for example `https://yourcompany.atlassian.net` (no trailing path).
   - `JIRA_EMAIL` — the Atlassian account email associated with the token.
   - `JIRA_API_TOKEN` — the token string.
4. Set `JIRA_PROJECTS` to a comma-separated list of project keys to include in tracking (for example `PROJ1,PROJ2`).
5. Set `JIRA_ACCOUNT_NAME` to your display name as it appears in Jira (used when filtering work assigned to you).
6. Set `JIRA_BOARD_PROJECTS` to a comma-separated list of project keys whose sprint boards should be linked in the dashboard.

## Google Calendar (Optional)

OAuth 2.0 setup:

1. Open the [Google Cloud Console](https://console.cloud.google.com/) and create a project or select an existing one.
2. Enable the **Google Calendar API** for that project (**APIs & Services** → **Library**).
3. Configure the **OAuth consent screen** (**APIs & Services** → **OAuth consent screen**). Use **Internal** if the project is under a Google Workspace organization and only staff will use the app; otherwise use **External** and complete any verification steps Google requires.
4. Under **Credentials**, create an **OAuth 2.0 Client ID** of type **Desktop app**.
5. Download the client JSON file from the credential details.
6. Place the file in the dashboard project directory as `google_credentials.json`, or set `GOOGLE_CREDENTIALS_PATH` in `.env` to the full path of that file.
7. On first use of Calendar integration, a browser window opens for OAuth consent. Approve access; the app stores a refresh token (default path: `google_token.json`, overridable with `GOOGLE_TOKEN_PATH`).
8. Set `GOOGLE_CALENDAR_IDS` to a comma-separated list of calendar IDs. Omit or use `primary` for your main calendar.

## AI Code Review (Optional)

You can use one or more providers. **Copy Prompt** mode works without API keys: it only builds a prompt you paste into any LLM.

- **Claude** — Create an API key in the [Anthropic Console](https://console.anthropic.com/). Set `AI_CLAUDE_API_KEY`. Optionally set `AI_CLAUDE_MODEL` (see defaults in the reference table below).
- **Gemini** — Create an API key in [Google AI Studio](https://aistudio.google.com/). Set `AI_GEMINI_API_KEY`. Optionally set `AI_GEMINI_MODEL`.
- **Ollama** — Install [Ollama](https://ollama.com/) locally and pull a model. Set `AI_OLLAMA_URL` if not using the default local endpoint, and `AI_OLLAMA_MODEL` to the model tag you use.

## Display and Behavior

- **DISPLAY_NAME** — Shown in the dashboard greeting when set.
- **POLL_INTERVAL** — Polling interval in seconds for refreshing remote data (default: 300).

## Repo Filtering

- **IGNORED_REPOS** — Comma-separated `owner/repo` identifiers to exclude from review-request tracking.
- **INTELLIGENCE_DEFAULT_REPOS** — Comma-separated default repositories for intelligence collection when a run does not specify repositories explicitly.

## Paths

- **DB_PATH** — SQLite database file path (default: `./data.db` relative to the dashboard package directory).
- **LOG_DIR** — Directory for log files (default: `./logs`).
- **REPOS_YAML** — Path to an optional `repos.yaml` file for extra repository tracking configuration.

## Full Environment Variable Reference

| Variable | Required | Default | Description |
| -------- | -------- | ------- | ----------- |
| `AI_CLAUDE_API_KEY` | No | *(empty)* | Anthropic API key for Claude-based review. |
| `AI_CLAUDE_MODEL` | No | `claude-sonnet-4-20250514` | Claude model id for reviews. |
| `AI_GEMINI_API_KEY` | No | *(empty)* | Google AI Studio API key for Gemini-based review. |
| `AI_GEMINI_MODEL` | No | `gemini-2.0-flash` | Gemini model id for reviews. |
| `AI_OLLAMA_MODEL` | No | `llama3` | Ollama model name/tag. |
| `AI_OLLAMA_URL` | No | `http://localhost:11434` | Ollama HTTP API base URL. |
| `DB_PATH` | No | `<project>/data.db` | SQLite database file path. |
| `DISPLAY_NAME` | No | *(empty)* | Name shown in the UI greeting. |
| `GITHUB_PAT` | Yes* | *(empty)* | GitHub personal access token (fine-grained or classic per your policy). |
| `GITHUB_USERNAME` | Yes* | *(empty)* | GitHub username for matching PRs and reviews. |
| `GITLAB_PAT` | No | *(empty)* | GitLab personal access token. |
| `GITLAB_URL` | No | `https://gitlab.com` | GitLab instance base URL. |
| `GITLAB_USERNAME` | No | *(empty)* | GitLab username. |
| `GOOGLE_CALENDAR_IDS` | No | `primary` | Comma-separated calendar IDs; use `primary` for the default calendar. |
| `GOOGLE_CREDENTIALS_PATH` | No | `<project>/google_credentials.json` | Path to OAuth client JSON from Google Cloud. |
| `GOOGLE_TOKEN_PATH` | No | `<project>/google_token.json` | Path where the OAuth refresh token is stored after first consent. |
| `IGNORED_REPOS` | No | *(empty)* | Comma-separated `owner/repo` values excluded from review tracking. |
| `INTELLIGENCE_DEFAULT_REPOS` | No | *(empty)* | Comma-separated default repos for intelligence runs. |
| `JIRA_ACCOUNT_NAME` | No | *(empty)* | Jira display name for user-centric filters. |
| `JIRA_API_TOKEN` | No | *(empty)* | Atlassian API token for Jira REST API. |
| `JIRA_BOARD_PROJECTS` | No | *(empty)* | Comma-separated Jira project keys for board links. |
| `JIRA_EMAIL` | No | *(empty)* | Email for Jira API authentication. |
| `JIRA_PROJECTS` | No | *(empty)* | Comma-separated Jira project keys to track. |
| `JIRA_URL` | No | *(empty)* | Jira site URL (e.g. `https://company.atlassian.net`). |
| `LOG_DIR` | No | `<project>/logs` | Directory for application logs. |
| `POLL_INTERVAL` | No | `300` | Seconds between data refresh polls. |
| `REPOS_YAML` | No | `<project>/repos.yaml` | Optional repos configuration file path. |

\*Required for core GitHub dashboard features; other integrations remain optional.
