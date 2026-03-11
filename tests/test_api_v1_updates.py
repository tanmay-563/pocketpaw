# Tests for API v1 updates router (Paw-to-Paw Phase 1).
# Created: 2026-03-11

import json
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pocketpaw.api.v1.updates import router


@pytest.fixture
def test_app():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return app


@pytest.fixture
def client(test_app):
    return TestClient(test_app)


class TestGetUpdateInfo:
    """Tests for GET /api/v1/updates."""

    @patch("pocketpaw.config.get_config_dir")
    @patch("pocketpaw.update_check.check_for_updates_full")
    def test_returns_update_info(self, mock_full, mock_config_dir, client, tmp_path):
        mock_config_dir.return_value = tmp_path
        mock_full.return_value = {
            "current": "0.4.8",
            "latest": "0.5.0",
            "update_available": True,
            "announcement": "",
            "urgency": "info",
            "announcement_url": "",
        }

        resp = client.get("/api/v1/updates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current"] == "0.4.8"
        assert data["latest"] == "0.5.0"
        assert data["update_available"] is True
        assert "announcement" in data
        assert "urgency" in data
        assert "announcement_url" in data

    @patch("pocketpaw.config.get_config_dir")
    @patch("pocketpaw.update_check.check_for_updates_full")
    def test_no_update_available(self, mock_full, mock_config_dir, client, tmp_path):
        mock_config_dir.return_value = tmp_path
        mock_full.return_value = {
            "current": "0.5.0",
            "latest": "0.5.0",
            "update_available": False,
            "announcement": "",
            "urgency": "info",
            "announcement_url": "",
        }

        resp = client.get("/api/v1/updates")
        assert resp.status_code == 200
        assert resp.json()["update_available"] is False

    @patch("pocketpaw.config.get_config_dir")
    @patch("pocketpaw.update_check.check_for_updates_full")
    def test_includes_announcement(self, mock_full, mock_config_dir, client, tmp_path):
        mock_config_dir.return_value = tmp_path
        mock_full.return_value = {
            "current": "0.4.8",
            "latest": "0.5.0",
            "update_available": True,
            "announcement": "Security patch!",
            "urgency": "critical",
            "announcement_url": "https://example.com/security",
        }

        resp = client.get("/api/v1/updates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["announcement"] == "Security patch!"
        assert data["urgency"] == "critical"
        assert data["announcement_url"] == "https://example.com/security"


class TestDismissUpdateBanner:
    """Tests for POST /api/v1/updates/dismiss."""

    @patch("pocketpaw.config.get_config_dir")
    def test_dismiss_records_version(self, mock_config_dir, client, tmp_path):
        mock_config_dir.return_value = tmp_path

        resp = client.post(
            "/api/v1/updates/dismiss",
            json={"version": "0.5.0"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Verify it was written to cache
        cache = json.loads((tmp_path / ".update_check").read_text())
        assert cache["last_seen_version"] == "0.5.0"

    @patch("pocketpaw.config.get_config_dir")
    def test_dismiss_empty_version_is_noop(self, mock_config_dir, client, tmp_path):
        mock_config_dir.return_value = tmp_path

        resp = client.post(
            "/api/v1/updates/dismiss",
            json={"version": ""},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        # No cache file created
        assert not (tmp_path / ".update_check").exists()
