"""Tests for update_check module.

Changes:
  - 2026-03-11: Added tests for Paw-to-Paw Phase 1: fetch_latest_json,
    check_for_updates_full, admin notification helpers, announcement in CLI notice.
  - 2026-02-18: Added TestStyledUpdateNotice, TestFetchReleaseNotes, TestVersionSeen.
  - 2026-02-16: Initial tests for PyPI version check with caching.
"""

import json
import time
from unittest.mock import patch

from pocketpaw.update_check import (
    ANNOUNCEMENT_CACHE_FILENAME,
    CACHE_FILENAME,
    CACHE_TTL,
    RELEASE_NOTES_CACHE_DIR,
    _parse_version,
    check_for_updates,
    check_for_updates_full,
    fetch_latest_json,
    fetch_release_notes,
    format_admin_update_message,
    get_last_notified_version,
    get_last_seen_version,
    mark_version_notified,
    mark_version_seen,
    print_styled_update_notice,
    print_update_notice,
)


class TestParseVersion:
    def test_simple(self):
        assert _parse_version("0.4.1") == (0, 4, 1)

    def test_major(self):
        assert _parse_version("1.0.0") == (1, 0, 0)

    def test_two_digit(self):
        assert _parse_version("0.12.3") == (0, 12, 3)


class TestCheckForUpdates:
    def test_returns_no_update_when_current(self, tmp_path):
        """When PyPI returns same version, update_available is False."""
        pypi_response = json.dumps({"info": {"version": "0.4.1"}}).encode()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__ = lambda s: s
            mock_urlopen.return_value.__exit__ = lambda s, *a: None
            mock_urlopen.return_value.read.return_value = pypi_response

            result = check_for_updates("0.4.1", tmp_path)

        assert result is not None
        assert result["current"] == "0.4.1"
        assert result["latest"] == "0.4.1"
        assert result["update_available"] is False

    def test_returns_update_when_behind(self, tmp_path):
        """When PyPI has newer version, update_available is True."""
        pypi_response = json.dumps({"info": {"version": "0.5.0"}}).encode()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__ = lambda s: s
            mock_urlopen.return_value.__exit__ = lambda s, *a: None
            mock_urlopen.return_value.read.return_value = pypi_response

            result = check_for_updates("0.4.1", tmp_path)

        assert result is not None
        assert result["update_available"] is True
        assert result["latest"] == "0.5.0"

    def test_writes_cache_file(self, tmp_path):
        """After a successful check, cache file should exist."""
        pypi_response = json.dumps({"info": {"version": "0.4.1"}}).encode()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__ = lambda s: s
            mock_urlopen.return_value.__exit__ = lambda s, *a: None
            mock_urlopen.return_value.read.return_value = pypi_response

            check_for_updates("0.4.1", tmp_path)

        cache_file = tmp_path / CACHE_FILENAME
        assert cache_file.exists()
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
        assert "ts" in cache
        assert cache["latest"] == "0.4.1"

    def test_uses_fresh_cache(self, tmp_path):
        """When cache is fresh, doesn't hit PyPI."""
        cache_file = tmp_path / CACHE_FILENAME
        cache_file.write_text(json.dumps({"ts": time.time(), "latest": "0.5.0"}))

        # No mock needed — if it tries to hit PyPI it would fail
        result = check_for_updates("0.4.1", tmp_path)

        assert result is not None
        assert result["update_available"] is True
        assert result["latest"] == "0.5.0"

    def test_ignores_stale_cache(self, tmp_path):
        """When cache is older than TTL, re-fetches from PyPI."""
        cache_file = tmp_path / CACHE_FILENAME
        stale_ts = time.time() - CACHE_TTL - 100
        cache_file.write_text(json.dumps({"ts": stale_ts, "latest": "0.3.0"}))

        pypi_response = json.dumps({"info": {"version": "0.4.1"}}).encode()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__ = lambda s: s
            mock_urlopen.return_value.__exit__ = lambda s, *a: None
            mock_urlopen.return_value.read.return_value = pypi_response

            result = check_for_updates("0.4.1", tmp_path)

        assert result is not None
        assert result["latest"] == "0.4.1"  # Updated from stale 0.3.0

    def test_returns_none_on_network_error(self, tmp_path):
        """Network errors return None, never raise."""
        with patch("urllib.request.urlopen", side_effect=Exception("no network")):
            result = check_for_updates("0.4.1", tmp_path)

        assert result is None

    def test_handles_corrupted_cache(self, tmp_path):
        """Corrupted cache file doesn't crash, re-fetches."""
        cache_file = tmp_path / CACHE_FILENAME
        cache_file.write_text("not json{{{")

        pypi_response = json.dumps({"info": {"version": "0.4.1"}}).encode()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__ = lambda s: s
            mock_urlopen.return_value.__exit__ = lambda s, *a: None
            mock_urlopen.return_value.read.return_value = pypi_response

            result = check_for_updates("0.4.1", tmp_path)

        assert result is not None
        assert result["current"] == "0.4.1"


