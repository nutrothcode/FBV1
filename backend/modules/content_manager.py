from __future__ import annotations

from typing import Any


def run(profile_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    assets = payload.get("assets")
    asset_count = len(assets) if isinstance(assets, list) else 0
    return {
        "message": "Content preparation job completed.",
        "profile_id": profile_id,
        "asset_count": asset_count,
        "content_plan": payload.get("content_plan") or "draft",
    }
