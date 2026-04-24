from __future__ import annotations

from typing import Any


def run(profile_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    session_label = str(payload.get("session_label") or "default-session")
    return {
        "message": "Login/session preparation job completed.",
        "profile_id": profile_id,
        "session_label": session_label,
        "next_step": "Attach an approved identity provider or official API flow.",
    }
