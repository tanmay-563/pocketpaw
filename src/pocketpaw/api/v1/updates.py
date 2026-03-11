# Updates router — version check, announcements, banner dismiss (Paw-to-Paw Phase 1).
# Created: 2026-03-11

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from pocketpaw.api.v1.schemas.common import OkResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Updates"])


@router.get("/updates")
async def get_update_info():
    """Return current version, update availability, and announcements.

    Combines PyPI version check (24h cache) with latest.json announcements
    (1h cache) into a single response. Fields:

    - ``current`` / ``latest`` / ``update_available`` — version info
    - ``announcement`` / ``urgency`` / ``announcement_url`` — from latest.json
    """
    from importlib.metadata import version as get_version

    from pocketpaw.config import get_config_dir
    from pocketpaw.update_check import check_for_updates_full

    current = get_version("pocketpaw")
    return check_for_updates_full(current, get_config_dir())


@router.post("/updates/dismiss", response_model=OkResponse)
async def dismiss_update_banner(request: Request):
    """Record that the user dismissed the update banner for a specific version.

    Expects JSON body: ``{"version": "0.5.0"}``
    """
    from pocketpaw.config import get_config_dir
    from pocketpaw.update_check import mark_version_seen

    body = await request.json()
    version = body.get("version", "")
    if version:
        mark_version_seen(version, get_config_dir())
    return OkResponse()