class TestPrintUpdateNotice:
    def test_prints_notice(self, capsys):
        """Legacy print_update_notice delegates to styled version (suppressed in non-TTY tests)."""
        # In test env, stderr is not a TTY so styled notice is suppressed.
        # Just verify it doesn't crash.
        print_update_notice({"current": "0.4.0", "latest": "0.4.1"})


class TestStyledUpdateNotice:
    def test_outputs_to_stderr_when_tty(self, capsys):
        """Styled notice writes box-drawing chars to stderr when TTY is available."""
        info = {"current": "0.4.1", "latest": "0.5.0"}
        with (
            patch("sys.stderr.isatty", return_value=True),
            patch("pocketpaw.update_check.os.environ.get", return_value=None),
        ):
            print_styled_update_notice(info)
        captured = capsys.readouterr()
        assert "\u250c" in captured.err  # box-drawing top-left corner
        assert "\u2514" in captured.err  # box-drawing bottom-left corner
        assert "0.5.0" in captured.err
        assert "0.4.1" in captured.err
        assert "pip install --upgrade pocketpaw" in captured.err

    def test_suppressed_in_ci(self, capsys):
        """No output when CI env var is set."""
        info = {"current": "0.4.1", "latest": "0.5.0"}
        with (
            patch("sys.stderr.isatty", return_value=True),
            patch.dict("os.environ", {"CI": "true"}, clear=False),
        ):
            print_styled_update_notice(info)
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_suppressed_when_not_tty(self, capsys):
        """No output when stderr is not a TTY."""
        info = {"current": "0.4.1", "latest": "0.5.0"}
        with patch("sys.stderr.isatty", return_value=False):
            print_styled_update_notice(info)
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_suppressed_by_env_var(self, capsys):
        """No output when POCKETPAW_NO_UPDATE_CHECK is set."""
        info = {"current": "0.4.1", "latest": "0.5.0"}
        with (
            patch("sys.stderr.isatty", return_value=True),
            patch.dict("os.environ", {"POCKETPAW_NO_UPDATE_CHECK": "1"}, clear=False),
        ):
            print_styled_update_notice(info)
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_contains_box_drawing_chars(self, capsys):
        """Output includes all four box corners."""
        info = {"current": "0.4.1", "latest": "0.5.0"}
        with (
            patch("sys.stderr.isatty", return_value=True),
            patch("pocketpaw.update_check.os.environ.get", return_value=None),
        ):
            print_styled_update_notice(info)
        captured = capsys.readouterr()
        for char in ["\u250c", "\u2510", "\u2514", "\u2518", "\u2500"]:
            assert char in captured.err


class TestFetchReleaseNotes:
    def test_fetch_and_cache(self, tmp_path):
        """Fetches from GitHub and caches the result."""
        release_data = json.dumps(
            {
                "body": "## Changes\n- Fixed stuff",
                "html_url": "https://github.com/pocketpaw/pocketpaw/releases/tag/v0.4.2",
                "published_at": "2026-02-16T00:00:00Z",
                "name": "v0.4.2",
            }
        ).encode()

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__ = lambda s: s
            mock_urlopen.return_value.__exit__ = lambda s, *a: None
            mock_urlopen.return_value.read.return_value = release_data

            result = fetch_release_notes("0.4.2", tmp_path)

        assert result is not None
        assert result["version"] == "0.4.2"
        assert "Fixed stuff" in result["body"]
        assert result["name"] == "v0.4.2"

        # Verify cache was written
        cache_file = tmp_path / RELEASE_NOTES_CACHE_DIR / "v0.4.2.json"
        assert cache_file.exists()

    def test_uses_cached_notes(self, tmp_path):
        """Returns cached notes without hitting GitHub."""
        cache_dir = tmp_path / RELEASE_NOTES_CACHE_DIR
        cache_dir.mkdir(parents=True)
        cached = {
            "ts": time.time(),
            "data": {
                "version": "0.4.2",
                "body": "cached notes",
                "html_url": "https://example.com",
                "published_at": "2026-02-16T00:00:00Z",
                "name": "v0.4.2",
            },
        }
        (cache_dir / "v0.4.2.json").write_text(json.dumps(cached))

        # No mock — would fail if it tried to fetch
        result = fetch_release_notes("0.4.2", tmp_path)

        assert result is not None
        assert result["body"] == "cached notes"

    def test_returns_none_on_network_error(self, tmp_path):
        """Network errors return None, never raise."""
        with patch("urllib.request.urlopen", side_effect=Exception("no network")):
            result = fetch_release_notes("0.4.2", tmp_path)
        assert result is None


