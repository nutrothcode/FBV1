from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


JobType = Literal["login_manager", "content_manager", "account_care", "checker"]
JobStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
ProfileHealthStatus = Literal["unknown", "live", "review", "failed"]


class JobCreateRequest(BaseModel):
    job_type: JobType
    profile_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class StartAllCheckersRequest(BaseModel):
    target_url: str
    review_keywords: list[str] = Field(default_factory=list)
    failure_keywords: list[str] = Field(default_factory=list)
    profile_ids: list[str] = Field(default_factory=list)


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_type: str
    status: str
    profile_id: str | None
    input_payload: dict[str, Any]
    result_payload: dict[str, Any]
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ProfileCreateRequest(BaseModel):
    profile_name: str
    session_label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProfileUpdateRequest(BaseModel):
    profile_name: str | None = None
    session_label: str | None = None
    metadata: dict[str, Any] | None = None
    last_status: str | None = None
    health_status: ProfileHealthStatus | None = None
    health_reason: str | None = None


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    profile_name: str
    session_label: str | None
    metadata: dict[str, Any]
    last_status: str
    health_status: ProfileHealthStatus
    health_reason: str | None
    last_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class QueueControlResponse(BaseModel):
    message: str
    affected_jobs: int
