"""Tests for database.py — schema init, CRUD operations."""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def db_module(monkeypatch, tmp_path):
    """Reload database module with an isolated temp DB."""
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_file))

    import config

    importlib.reload(config)
    import database

    importlib.reload(database)
    return database


@pytest.mark.asyncio
async def test_init_db_creates_tables(db_module):
    """init_db should create all expected tables without error."""
    await db_module.init_db()

    import aiosqlite

    async with aiosqlite.connect(db_module.DB_PATH) as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in await cursor.fetchall()]

    assert "pull_requests" in tables
    assert "activities" in tables
    assert "jira_issues" in tables


@pytest.mark.asyncio
async def test_get_my_prs_empty(db_module):
    """get_my_prs should return empty list on a fresh DB."""
    await db_module.init_db()
    prs = await db_module.get_my_prs("testuser", "testuser")
    assert prs == []


@pytest.mark.asyncio
async def test_get_jira_tasks_empty(db_module):
    """get_jira_tasks should return empty list on a fresh DB."""
    await db_module.init_db()
    tasks = await db_module.get_jira_tasks()
    assert tasks == []


@pytest.mark.asyncio
async def test_get_recent_activities_empty(db_module):
    """get_recent_activities should return empty on a fresh DB."""
    await db_module.init_db()
    activities = await db_module.get_recent_activities(limit=10)
    assert activities == []
