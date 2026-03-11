"""Startup version check against PyPI + latest.json announcements + release notes.

Changes:
  - 2026-03-11: Phase 1 Paw-to-Paw: added latest.json announcement fetching, admin DM
    notification, and dashboard banner support (issue #573).
  - 2026-02-18: Added styled CLI update box, release notes fetching, version seen tracking.
  - 2026-02-16: Initial implementation. Checks PyPI daily, caches result, prints update notice.

Checks once per 24 hours whether a newer version of pocketpaw exists on PyPI,
and fetches announcements from a hosted latest.json endpoint.
Cache stored in ~/.pocketpaw/.update_check so the result is shared between
CLI launches and the dashboard API.
"""

import json
import logging
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

PYPI_URL = "https://pypi.org/pypi/pocketpaw/json"
LATEST_JSON_URL = "https://pocketpaw.github.io/pocketpaw/latest.json"
CACHE_FILENAME = ".update_check"
CACHE_TTL = 86400  # 24 hours
ANNOUNCEMENT_CACHE_FILENAME = ".announcement_cache"
ANNOUNCEMENT_CACHE_TTL = 3600  # 1 hour — announcements refresh more often
REQUEST_TIMEOUT = 2  # seconds

RELEASE_NOTES_CACHE_DIR = ".release_notes_cache"
RELEASE_NOTES_TTL = 3600  # 1 hour
GITHUB_API_URL = "https://api.github.com/repos/pocketpaw/pocketpaw/releases/tags/v{version}"


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse '0.4.1' into (0, 4, 1).

    Handles pre-release suffixes like '0.4.1rc1' by stripping non-numeric parts.
    """
    parts = []
    for segment in v.strip().split("."):
        num = re.match(r"\d+", segment)
        parts.append(int(num.group()) if num else 0)
    return tuple(parts)


def check_for_updates(current_version: str, config_dir: Path) -> dict | None:
    """Check PyPI for a newer version. Returns version info dict or None on error.

    Uses a daily cache file to avoid hitting PyPI on every launch.
    Never raises — all errors are caught and logged at debug level.
    """
    try:
        cache_file = config_dir / CACHE_FILENAME
        now = time.time()

        # Try cache first
        if cache_file.exists():
            try:
                cache = json.loads(cache_file.read_text())
                if now - cache.get("ts", 0) < CACHE_TTL:
                    latest = cache.get("latest", current_version)
                    return {
                        "current": current_version,
                        "latest": latest,
                        "update_available": _parse_version(latest)
                        > _parse_version(current_version),
                    }
            except (json.JSONDecodeError, ValueError):
                pass  # Corrupted cache, re-fetch

        # Fetch from PyPI
        req = urllib.request.Request(PYPI_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read())
        latest = data["info"]["version"]

        # Write cache
        config_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({"ts": now, "latest": latest}))

        return {
            "current": current_version,
            "latest": latest,
            "update_available": _parse_version(latest) > _parse_version(current_version),
        }
    except Exception:
        logger.debug("Update check failed (network or parse error)", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# latest.json announcement fetching (Paw-to-Paw Phase 1)
# ---------------------------------------------------------------------------


def fetch_latest_json(config_dir: Path) -> dict | None:
    """Fetch the hosted latest.json for version + announcements.

    Expected schema::

        {
          "version": "0.4.9",
          "announcement": "Optional message to display to all users",
          "urgency": "info",        // "info" | "warning" | "critical"
          "url": "https://..."      // optional link for more details
        }

    Uses a 1-hour cache. Returns the parsed dict or None on error.
    Never raises.
    """
    try:
        cache_file = config_dir / ANNOUNCEMENT_CACHE_FILENAME
        now = time.time()

        # Try cache first
        if cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text())
                if now - cached.get("ts", 0) < ANNOUNCEMENT_CACHE_TTL:
                    return cached.get("data")
            except (json.JSONDecodeError, ValueError):
                pass

        url = os.environ.get("POCKETPAW_LATEST_JSON_URL", LATEST_JSON_URL)
        req = urllib.request.Request(url, headers={"User-Agent": "pocketpaw"})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read())

        # Validate minimum fields
        if not isinstance(data, dict) or "version" not in data:
            logger.debug("latest.json missing 'version' field")
            return None

        result = {
            "version": data["version"],
            "announcement": data.get("announcement", ""),
            "urgency": data.get("urgency", "info"),
            "url": data.get("url", ""),
        }

        # Write cache
        config_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({"ts": now, "data": result}))

        return result
    except Exception:
        logger.debug("Failed to fetch latest.json", exc_info=True)
        return None


def check_for_updates_full(current_version: str, config_dir: Path) -> dict:
    """Combined update check: PyPI version + latest.json announcements.

    Returns a dict with:
      - current, latest, update_available (from PyPI check)
      - announcement, urgency, announcement_url (from latest.json)

    Always returns a dict (never None). Errors in either source are isolated.
    """
    # Base version info from PyPI
    pypi_info = check_for_updates(current_version, config_dir)
    result = pypi_info or {
        "current": current_version,
        "latest": current_version,
        "update_available": False,
    }

    # Merge latest.json announcement data
    latest_json = fetch_latest_json(config_dir)
    if latest_json:
        # latest.json version takes precedence if newer than PyPI
        lj_version = latest_json["version"]
        if _parse_version(lj_version) > _parse_version(result["latest"]):
            result["latest"] = lj_version
            result["update_available"] = _parse_version(lj_version) > _parse_version(
                current_version
            )

        result["announcement"] = latest_json.get("announcement", "")
        result["urgency"] = latest_json.get("urgency", "info")
        result["announcement_url"] = latest_json.get("url", "")
    else:
        result["announcement"] = ""
        result["urgency"] = "info"
        result["announcement_url"] = ""

    return result


# ---------------------------------------------------------------------------
# CLI styled update notice
# ---------------------------------------------------------------------------


def _should_suppress_notice() -> bool:
    """Check if the update notice should be suppressed."""
    if os.environ.get("POCKETPAW_NO_UPDATE_CHECK"):
        return True
    if os.environ.get("CI"):
        return True
    if not sys.stderr.isatty():
        return True
    return False


def print_styled_update_notice(info: dict) -> None:
    """Print a styled, can't-miss update box to stderr.

    Uses box-drawing characters, ANSI colors, and writes to stderr so it
    doesn't pollute piped output. Auto-suppressed in CI, non-TTY, or when
    POCKETPAW_NO_UPDATE_CHECK is set.

    Supports announcement text from latest.json (Paw-to-Paw Phase 1).
    """
    if _should_suppress_notice():
        return

    current = info["current"]
    latest = info["latest"]
    announcement = info.get("announcement", "")

    # ANSI color codes
    YELLOW = "\033[33m"
    GREEN = "\033[32m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    CYAN = "\033[36m"
    RESET = "\033[0m"

    changelog_url = "github.com/pocketpaw/pocketpaw/releases"
    upgrade_cmd = "pip install --upgrade pocketpaw"

    # Build the content lines (without borders) to measure width
    title_line = (
        f"   {BOLD}Update available!{RESET}  {current} {YELLOW}\u2192{RESET} {GREEN}{latest}{RESET}"
    )
    changelog_line = f"   {DIM}Changelog:{RESET} {changelog_url}"
    upgrade_line = f"   {DIM}Run:{RESET}       {upgrade_cmd}"

    # Fixed box width (60 chars inner)
    box_width = 60
    border_h = "\u2500" * box_width
    empty_inner = " " * box_width

    lines = [
        f"{YELLOW}\u250c{border_h}\u2510{RESET}",
        f"{YELLOW}\u2502{RESET}{empty_inner}{YELLOW}\u2502{RESET}",
        f"{YELLOW}\u2502{RESET}{title_line}{' ' * 6}{YELLOW}\u2502{RESET}",
        f"{YELLOW}\u2502{RESET}{empty_inner}{YELLOW}\u2502{RESET}",
        f"{YELLOW}\u2502{RESET}{changelog_line}{' ' * (box_width - 52)}{YELLOW}\u2502{RESET}",
        f"{YELLOW}\u2502{RESET}{upgrade_line}{' ' * (box_width - 46)}{YELLOW}\u2502{RESET}",
    ]

    # Add announcement line if present
    if announcement:
        lines.append(f"{YELLOW}\u2502{RESET}{empty_inner}{YELLOW}\u2502{RESET}")
        # Wrap announcement to fit in box (max ~54 chars per line)
        max_text_width = box_width - 6  # 3 indent + 3 padding
        for i in range(0, len(announcement), max_text_width):
            chunk = announcement[i : i + max_text_width]
            padded = f"   {CYAN}{chunk}{RESET}"
            pad_right = box_width - len(chunk) - 3
            lines.append(f"{YELLOW}\u2502{RESET}{padded}{' ' * pad_right}{YELLOW}\u2502{RESET}")

    lines.extend(
        [
            f"{YELLOW}\u2502{RESET}{empty_inner}{YELLOW}\u2502{RESET}",
            f"{YELLOW}\u2514{border_h}\u2518{RESET}",
        ]
    )

    sys.stderr.write("\n" + "\n".join(lines) + "\n\n")


def print_update_notice(info: dict) -> None:
    """Deprecated: use print_styled_update_notice instead.

    Delegates to styled version for backward compatibility.
    """
    print_styled_update_notice(info)


# ---------------------------------------------------------------------------
# Release notes fetching + version seen tracking
# ---------------------------------------------------------------------------


def fetch_release_notes(version: str, config_dir: Path) -> dict | None:
    """Fetch release notes from GitHub for a specific version.

    Returns {version, body, html_url, published_at, name} or None on error.
    Uses per-version cache files with 1h TTL in config_dir/.release_notes_cache/.
    """
    try:
        cache_dir = config_dir / RELEASE_NOTES_CACHE_DIR
        cache_file = cache_dir / f"v{version}.json"
        now = time.time()

        # Try cache first
        if cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text())
                if now - cached.get("ts", 0) < RELEASE_NOTES_TTL:
                    return cached.get("data")
            except (json.JSONDecodeError, ValueError):
                pass

        # Fetch from GitHub
        url = GITHUB_API_URL.format(version=version)
        req = urllib.request.Request(
            url, headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "pocketpaw"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            release = json.loads(resp.read())

        data = {
            "version": version,
            "body": release.get("body", ""),
            "html_url": release.get("html_url", ""),
            "published_at": release.get("published_at", ""),
            "name": release.get("name", f"v{version}"),
        }

        # Write cache
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({"ts": now, "data": data}))

        return data
    except Exception:
        logger.debug("Failed to fetch release notes for v%s", version, exc_info=True)
        return None


def get_last_seen_version(config_dir: Path) -> str | None:
    """Read last_seen_version from the update check cache file."""
    try:
        cache_file = config_dir / CACHE_FILENAME
        if cache_file.exists():
            cache = json.loads(cache_file.read_text())
            return cache.get("last_seen_version")
    except (json.JSONDecodeError, ValueError, OSError):
        pass
    return None


def mark_version_seen(version: str, config_dir: Path) -> None:
    """Write last_seen_version into the update check cache file.

    Preserves existing cache fields (ts, latest) and adds/updates last_seen_version.
    """
    try:
        cache_file = config_dir / CACHE_FILENAME
        cache = {}
        if cache_file.exists():
            try:
                cache = json.loads(cache_file.read_text())
            except (json.JSONDecodeError, ValueError):
                pass
        cache["last_seen_version"] = version
        config_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache))
    except OSError:
        logger.debug("Failed to mark version %s as seen", version, exc_info=True)


def get_last_notified_version(config_dir: Path) -> str | None:
    """Read last_notified_version (for admin DM dedup) from the cache file."""
    try:
        cache_file = config_dir / CACHE_FILENAME
        if cache_file.exists():
            cache = json.loads(cache_file.read_text())
            return cache.get("last_notified_version")
    except (json.JSONDecodeError, ValueError, OSError):
        pass
    return None


def mark_version_notified(version: str, config_dir: Path) -> None:
    """Record that admin DM was sent for this version, preventing duplicate notifications."""
    try:
        cache_file = config_dir / CACHE_FILENAME
        cache = {}
        if cache_file.exists():
            try:
                cache = json.loads(cache_file.read_text())
            except (json.JSONDecodeError, ValueError):
                pass
        cache["last_notified_version"] = version
        config_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache))
    except OSError:
        logger.debug("Failed to mark version %s as notified", version, exc_info=True)


def format_admin_update_message(info: dict) -> str:
    """Format a concise update notification message for admin DMs."""
    current = info.get("current", "?")
    latest = info.get("latest", "?")
    announcement = info.get("announcement", "")

    lines = [f"PocketPaw update available: v{current} -> v{latest}"]

    if announcement:
        lines.append(f"\n{announcement}")

    lines.append("\nUpgrade: pip install --upgrade pocketpaw")
    lines.append("Release notes: github.com/pocketpaw/pocketpaw/releases")

    return "\n".join(lines)