class TestVersionSeen:
    def test_initial_none(self, tmp_path):
        """When no cache exists, returns None."""
        assert get_last_seen_version(tmp_path) is None

    def test_mark_and_get(self, tmp_path):
        """Mark a version as seen, then retrieve it."""
        mark_version_seen("0.4.2", tmp_path)
        assert get_last_seen_version(tmp_path) == "0.4.2"

    def test_preserves_existing_cache(self, tmp_path):
        """Marking version seen doesn't destroy existing cache fields."""
        cache_file = tmp_path / CACHE_FILENAME
        cache_file.write_text(json.dumps({"ts": 12345, "latest": "0.5.0"}))

        mark_version_seen("0.4.2", tmp_path)

        cache = json.loads(cache_file.read_text(encoding="utf-8"))
        assert cache["ts"] == 12345
        assert cache["latest"] == "0.5.0"
        assert cache["last_seen_version"] == "0.4.2"

    def test_updates_existing_seen(self, tmp_path):
        """Updating last_seen_version overwrites old value."""
        mark_version_seen("0.4.1", tmp_path)
        mark_version_seen("0.4.2", tmp_path)
        assert get_last_seen_version(tmp_path) == "0.4.2"


# ---------------------------------------------------------------------------
# Paw-to-Paw Phase 1 tests
# ---------------------------------------------------------------------------


class TestFetchLatestJson:
    def test_fetch_and_cache(self, tmp_path):
        """Fetches latest.json and caches the result."""
        payload = json.dumps(
            {
                "version": "0.5.0",
                "announcement": "New feature!",
                "urgency": "info",
                "url": "https://example.com",
            }
        ).encode()

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__ = lambda s: s
            mock_urlopen.return_value.__exit__ = lambda s, *a: None
            mock_urlopen.return_value.read.return_value = payload

            result = fetch_latest_json(tmp_path)

        assert result is not None
        assert result["version"] == "0.5.0"
        assert result["announcement"] == "New feature!"
        assert result["urgency"] == "info"
        assert result["url"] == "https://example.com"

        # Cache written
        cache_file = tmp_path / ANNOUNCEMENT_CACHE_FILENAME
        assert cache_file.exists()

    def test_uses_cached_data(self, tmp_path):
        """Returns cached data without fetching."""
        cache_file = tmp_path / ANNOUNCEMENT_CACHE_FILENAME
        cached = {
            "ts": time.time(),
            "data": {
                "version": "0.5.0",
                "announcement": "cached msg",
                "urgency": "warning",
                "url": "",
            },
        }
        cache_file.write_text(json.dumps(cached))

        result = fetch_latest_json(tmp_path)
        assert result is not None
        assert result["announcement"] == "cached msg"
        assert result["urgency"] == "warning"

    def test_returns_none_on_network_error(self, tmp_path):
        """Network errors return None."""
        with patch("urllib.request.urlopen", side_effect=Exception("no network")):
            result = fetch_latest_json(tmp_path)
        assert result is None

    def test_returns_none_on_missing_version_field(self, tmp_path):
        """Rejects payloads without a version field."""
        payload = json.dumps({"announcement": "hello"}).encode()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__ = lambda s: s
            mock_urlopen.return_value.__exit__ = lambda s, *a: None
            mock_urlopen.return_value.read.return_value = payload

            result = fetch_latest_json(tmp_path)
        assert result is None

    def test_defaults_missing_optional_fields(self, tmp_path):
        """Optional fields default to empty strings."""
        payload = json.dumps({"version": "0.5.0"}).encode()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__ = lambda s: s
            mock_urlopen.return_value.__exit__ = lambda s, *a: None
            mock_urlopen.return_value.read.return_value = payload

            result = fetch_latest_json(tmp_path)

        assert result is not None
        assert result["announcement"] == ""
        assert result["urgency"] == "info"
        assert result["url"] == ""


