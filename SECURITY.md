# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| latest  | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in Workstream, please report it responsibly:

1. **Do NOT** open a public GitHub issue
2. Email: happybhati@github (or open a private security advisory on GitHub)
3. Include: description, steps to reproduce, potential impact

## Security Considerations

- **API tokens**: All credentials are stored in `.env` (git-ignored) and loaded via `config.py`
- **Local-only**: Workstream runs locally and does not expose any public endpoints
- **No secrets in code**: The `.gitignore` covers `.env`, credentials, keys, and tokens
- **Dependencies**: Monitored via Dependabot for known vulnerabilities
