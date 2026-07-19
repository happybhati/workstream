"""Scan any GitHub repository for AI/agentic readiness.

Uses the GitHub API to fetch the file tree, key files, CI configuration,
and language breakdown -- returning a structured ScanResult dict used by
the scorer and generator.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from datetime import datetime, timezone

import httpx

from config import settings

logger = logging.getLogger("dashboard.readiness.scanner")

GITHUB_API = "https://api.github.com"

REPO_URL_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/(?P<owner>[^/]+)/(?P<repo>[^/\s#?]+)")

KEY_FILES = [
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "README.md",
    "ARCHITECTURE.md",
    "CONTRIBUTING.md",
    "CODEOWNERS",
    "LICENSE",
    "SECURITY.md",
    ".gitignore",
    ".github/copilot-instructions.md",
    ".github/dependabot.yml",
    ".codex/config.toml",
    "BOOKMARKS.md",
    "Makefile",
]

LINTER_GLOBS = {
    ".eslintrc",
    ".eslintrc.js",
    ".eslintrc.json",
    ".eslintrc.yml",
    ".flake8",
    ".pylintrc",
    "pyproject.toml",
    "setup.cfg",
    ".golangci.yml",
    ".golangci.yaml",
    ".prettierrc",
    ".prettierrc.json",
    ".prettierrc.yml",
    "biome.json",
    "deno.json",
    "Makefile",
    "justfile",
    ".rubocop.yml",
    ".stylelintrc",
    "tslint.json",
}

DEP_FILES = {
    "go.mod",
    "go.sum",
    "package.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "package-lock.json",
    "requirements.txt",
    "Pipfile",
    "poetry.lock",
    "pyproject.toml",
    "Cargo.toml",
    "Gemfile",
    "build.gradle",
    "pom.xml",
    "mix.exs",
    "composer.json",
}

STRUCTURED_DIRS = {
    "src",
    "pkg",
    "internal",
    "lib",
    "cmd",
    "api",
    "app",
    "core",
    "modules",
    "services",
    "components",
}

SECRET_PATTERNS_IN_TREE = {
    ".env",
    ".env.local",
    ".env.production",
    "credentials.json",
    "secrets.json",
    "secrets.yaml",
    "service-account.json",
    ".npmrc",
    ".pypirc",
    "id_rsa",
    "id_ed25519",
}

SECRET_CONTENT_RE = re.compile(
    r"(?i)(ghp_[a-zA-Z0-9]{36}|glpat-[a-zA-Z0-9\-]{20}"
    r"|sk-[a-zA-Z0-9]{32,}|AKIA[0-9A-Z]{16}"
    r"|-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----"
    r"|password\s*[:=]\s*['\"][^'\"]{8,})"
)

RISKY_AGENT_PATTERNS = re.compile(
    r"(?i)(curl\s.*\|\s*(ba)?sh"
    r"|wget\s.*\|\s*(ba)?sh"
    r"|\$\{?(?:GITHUB_TOKEN|AWS_SECRET|OPENAI_API_KEY|ANTHROPIC_API_KEY|GH_TOKEN)\}?"
    r"|rm\s+-rf\s+/"
    r"|eval\s*\("
    r"|exec\s*\()"
)

AGENTS_MD_SECTIONS = [
    "summary",
    "rules",
    "guidelines",
    "context",
    "must-read",
    "build",
    "test",
    "style",
    "architecture",
    "security",
]

TYPE_CHECKER_PATTERNS = {
    "mypy.ini",
    ".mypy.ini",
    "pyrightconfig.json",
    "tsconfig.json",
    "jsconfig.json",
}

PRE_COMMIT_FILES = {
    ".pre-commit-config.yaml",
    ".husky",
}


def _github_headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.github_pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def parse_repo_url(url: str) -> tuple[str, str]:
    """Extract (owner, repo) from a GitHub URL or 'owner/repo' string."""
    url = url.strip().rstrip("/")
    m = REPO_URL_RE.search(url)
    if m:
        return m.group("owner"), m.group("repo").removesuffix(".git")
    parts = url.split("/")
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[0], parts[1].removesuffix(".git")
    raise ValueError(f"Cannot parse GitHub repo from: {url}")


async def scan_repo(repo_url: str) -> dict:
    """Scan a GitHub repository and return a ScanResult dict."""
    if not settings.github_pat:
        raise RuntimeError("GITHUB_PAT not configured")

    owner, repo = parse_repo_url(repo_url)
    logger.info("Scanning %s/%s", owner, repo)

    async with httpx.AsyncClient(
        base_url=GITHUB_API,
        headers=_github_headers(),
        timeout=30,
    ) as client:
        metadata, languages = await asyncio.gather(
            _fetch_metadata(client, owner, repo),
            _fetch_languages(client, owner, repo),
        )

        default_branch = metadata.get("default_branch", "main")
        tree = await _fetch_tree(client, owner, repo, default_branch)

        key_files = {}
        for fname in KEY_FILES:
            path_in_tree = _find_file_in_tree(tree, fname)
            if path_in_tree:
                content = await _fetch_file(client, owner, repo, path_in_tree)
                key_files[fname] = content
            else:
                key_files[fname] = ""
            await asyncio.sleep(0.1)

        ci_workflows = await _check_ci(client, owner, repo)

    all_paths = [item for item in tree]
    top_dirs = sorted({p.split("/")[0] for p in all_paths if "/" in p})

    linter_files = [p for p in all_paths if p.split("/")[-1] in LINTER_GLOBS]
    dep_files_found = [p for p in all_paths if p.split("/")[-1] in DEP_FILES]
    test_dirs = [
        d for d in top_dirs if d.lower() in ("test", "tests", "spec", "specs", "__tests__", "e2e", "integration-tests")
    ]
    if not test_dirs:
        test_dirs = [
            p.split("/")[0]
            for p in all_paths
            if any(seg in p.lower() for seg in ("_test.", "_test/", "test_", "/tests/", "/spec/"))
        ]
        test_dirs = sorted(set(test_dirs))

    doc_dirs = [d for d in top_dirs if d.lower() in ("docs", "doc", "documentation", "wiki")]
    cursor_rules = [p for p in all_paths if p.startswith(".cursor/rules/")]
    claude_rules = [p for p in all_paths if p.startswith(".claude/rules/")]
    structured = [d for d in top_dirs if d.lower() in STRUCTURED_DIRS]

    secrets_in_tree = [p for p in all_paths if p.split("/")[-1] in SECRET_PATTERNS_IN_TREE]

    has_secrets_in_content = False
    for fname in ("README.md", ".gitignore"):
        content = key_files.get(fname, "")
        if content and SECRET_CONTENT_RE.search(content):
            has_secrets_in_content = True
            break

    gitignore = key_files.get(".gitignore", "")
    gitignore_covers_secrets = (
        any(pat in gitignore.lower() for pat in (".env", "credentials", "secrets", "*.pem", "*.key", "id_rsa"))
        if gitignore
        else False
    )

    renovate_files = [p for p in all_paths if "renovate" in p.lower() and p.endswith(".json")]
    has_dependabot = bool(key_files.get(".github/dependabot.yml", ""))
    has_renovate = bool(renovate_files)

    e2e_dirs = sorted(
        {
            p.split("/")[0]
            for p in all_paths
            if p.split("/")[0].lower() in ("e2e", "integration-tests", "integration") and "/" in p
        }
        | {
            "/".join(p.split("/")[:2])
            for p in all_paths
            if len(p.split("/")) >= 3 and p.split("/")[1].lower() in ("e2e", "integration")
        }
    )

    hack_scripts = sorted(p for p in all_paths if p.startswith("hack/"))

    kind_configs = sorted(
        p
        for p in all_paths
        if "kind" in p.lower() and (p.endswith(".yaml") or p.endswith(".yml") or p.endswith(".conf"))
    )

    dockerfiles = sorted(
        p
        for p in all_paths
        if p.split("/")[-1].lower() in ("dockerfile", "containerfile")
        or p.split("/")[-1].lower().startswith("dockerfile.")
    )

    deployment_manifests = sorted(
        p
        for p in all_paths
        if any(seg in p.lower() for seg in ("deploy", "kustomize", "helm", "manifest", "k8s", "kubernetes"))
        and (p.endswith(".yaml") or p.endswith(".yml") or p.endswith(".json"))
    )

    existing_skills = sorted(p for p in all_paths if p.startswith("skills/") and p.endswith("SKILL.md"))

    skill_symlinks = sorted(
        p
        for p in all_paths
        if (p.startswith(".claude/skills/") or p.startswith(".cursor/skills/") or p.startswith(".agents/skills/"))
        and p.endswith("SKILL.md")
    )

    type_checker_files = [p for p in all_paths if p.split("/")[-1] in TYPE_CHECKER_PATTERNS]
    pre_commit_files = [p for p in all_paths if p.split("/")[-1] in PRE_COMMIT_FILES or p.startswith(".husky/")]

    ci_content = {}
    async with httpx.AsyncClient(
        base_url=GITHUB_API,
        headers=_github_headers(),
        timeout=30,
    ) as client:
        ci_yaml_paths = [
            p for p in all_paths if p.startswith(".github/workflows/") and (p.endswith(".yml") or p.endswith(".yaml"))
        ]
        for ci_path in ci_yaml_paths[:5]:
            content = await _fetch_file(client, owner, repo, ci_path)
            if content:
                ci_content[ci_path] = content
            await asyncio.sleep(0.1)

    ci_commands = _extract_ci_commands(ci_content)
    makefile_targets = _extract_makefile_targets(key_files.get("Makefile", ""))

    claude_md_lines = len(key_files.get("CLAUDE.md", "").splitlines()) if key_files.get("CLAUDE.md") else 0
    has_bookmarks = bool(key_files.get("BOOKMARKS.md", ""))

    agents_md_analysis = _analyze_agents_md(key_files.get("AGENTS.md", ""))
    skill_details = _analyze_skills(existing_skills, key_files, ci_content, client if False else None)
    agent_config_risks = _detect_agent_config_risks(key_files)
    arch_md_quality = _analyze_architecture_md(key_files.get("ARCHITECTURE.md", ""))

    return {
        "owner": owner,
        "repo": repo,
        "full_name": f"{owner}/{repo}",
        "description": metadata.get("description", "") or "",
        "default_branch": default_branch,
        "visibility": metadata.get("visibility", "unknown"),
        "primary_language": metadata.get("language", "") or "",
        "languages": languages,
        "tree": all_paths,
        "dirs": top_dirs,
        "key_files": key_files,
        "has_ci": len(ci_workflows) > 0,
        "ci_workflows": ci_workflows,
        "linter_files": linter_files,
        "dep_files": dep_files_found,
        "test_dirs": test_dirs,
        "doc_dirs": doc_dirs,
        "cursor_rules": cursor_rules,
        "claude_rules": claude_rules,
        "structured_dirs": structured,
        "secrets_in_tree": secrets_in_tree,
        "has_secrets_in_content": has_secrets_in_content,
        "gitignore_covers_secrets": gitignore_covers_secrets,
        "has_dependabot": has_dependabot,
        "has_renovate": has_renovate,
        "e2e_dirs": e2e_dirs,
        "hack_scripts": hack_scripts,
        "kind_configs": kind_configs,
        "dockerfiles": dockerfiles,
        "deployment_manifests": deployment_manifests,
        "existing_skills": existing_skills,
        "skill_symlinks": skill_symlinks,
        "skill_details": skill_details,
        "type_checker_files": type_checker_files,
        "pre_commit_files": pre_commit_files,
        "ci_content": ci_content,
        "ci_commands": ci_commands,
        "makefile_targets": makefile_targets,
        "claude_md_lines": claude_md_lines,
        "has_bookmarks": has_bookmarks,
        "agents_md_analysis": agents_md_analysis,
        "agent_config_risks": agent_config_risks,
        "arch_md_quality": arch_md_quality,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }


def _analyze_agents_md(content: str) -> dict:
    """Analyze AGENTS.md for section completeness, line count, and quality."""
    if not content:
        return {"present": False, "lines": 0, "sections_found": [], "section_count": 0, "quality": "missing"}

    lines = content.splitlines()
    line_count = len(lines)
    lower = content.lower()

    sections_found = []
    for section in AGENTS_MD_SECTIONS:
        if section in lower or f"# {section}" in lower or f"## {section}" in lower:
            sections_found.append(section)

    heading_re = re.compile(r"^#{1,3}\s+(.+)", re.MULTILINE)
    headings = heading_re.findall(content)

    quality = "good"
    if line_count > 100:
        quality = "verbose"
    elif line_count < 10:
        quality = "minimal"
    elif len(sections_found) < 3:
        quality = "incomplete"

    return {
        "present": True,
        "lines": line_count,
        "sections_found": sections_found,
        "section_count": len(sections_found),
        "headings": headings[:10],
        "quality": quality,
        "under_60": line_count <= 60,
        "under_100": line_count <= 100,
    }


def _analyze_skills(skill_paths: list[str], key_files: dict, ci_content: dict, client) -> list[dict]:
    """Analyze skill quality from paths (content fetched separately if needed)."""
    details = []
    for path in skill_paths:
        parts = path.split("/")
        if len(parts) < 3:
            continue
        skill_name = parts[1]
        detail = {
            "path": path,
            "name": skill_name,
            "has_frontmatter": False,
            "has_description": False,
            "description_optimized": False,
            "has_scripts_dir": False,
            "has_references_dir": False,
            "quality_score": 0,
        }
        details.append(detail)
    return details


def _detect_agent_config_risks(key_files: dict) -> list[dict]:
    """Scan agent config files for risky patterns (AgentLint-inspired)."""
    risks = []
    files_to_check = ["AGENTS.md", "CLAUDE.md", ".github/copilot-instructions.md"]
    for fname in files_to_check:
        content = key_files.get(fname, "")
        if not content:
            continue
        for match in RISKY_AGENT_PATTERNS.finditer(content):
            risks.append(
                {
                    "file": fname,
                    "pattern": match.group(0)[:80],
                    "severity": "high" if "rm -rf" in match.group(0).lower() else "medium",
                }
            )
    return risks


def _analyze_architecture_md(content: str) -> dict:
    """Assess ARCHITECTURE.md quality for AI readability."""
    if not content:
        return {"present": False, "quality": "missing", "has_headings": False, "has_code_blocks": False}

    headings = re.findall(r"^#{1,3}\s+.+", content, re.MULTILINE)
    code_blocks = content.count("```")
    has_api = bool(re.search(r"(?i)(api|endpoint|route|grpc|rest|graphql)", content))
    has_diagram = bool(re.search(r"(?i)(mermaid|diagram|flowchart|graph\s|sequenceDiagram)", content))
    lines = len(content.splitlines())

    quality = "good"
    if lines < 20:
        quality = "minimal"
    elif not headings:
        quality = "unstructured"
    elif len(headings) >= 3 and code_blocks >= 2:
        quality = "excellent"

    return {
        "present": True,
        "quality": quality,
        "lines": lines,
        "has_headings": bool(headings),
        "heading_count": len(headings),
        "has_code_blocks": code_blocks > 0,
        "has_api_docs": has_api,
        "has_diagrams": has_diagram,
    }


async def _fetch_metadata(client: httpx.AsyncClient, owner: str, repo: str) -> dict:
    resp = await client.get(f"/repos/{owner}/{repo}")
    if resp.status_code != 200:
        raise RuntimeError(f"Repository not found or inaccessible: {owner}/{repo} ({resp.status_code})")
    return resp.json()


async def _fetch_languages(client: httpx.AsyncClient, owner: str, repo: str) -> dict:
    resp = await client.get(f"/repos/{owner}/{repo}/languages")
    if resp.status_code != 200:
        return {}
    return resp.json()


async def _fetch_tree(client: httpx.AsyncClient, owner: str, repo: str, branch: str) -> list[str]:
    resp = await client.get(
        f"/repos/{owner}/{repo}/git/trees/{branch}",
        params={"recursive": "1"},
    )
    if resp.status_code != 200:
        logger.warning("Could not fetch tree for %s/%s:%s", owner, repo, branch)
        return []
    data = resp.json()
    return [item["path"] for item in data.get("tree", []) if item.get("type") in ("blob", "tree")]


async def _fetch_file(client: httpx.AsyncClient, owner: str, repo: str, path: str) -> str:
    resp = await client.get(f"/repos/{owner}/{repo}/contents/{path}")
    if resp.status_code != 200:
        return ""
    data = resp.json()
    content = data.get("content", "")
    encoding = data.get("encoding", "")
    if encoding == "base64" and content:
        try:
            return base64.b64decode(content).decode("utf-8", errors="replace")
        except Exception:
            return ""
    return content


async def _check_ci(client: httpx.AsyncClient, owner: str, repo: str) -> list[str]:
    resp = await client.get(f"/repos/{owner}/{repo}/actions/workflows")
    if resp.status_code != 200:
        return []
    data = resp.json()
    return [w["name"] for w in data.get("workflows", [])]


def _extract_ci_commands(ci_content: dict[str, str]) -> dict[str, list[str]]:
    """Extract build, test, and lint commands from CI workflow YAML."""
    commands: dict[str, list[str]] = {"build": [], "test": [], "lint": [], "install": [], "other": []}
    seen: set[str] = set()

    run_re = re.compile(r"^\s*-?\s*run:\s*[|>]?\s*(.+)$", re.MULTILINE)
    test_kw = re.compile(r"(?i)(pytest|go\s+test|npm\s+test|cargo\s+test|make\s+test|yarn\s+test|mvn\s+test|tox)")
    build_kw = re.compile(
        r"(?i)(go\s+build|npm\s+run\s+build|cargo\s+build|make\s+build|mvn\s+package|gradle\s+build|docker\s+build)"
    )
    lint_kw = re.compile(r"(?i)(lint|golangci|eslint|ruff|flake8|pylint|clippy|prettier|black|isort|mypy)")
    install_kw = re.compile(
        r"(?i)(pip\s+install|npm\s+(ci|install)|go\s+mod|cargo\s+fetch|yarn\s+install|poetry\s+install)"
    )

    for _path, content in ci_content.items():
        for m in run_re.finditer(content):
            cmd = m.group(1).strip().rstrip("|").strip()
            if not cmd or cmd in seen or len(cmd) > 200:
                continue
            seen.add(cmd)
            if test_kw.search(cmd):
                commands["test"].append(cmd)
            elif build_kw.search(cmd):
                commands["build"].append(cmd)
            elif lint_kw.search(cmd):
                commands["lint"].append(cmd)
            elif install_kw.search(cmd):
                commands["install"].append(cmd)

    return commands


def _extract_makefile_targets(makefile_content: str) -> list[str]:
    """Extract target names from a Makefile."""
    if not makefile_content:
        return []
    target_re = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_-]*):", re.MULTILINE)
    return sorted(set(target_re.findall(makefile_content)))


def _find_file_in_tree(tree: list[str], filename: str) -> str | None:
    """Find the best match for a filename in the tree (case-insensitive root match first)."""
    lower = filename.lower()
    for path in tree:
        if path.lower() == lower:
            return path
    for path in tree:
        if path.lower().endswith("/" + lower):
            return path
    return None
