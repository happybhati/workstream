# Team Setup Guide

Workstream is designed as a **personal-instance tool**. Each person runs their own
copy with their own tokens. There is no shared database or multi-tenant mode.

## Quick Start

```bash
git clone https://github.com/happybhati/workstream.git
cd workstream
cp .env.example .env
# Edit .env with your tokens (see below)
pip install -r requirements.txt
python -m uvicorn app:app
# Open http://localhost:8080
```

## Creating a GitHub Personal Access Token

1. Go to https://github.com/settings/tokens?type=beta (fine-grained tokens)
2. Click **Generate new token**
3. Set a descriptive name (e.g. "Workstream Dashboard")
4. Select minimum required permissions:
   - **Repository access**: All repositories (or select specific ones)
   - **Permissions**: `Pull requests: Read`, `Contents: Read`, `Metadata: Read`
5. Copy the token into your `.env` as `GITHUB_PAT`

Classic tokens also work — select scopes: `repo:status`, `read:org`, `read:user`.

## Creating a Jira API Token (optional)

1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click **Create API token**
3. Set your `.env`:
   ```
   JIRA_URL=https://your-org.atlassian.net
   JIRA_EMAIL=you@example.com
   JIRA_API_TOKEN=your_token
   JIRA_PROJECTS=PROJ1,PROJ2
   ```

## Protecting a Network-Exposed Instance

If you expose Workstream beyond localhost (e.g. for a shared VM), always:

1. **Set an auth token** — add `WORKSTREAM_AUTH_TOKEN=some-long-random-secret` to `.env`
2. **Use HTTPS** — put a reverse proxy in front (see `docs/deployment/nginx.conf.example`)
3. **Bind explicitly** — set `WORKSTREAM_HOST=0.0.0.0` only when behind a proxy

Without these, anyone on the network can see your PRs, Jira tasks, and calendar.

## Container Deployment

```bash
podman build -t workstream:dev -f Containerfile .
podman run -p 8080:8080 --env-file .env workstream:dev
```

See `docs/deployment/` for Kubernetes and OpenShift manifests.

## Security Checklist

- [ ] `.env` is in `.gitignore` (default — do not change)
- [ ] Tokens use minimum required scopes
- [ ] `WORKSTREAM_AUTH_TOKEN` is set if exposed on a network
- [ ] HTTPS via reverse proxy if accessed over a network
- [ ] Container runs as non-root user (default in Containerfile)
