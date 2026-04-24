from __future__ import annotations

from concurrent.futures import Future
from threading import Lock

from ..api.schemas import JobCreateRequest
from ..api.schemas import StartAllCheckersRequest
from ..core.events import event_broker
from ..core.executor import get_executor
from ..data import repositories
from .jobs import run_job


class QueueService:
    def __init__(self) -> None:
        self._futures: dict[str, Future[None]] = {}
        self._lock = Lock()

    def submit_job(self, payload: JobCreateRequest) -> dict:
        job = repositories.create_job(
            job_type=payload.job_type,
            profile_id=payload.profile_id,
            payload=payload.payload,
        )
        future = get_executor().submit(
            run_job,
            job["id"],
            payload.job_type,
            payload.profile_id,
            payload.payload,
        )
        with self._lock:
            self._futures[job["id"]] = future
        return job

    def submit_checker_jobs_for_profiles(self, payload: StartAllCheckersRequest) -> int:
        profiles = repositories.list_profiles()
        selected_ids = set(payload.profile_ids)
        target_profiles = [
            profile for profile in profiles if not selected_ids or profile["id"] in selected_ids
        ]
        count = 0
        for profile in target_profiles:
            self.submit_job(
                JobCreateRequest(
                    job_type="checker",
                    profile_id=profile["id"],
                    payload={
                        "target_url": payload.target_url,
                        "review_keywords": payload.review_keywords,
                        "failure_keywords": payload.failure_keywords,
                        "live_status_codes": [200],
                        "review_status_codes": [401, 403],
                        "failed_status_codes": [404, 500, 503],
                    },
                )
            )
            count += 1
        return count

    def cancel_pending_jobs(self) -> int:
        cancelled = 0
        with self._lock:
            futures = list(self._futures.items())
        for job_id, future in futures:
            if not future.cancel():
                continue
            repositories.mark_job_cancelled(job_id, "Cancelled before execution.")
            event_broker.publish(
                {
                    "type": "job.updated",
                    "payload": {
                        "id": job_id,
                        "status": "cancelled",
                        "error_message": "Cancelled before execution.",
                    },
                }
            )
            cancelled += 1
        return cancelled


queue_service = QueueService()
