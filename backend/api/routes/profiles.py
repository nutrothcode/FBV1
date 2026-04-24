from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from ...core.events import event_broker
from ...data import repositories
from ..schemas import ProfileCreateRequest, ProfileResponse, ProfileUpdateRequest

router = APIRouter(tags=["profiles"])


@router.get("/profiles", response_model=list[ProfileResponse])
def list_profiles() -> list[ProfileResponse]:
    return [
        ProfileResponse.model_validate(profile)
        for profile in repositories.list_profiles()
    ]


@router.get("/profiles/{profile_id}", response_model=ProfileResponse)
def get_profile(profile_id: str) -> ProfileResponse:
    profile = repositories.get_profile(profile_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile '{profile_id}' was not found.",
        )
    return ProfileResponse.model_validate(profile)


@router.post(
    "/profiles",
    response_model=ProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_profile(payload: ProfileCreateRequest) -> ProfileResponse:
    profile = repositories.create_profile(
        profile_name=payload.profile_name,
        session_label=payload.session_label,
        metadata=payload.metadata,
    )
    event_broker.publish({"type": "profile.created", "payload": profile})
    return ProfileResponse.model_validate(profile)


@router.put("/profiles/{profile_id}", response_model=ProfileResponse)
def update_profile(profile_id: str, payload: ProfileUpdateRequest) -> ProfileResponse:
    profile = repositories.update_profile(
        profile_id,
        profile_name=payload.profile_name,
        session_label=payload.session_label,
        metadata=payload.metadata,
        last_status=payload.last_status,
        health_status=payload.health_status,
        health_reason=payload.health_reason,
    )
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile '{profile_id}' was not found.",
        )
    event_broker.publish({"type": "profile.updated", "payload": profile})
    return ProfileResponse.model_validate(profile)


@router.delete("/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(profile_id: str) -> None:
    deleted = repositories.delete_profile(profile_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile '{profile_id}' was not found.",
        )
    event_broker.publish({"type": "profile.deleted", "payload": {"id": profile_id}})
