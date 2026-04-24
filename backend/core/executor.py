from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from .config import get_settings


@lru_cache(maxsize=1)
def get_executor() -> ThreadPoolExecutor:
    settings = get_settings()
    return ThreadPoolExecutor(
        max_workers=max(1, settings.max_workers),
        thread_name_prefix="fbv1-worker",
    )
