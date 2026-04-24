from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from ...data import repositories
from ...core.events import event_broker
from ...workers.queue import queue_service
from ..schemas import (
    JobCreateRequest,
    JobResponse,
    QueueControlResponse,
    StartAllCheckersRequest,
)

router = APIRouter(tags=["jobs"])


@router.get("/jobs", response_model=list[JobResponse])
def list_jobs() -> list[JobResponse]:
    return [JobResponse.model_validate(job) for job in repositories.list_jobs()]


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str) -> JobResponse:
    job = repositories.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' was not found.",
        )
    return JobResponse.model_validate(job)


@router.post("/jobs", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def create_job(payload: JobCreateRequest) -> JobResponse:
    job = queue_service.submit_job(payload)
    event_broker.publish({"type": "job.created", "payload": job})
    return JobResponse.model_validate(job)


@router.post("/jobs/start-all", response_model=QueueControlResponse)
def start_all_jobs(payload: StartAllCheckersRequest) -> QueueControlResponse:
    count = queue_service.submit_checker_jobs_for_profiles(payload)
    return QueueControlResponse(
        message="Checker jobs submitted.",
        affected_jobs=count,
    )


@router.post("/jobs/stop-all", response_model=QueueControlResponse)
def stop_all_jobs() -> QueueControlResponse:
    count = queue_service.cancel_pending_jobs()
    return QueueControlResponse(
        message="Pending jobs cancelled.",
        affected_jobs=count,
    )
