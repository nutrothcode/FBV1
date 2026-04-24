from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from .db import get_session
from .models import JobRecord, ProfileSession


def _serialize(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _deserialize(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    return json.loads(value)


def _job_to_dict(job: JobRecord) -> dict[str, Any]:
    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "profile_id": job.profile_id,
        "input_payload": _deserialize(job.input_payload_json),
        "result_payload": _deserialize(job.result_payload_json),
        "error_message": job.error_message,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


def _profile_to_dict(profile: ProfileSession) -> dict[str, Any]:
    return {
        "id": profile.id,
        "profile_name": profile.profile_name,
        "session_label": profile.session_label,
        "metadata": _deserialize(profile.metadata_json),
        "last_status": profile.last_status,
        "health_status": profile.health_status,
        "health_reason": profile.health_reason,
        "last_checked_at": profile.last_checked_at,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


def create_job(job_type: str, profile_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    with get_session() as session:
        job = JobRecord(
            job_type=job_type,
            status="pending",
            profile_id=profile_id,
            input_payload_json=_serialize(payload),
            result_payload_json="{}",
        )
        session.add(job)
        session.flush()
        session.refresh(job)
        return _job_to_dict(job)


def get_job(job_id: str) -> dict[str, Any] | None:
    with get_session() as session:
        job = session.get(JobRecord, job_id)
        return None if job is None else _job_to_dict(job)


def list_jobs() -> list[dict[str, Any]]:
    with get_session() as session:
        jobs = session.query(JobRecord).order_by(JobRecord.created_at.desc()).all()
        return [_job_to_dict(job) for job in jobs]


def mark_job_running(job_id: str) -> None:
    now = datetime.now(UTC)
    with get_session() as session:
        job = session.get(JobRecord, job_id)
        if job is None:
            return
        job.status = "running"
        job.started_at = now
        job.updated_at = now


def mark_job_completed(job_id: str, result_payload: dict[str, Any]) -> None:
    now = datetime.now(UTC)
    with get_session() as session:
        job = session.get(JobRecord, job_id)
        if job is None:
            return
        job.status = "completed"
        job.result_payload_json = _serialize(result_payload)
        job.finished_at = now
        job.updated_at = now


def mark_job_failed(job_id: str, error_message: str) -> None:
    now = datetime.now(UTC)
    with get_session() as session:
        job = session.get(JobRecord, job_id)
        if job is None:
            return
        job.status = "failed"
        job.error_message = error_message
        job.finished_at = now
        job.updated_at = now


def mark_job_cancelled(job_id: str, error_message: str | None = None) -> None:
    now = datetime.now(UTC)
    with get_session() as session:
        job = session.get(JobRecord, job_id)
        if job is None:
            return
        job.status = "cancelled"
        job.error_message = error_message
        job.finished_at = now
        job.updated_at = now


def create_profile(
    profile_name: str,
    session_label: str | None,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    with get_session() as session:
        profile = ProfileSession(
            profile_name=profile_name,
            session_label=session_label,
            metadata_json=_serialize(metadata),
            last_status="new",
            health_status="unknown",
        )
        session.add(profile)
        session.flush()
        session.refresh(profile)
        return _profile_to_dict(profile)


def get_profile(profile_id: str) -> dict[str, Any] | None:
    with get_session() as session:
        profile = session.get(ProfileSession, profile_id)
        return None if profile is None else _profile_to_dict(profile)


def list_profiles() -> list[dict[str, Any]]:
    with get_session() as session:
        profiles = (
            session.query(ProfileSession)
            .order_by(ProfileSession.created_at.desc())
            .all()
        )
        return [_profile_to_dict(profile) for profile in profiles]


def update_profile_status(profile_id: str, status_value: str) -> None:
    with get_session() as session:
        profile = session.get(ProfileSession, profile_id)
        if profile is None:
            return
        profile.last_status = status_value
        profile.updated_at = datetime.now(UTC)


def update_profile_health(
    profile_id: str,
    health_status: str,
    health_reason: str | None,
) -> None:
    with get_session() as session:
        profile = session.get(ProfileSession, profile_id)
        if profile is None:
            return
        now = datetime.now(UTC)
        profile.health_status = health_status
        profile.health_reason = health_reason
        profile.last_checked_at = now
        profile.updated_at = now


def update_profile(
    profile_id: str,
    *,
    profile_name: str | None = None,
    session_label: str | None = None,
    metadata: dict[str, Any] | None = None,
    last_status: str | None = None,
    health_status: str | None = None,
    health_reason: str | None = None,
) -> dict[str, Any] | None:
    with get_session() as session:
        profile = session.get(ProfileSession, profile_id)
        if profile is None:
            return None

        if profile_name is not None:
            profile.profile_name = profile_name
        if session_label is not None:
            profile.session_label = session_label
        if metadata is not None:
            profile.metadata_json = _serialize(metadata)
        if last_status is not None:
            profile.last_status = last_status
        if health_status is not None:
            profile.health_status = health_status
            profile.last_checked_at = datetime.now(UTC)
        if health_reason is not None or health_status is not None:
            profile.health_reason = health_reason

        profile.updated_at = datetime.now(UTC)
        session.flush()
        session.refresh(profile)
        return _profile_to_dict(profile)


def delete_profile(profile_id: str) -> bool:
    with get_session() as session:
        profile = session.get(ProfileSession, profile_id)
        if profile is None:
            return False
        session.delete(profile)
        return True
