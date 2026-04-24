from __future__ import annotations

import logging
import time
from typing import Any

from ..core.config import get_settings
from ..core.events import event_broker
from ..modules import get_job_handler
from ..data import repositories

logger = logging.getLogger(__name__)


def run_job(job_id: str, job_type: str, profile_id: str | None, payload: dict[str, Any]) -> None:
    settings = get_settings()
    repositories.mark_job_running(job_id)
    event_broker.publish(
        {
            "type": "job.updated",
            "payload": {"id": job_id, "status": "running", "job_type": job_type},
        }
    )
    if profile_id:
        repositories.update_profile_status(profile_id, "running")
        event_broker.publish(
            {
                "type": "profile.updated",
                "payload": {"id": profile_id, "last_status": "running"},
            }
        )

    try:
        time.sleep(max(0.0, settings.default_job_delay_seconds))
        handler = get_job_handler(job_type)
        result = handler(profile_id, payload)
        repositories.mark_job_completed(job_id, result)
        event_broker.publish(
            {
                "type": "job.updated",
                "payload": {
                    "id": job_id,
                    "status": "completed",
                    "job_type": job_type,
                    "result_payload": result,
                },
            }
        )
        if profile_id:
            repositories.update_profile_status(profile_id, "ready")
            if job_type == "checker":
                repositories.update_profile_health(
                    profile_id,
                    str(result.get("health_status") or "unknown"),
                    str(result["health_reason"]) if result.get("health_reason") else None,
                )
            event_broker.publish(
                {
                    "type": "profile.updated",
                    "payload": repositories.get_profile(profile_id),
                }
            )
    except Exception as error:
        logger.exception("Job %s failed", job_id)
        repositories.mark_job_failed(job_id, str(error))
        event_broker.publish(
            {
                "type": "job.updated",
                "payload": {
                    "id": job_id,
                    "status": "failed",
                    "job_type": job_type,
                    "error_message": str(error),
                },
            }
        )
        if profile_id:
            repositories.update_profile_status(profile_id, "error")
            if job_type == "checker":
                repositories.update_profile_health(profile_id, "failed", str(error))
            event_broker.publish(
                {
                    "type": "profile.updated",
                    "payload": repositories.get_profile(profile_id),
                }
            )
