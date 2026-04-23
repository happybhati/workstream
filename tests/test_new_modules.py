"""Tests for response_validator, model_registry, claude_code_importer, and reports."""

from __future__ import annotations

import importlib
import json

import pytest


class TestResponseValidator:
    def test_clean_review_text_strips_fences(self):
        from response_validator import clean_review_text

        raw = "```json\n{}\n```"
        result = clean_review_text(raw)
        assert "```" not in result

    def test_clean_review_text_plain(self):
        from response_validator import clean_review_text

        result = clean_review_text("simple text")
        assert result == "simple text"

    def test_validate_review_valid_json(self):
        from response_validator import validate_review

        raw = json.dumps(
            {
                "summary": "Looks good",
                "comments": [{"file": "a.py", "line": 1, "body": "nice"}],
            }
        )
        result = validate_review(raw)
        assert "cleaned" in result
        assert result["cleaned"]["summary"] == "Looks good"
        assert len(result["cleaned"]["comments"]) == 1

    def test_validate_review_fenced_json(self):
        from response_validator import validate_review

        raw = '```json\n{"summary": "ok", "comments": []}\n```'
        result = validate_review(raw)
        assert result["cleaned"]["summary"] == "ok"

    def test_validate_review_garbage(self):
        from response_validator import validate_review

        result = validate_review("totally broken response with no json")
        assert "cleaned" in result
        assert len(result["warnings"]) > 0

    def test_validate_review_missing_summary(self):
        from response_validator import validate_review

        raw = json.dumps({"comments": []})
        result = validate_review(raw)
        assert result["cleaned"]["summary"] == "Review completed."

    def test_validate_review_with_preamble(self):
        from response_validator import validate_review

        raw = 'Sure! Here is my review.\n```json\n{"summary": "ok", "comments": []}\n```'
        result = validate_review(raw)
        assert result["cleaned"]["summary"] == "ok"


class TestModelRegistry:
    def test_load_defaults(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
        import config

        importlib.reload(config)
        from model_registry import _load_defaults

        defaults = _load_defaults()
        assert isinstance(defaults, dict)
        assert len(defaults) > 0

    def test_get_registry(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
        import config

        importlib.reload(config)
        import model_registry

        importlib.reload(model_registry)
        models = model_registry.get_registry()
        assert isinstance(models, dict)

    def test_get_model_cost_unknown(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
        import config

        importlib.reload(config)
        import model_registry

        importlib.reload(model_registry)
        cost = model_registry.get_model_cost("nonexistent-model-xyz")
        assert cost["input"] == 0.0
        assert cost["output"] == 0.0

    def test_get_model_cost_known(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
        import config

        importlib.reload(config)
        import model_registry

        importlib.reload(model_registry)
        models = model_registry.get_registry()
        if models:
            first_model = next(iter(models))
            cost = model_registry.get_model_cost(first_model)
            assert "input" in cost
            assert "output" in cost

    def test_list_models(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
        import config

        importlib.reload(config)
        import model_registry

        importlib.reload(model_registry)
        models = model_registry.list_models()
        assert isinstance(models, list)
        if models:
            assert "model_id" in models[0]

    def test_estimate_cost(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
        import config

        importlib.reload(config)
        import model_registry

        importlib.reload(model_registry)
        cost = model_registry.estimate_cost("unknown-model", 1000, 500)
        assert cost == 0.0


class TestClaudeCodeImporter:
    def test_estimate_cost_defaults(self):
        from claude_code_importer import _estimate_cost

        usage = {"input_tokens": 1000, "output_tokens": 500}
        cost = _estimate_cost(usage, model="unknown")
        assert cost > 0.0

    def test_estimate_cost_zero_tokens(self):
        from claude_code_importer import _estimate_cost

        cost = _estimate_cost({}, model="unknown")
        assert cost == 0.0

    def test_discover_sessions_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("claude_code_importer.PROJECTS_DIR", tmp_path / "projects")
        from claude_code_importer import discover_sessions

        sessions = discover_sessions()
        assert sessions == []

    def test_discover_sessions_with_data(self, tmp_path, monkeypatch):
        proj_dir = tmp_path / "projects" / "test-proj"
        proj_dir.mkdir(parents=True)
        session_file = proj_dir / "session_001.jsonl"
        session_file.write_text(
            json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 10, "output_tokens": 5}}}) + "\n"
        )
        monkeypatch.setattr("claude_code_importer.PROJECTS_DIR", tmp_path / "projects")
        from claude_code_importer import discover_sessions

        sessions = discover_sessions()
        assert isinstance(sessions, list)


class TestReports:
    @pytest.mark.asyncio
    async def test_generate_cost_report(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
        import config

        importlib.reload(config)
        import database

        importlib.reload(database)
        await database.init_db()

        from reports import generate_cost_report

        result = await generate_cost_report("30d")
        assert "markdown" in result
        assert "html" in result
        assert "AI Cost Report" in result["markdown"]

    @pytest.mark.asyncio
    async def test_generate_weekly_digest(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
        monkeypatch.setenv("GITHUB_PAT", "")
        import config

        importlib.reload(config)
        import database

        importlib.reload(database)
        await database.init_db()

        from reports import generate_weekly_digest

        result = await generate_weekly_digest()
        assert "markdown" in result
        assert "html" in result

    def test_md_to_html_basic(self):
        from reports import _md_to_html

        html = _md_to_html("# Hello\n\nWorld")
        assert "Hello" in html
        assert "World" in html

    def test_md_to_html_code_block(self):
        from reports import _md_to_html

        md = "```\ncode here\n```"
        html = _md_to_html(md)
        assert "code" in html

    def test_esc(self):
        from reports import _esc

        assert "&amp;" in _esc("&")
        assert "&lt;" in _esc("<")

    def test_inline(self):
        from reports import _inline

        result = _inline("**bold** and `code`")
        assert "<strong>" in result or "bold" in result
