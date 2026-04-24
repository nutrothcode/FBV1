from __future__ import annotations

from http.client import HTTPResponse
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _to_int_set(values: Any, default: set[int]) -> set[int]:
    if not isinstance(values, list):
        return default
    parsed: set[int] = set()
    for value in values:
        try:
            parsed.add(int(value))
        except (TypeError, ValueError):
            continue
    return parsed or default


def _to_text_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _classify_from_response(
    status_code: int,
    body_text: str,
    live_status_codes: set[int],
    review_status_codes: set[int],
    failed_status_codes: set[int],
    review_keywords: list[str],
    failure_keywords: list[str],
) -> tuple[str, str]:
    lowered_body = body_text.lower()
    for keyword in failure_keywords:
        if keyword.lower() in lowered_body:
            return "failed", f"Matched failure keyword: {keyword}"

    for keyword in review_keywords:
        if keyword.lower() in lowered_body:
            return "review", f"Matched review keyword: {keyword}"

    if status_code in failed_status_codes:
        return "failed", f"Matched failed status code: {status_code}"
    if status_code in review_status_codes:
        return "review", f"Matched review status code: {status_code}"
    if status_code in live_status_codes:
        return "live", f"Matched live status code: {status_code}"

    return "unknown", f"No classification rule matched for status code {status_code}"


def run(profile_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    target_url = str(payload.get("target_url") or "").strip()
    if not target_url:
        raise ValueError("Checker job requires a 'target_url' in the payload.")

    method = str(payload.get("method") or "GET").upper()
    timeout_seconds = float(payload.get("timeout_seconds") or 10.0)
    live_status_codes = _to_int_set(payload.get("live_status_codes"), {200})
    review_status_codes = _to_int_set(payload.get("review_status_codes"), {401, 403})
    failed_status_codes = _to_int_set(payload.get("failed_status_codes"), {404, 410, 500, 503})
    review_keywords = _to_text_list(payload.get("review_keywords"))
    failure_keywords = _to_text_list(payload.get("failure_keywords"))

    request = Request(
        target_url,
        method=method,
        headers={
            "User-Agent": "FBV1-Checker/0.1",
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        },
    )

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response = response  # type: HTTPResponse
            status_code = int(response.getcode())
            body_bytes = response.read()
            body_text = body_bytes.decode("utf-8", errors="ignore")
    except HTTPError as error:
        status_code = int(error.code)
        body_text = error.read().decode("utf-8", errors="ignore")
    except URLError as error:
        return {
            "message": "Checker request could not reach the target.",
            "profile_id": profile_id,
            "target_url": target_url,
            "health_status": "failed",
            "health_reason": f"Network error: {error.reason}",
            "status_code": None,
        }

    health_status, health_reason = _classify_from_response(
        status_code=status_code,
        body_text=body_text,
        live_status_codes=live_status_codes,
        review_status_codes=review_status_codes,
        failed_status_codes=failed_status_codes,
        review_keywords=review_keywords,
        failure_keywords=failure_keywords,
    )

    return {
        "message": "Checker job completed.",
        "profile_id": profile_id,
        "target_url": target_url,
        "health_status": health_status,
        "health_reason": health_reason,
        "status_code": status_code,
    }
