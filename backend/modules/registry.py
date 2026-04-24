from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import account_care, checker, content_manager, login_manager


JobHandler = Callable[[str | None, dict[str, Any]], dict[str, Any]]


HANDLERS: dict[str, JobHandler] = {
    "login_manager": login_manager.run,
    "content_manager": content_manager.run,
    "account_care": account_care.run,
    "checker": checker.run,
}


def get_job_handler(job_type: str) -> JobHandler:
    try:
        return HANDLERS[job_type]
    except KeyError as error:
        raise ValueError(f"Unsupported job type: {job_type}") from error