class TestCheckForUpdatesFull:
    def test_merges_pypi_and_latest_json(self, tmp_path):
        """Combines PyPI version info with latest.json announcements."""
        # Seed PyPI cache
        cache_file = tmp_path / CACHE_FILENAME
        cache_file.write_text(json.dumps({"ts": time.time(), "latest": "0.5.0"}))

        # Seed announcement cache
        ann_cache = tmp_path / ANNOUNCEMENT_CACHE_FILENAME
        ann_cache.write_text(
            json.dumps(
                {
                    "ts": time.time(),
                    "data": {
                        "version": "0.5.0",
                        "announcement": "Big update!",
                        "urgency": "warning",
                        "url": "https://example.com/update",
                    },
                }
            )
        )

        result = check_for_updates_full("0.4.8", tmp_path)

        assert result["current"] == "0.4.8"
        assert result["latest"] == "0.5.0"
        assert result["update_available"] is True
        assert result["announcement"] == "Big update!"
        assert result["urgency"] == "warning"
        assert result["announcement_url"] == "https://example.com/update"

    def test_latest_json_version_takes_precedence(self, tmp_path):
        """latest.json version overrides PyPI if newer."""
        # PyPI says 0.5.0
        cache_file = tmp_path / CACHE_FILENAME
        cache_file.write_text(json.dumps({"ts": time.time(), "latest": "0.5.0"}))

        # latest.json says 0.5.1
        ann_cache = tmp_path / ANNOUNCEMENT_CACHE_FILENAME
        ann_cache.write_text(
            json.dumps(
                {
                    "ts": time.time(),
                    "data": {"version": "0.5.1", "announcement": "", "urgency": "info", "url": ""},
                }
            )
        )

        result = check_for_updates_full("0.4.8", tmp_path)
        assert result["latest"] == "0.5.1"

    def test_works_without_latest_json(self, tmp_path):
        """Falls back gracefully when latest.json is unavailable."""
        cache_file = tmp_path / CACHE_FILENAME
        cache_file.write_text(json.dumps({"ts": time.time(), "latest": "0.5.0"}))

        result = check_for_updates_full("0.4.8", tmp_path)

        assert result["update_available"] is True
        assert result["announcement"] == ""
        assert result["urgency"] == "info"
        assert result["announcement_url"] == ""

    def test_announcement_only_no_update(self, tmp_path):
        """Announcement can exist even when version is current."""
        cache_file = tmp_path / CACHE_FILENAME
        cache_file.write_text(json.dumps({"ts": time.time(), "latest": "0.4.8"}))

        ann_cache = tmp_path / ANNOUNCEMENT_CACHE_FILENAME
        ann_cache.write_text(
            json.dumps(
                {
                    "ts": time.time(),
                    "data": {
                        "version": "0.4.8",
                        "announcement": "Maintenance window tonight",
                        "urgency": "info",
                        "url": "",
                    },
                }
            )
        )

        result = check_for_updates_full("0.4.8", tmp_path)
        assert result["update_available"] is False
        assert result["announcement"] == "Maintenance window tonight"


class TestVersionNotified:
    def test_initial_none(self, tmp_path):
        """No notification record initially."""
        assert get_last_notified_version(tmp_path) is None

    def test_mark_and_get(self, tmp_path):
        """Mark a version as notified, then retrieve it."""
        mark_version_notified("0.5.0", tmp_path)
        assert get_last_notified_version(tmp_path) == "0.5.0"

    def test_preserves_existing_cache(self, tmp_path):
        """Notification record doesn't destroy other cache fields."""
        cache_file = tmp_path / CACHE_FILENAME
        cache_file.write_text(json.dumps({"ts": 12345, "latest": "0.5.0"}))

        mark_version_notified("0.5.0", tmp_path)

        cache = json.loads(cache_file.read_text(encoding="utf-8"))
        assert cache["ts"] == 12345
        assert cache["latest"] == "0.5.0"
        assert cache["last_notified_version"] == "0.5.0"

    def test_updates_existing_notified(self, tmp_path):
        """Updating last_notified_version overwrites old value."""
        mark_version_notified("0.4.9", tmp_path)
        mark_version_notified("0.5.0", tmp_path)
        assert get_last_notified_version(tmp_path) == "0.5.0"


class TestFormatAdminUpdateMessage:
    def test_basic_message(self):
        info = {"current": "0.4.8", "latest": "0.5.0"}
        msg = format_admin_update_message(info)
        assert "v0.4.8 -> v0.5.0" in msg
        assert "pip install --upgrade pocketpaw" in msg
        assert "Release notes" in msg

    def test_includes_announcement(self):
        info = {
            "current": "0.4.8",
            "latest": "0.5.0",
            "announcement": "Critical security fix",
        }
        msg = format_admin_update_message(info)
        assert "Critical security fix" in msg

    def test_no_announcement(self):
        info = {"current": "0.4.8", "latest": "0.5.0", "announcement": ""}
        msg = format_admin_update_message(info)
        assert "v0.4.8 -> v0.5.0" in msg


class TestStyledNoticeWithAnnouncement:
    def test_includes_announcement_text(self, capsys):
        """Announcement text is shown in the CLI box."""
        info = {
            "current": "0.4.8",
            "latest": "0.5.0",
            "announcement": "Bug fixes for memory hang",
        }
        with (
            patch("sys.stderr.isatty", return_value=True),
            patch("pocketpaw.update_check.os.environ.get", return_value=None),
        ):
            print_styled_update_notice(info)
        captured = capsys.readouterr()
        assert "Bug fixes for memory hang" in captured.err
        assert "0.5.0" in captured.err
