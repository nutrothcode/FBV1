from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .config import platform_auth_tokens_path


AUTH_STATUSES = (
    "Live",
    "Token Valid",
    "Token Expired",
    "Need Reconnect",
    "Login Required",
    "Unknown",
    "Failed",
)


@dataclass
class AuthCheckResult:
    success: bool
    status: str
    reason: str
    tokens: dict[str, Any] | None = None


class LocalAuthVault:
    """Encrypted per-platform token storage.

    On Windows this uses DPAPI through CryptProtectData/CryptUnprotectData.
    The app stores OAuth/API tokens only, not website passwords or cookies.
    """

    def load(self, platform: str) -> dict[str, dict[str, Any]]:
        path = platform_auth_tokens_path(platform)
        if not path.exists():
            return {}
        try:
            payload = self._decrypt(path.read_bytes())
            data = json.loads(payload.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logging.error("Could not load encrypted auth tokens for %s: %s", platform, exc)
            return {}

    def save(self, platform: str, data: dict[str, dict[str, Any]]) -> None:
        path = platform_auth_tokens_path(platform)
        encoded = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        path.write_bytes(self._encrypt(encoded))

    def get(self, platform: str, key: str) -> dict[str, Any] | None:
        return self.load(platform).get(key)

    def set(self, platform: str, key: str, auth: dict[str, Any]) -> None:
        data = self.load(platform)
        auth = dict(auth)
        auth["platform"] = platform
        auth["updated_at"] = datetime.now().isoformat(timespec="seconds")
        data[key] = auth
        self.save(platform, data)

    def clear(self, platform: str, key: str) -> bool:
        data = self.load(platform)
        existed = key in data
        data.pop(key, None)
        self.save(platform, data)
        return existed

    def _encrypt(self, payload: bytes) -> bytes:
        if os.name == "nt":
            return b"dpapi:" + _dpapi_protect(payload)
        return b"plain:" + base64.b64encode(payload)

    def _decrypt(self, payload: bytes) -> bytes:
        if payload.startswith(b"dpapi:"):
            return _dpapi_unprotect(payload[6:])
        if payload.startswith(b"plain:"):
            return base64.b64decode(payload[6:])
        return _dpapi_unprotect(payload) if os.name == "nt" else base64.b64decode(payload)


class AuthManager:
    def __init__(self) -> None:
        self.vault = LocalAuthVault()

    def save_auth(self, platform: str, key: str, auth: dict[str, Any]) -> None:
        self.vault.set(platform, key, auth)

    def clear_auth(self, platform: str, key: str) -> bool:
        return self.vault.clear(platform, key)

    def refresh_login(self, platform: str, key: str, account: dict[str, Any]) -> AuthCheckResult:
        auth = self.vault.get(platform, key)
        if not auth:
            return AuthCheckResult(False, "Need Reconnect", "No saved authorization token")

        if platform == "youtube":
            return self._refresh_google(auth)
        if platform == "tiktok":
            return self._refresh_tiktok(auth)
        if platform == "facebook":
            return self._check_facebook(auth)
        if platform == "instagram":
            return self._check_instagram(auth)
        if platform == "wordpress":
            return self._check_wordpress(auth, account)
        return AuthCheckResult(False, "Unknown", "Unsupported platform")

    def _refresh_google(self, auth: dict[str, Any]) -> AuthCheckResult:
        refresh_token = str(auth.get("refresh_token") or "").strip()
        if not refresh_token:
            return self._access_token_only_result(auth, "Google OAuth refresh token is missing")
        client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            return self._access_token_only_result(auth, "Google OAuth client env is not configured")
        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        return self._post_oauth_token("https://oauth2.googleapis.com/token", payload, auth, "Google OAuth token valid")

    def _refresh_tiktok(self, auth: dict[str, Any]) -> AuthCheckResult:
        refresh_token = str(auth.get("refresh_token") or "").strip()
        if not refresh_token:
            return self._access_token_only_result(auth, "TikTok OAuth refresh token is missing")
        client_key = os.getenv("TIKTOK_CLIENT_KEY", "").strip()
        client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "").strip()
        if not client_key or not client_secret:
            return self._access_token_only_result(auth, "TikTok OAuth client env is not configured")
        payload = {
            "client_key": client_key,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        return self._post_oauth_token(
            "https://open.tiktokapis.com/v2/oauth/token/",
            payload,
            auth,
            "TikTok OAuth token valid",
        )

    def _check_facebook(self, auth: dict[str, Any]) -> AuthCheckResult:
        token = str(auth.get("access_token") or "").strip()
        if not token:
            return AuthCheckResult(False, "Need Reconnect", "Meta access token is missing")
        app_id = os.getenv("META_APP_ID", "").strip()
        app_secret = os.getenv("META_APP_SECRET", "").strip()
        if app_id and app_secret:
            url = "https://graph.facebook.com/debug_token?" + urllib.parse.urlencode(
                {"input_token": token, "access_token": f"{app_id}|{app_secret}"}
            )
            data = self._get_json(url)
            token_data = data.get("data", {}) if isinstance(data, dict) else {}
            if token_data.get("is_valid"):
                return AuthCheckResult(True, "Live", "Token valid", auth)
            return AuthCheckResult(False, "Need Reconnect", str(token_data.get("error", {}).get("message") or "Meta token is invalid"))
        return self._check_bearer_me("https://graph.facebook.com/me", token, auth, "Meta token valid")

    def _check_instagram(self, auth: dict[str, Any]) -> AuthCheckResult:
        token = str(auth.get("access_token") or "").strip()
        if not token:
            return AuthCheckResult(False, "Need Reconnect", "Instagram access token is missing")
        url = "https://graph.instagram.com/me?" + urllib.parse.urlencode({"fields": "id,username", "access_token": token})
        try:
            data = self._get_json(url)
            if isinstance(data, dict) and data.get("id"):
                return AuthCheckResult(True, "Live", "Token valid", auth)
        except Exception as exc:
            return AuthCheckResult(False, "Need Reconnect", f"Instagram token check failed: {exc}")
        return AuthCheckResult(False, "Need Reconnect", "Instagram token is invalid")

    def _check_wordpress(self, auth: dict[str, Any], account: dict[str, Any]) -> AuthCheckResult:
        site_url = str(auth.get("site_url") or account.get("wordpress_site_url") or "").strip().rstrip("/")
        username = str(auth.get("username") or account.get("wordpress_username") or "").strip()
        app_password = str(auth.get("application_password") or auth.get("api_token") or "").strip()
        if not site_url or not username or not app_password:
            return AuthCheckResult(False, "Need Reconnect", "WordPress Site URL, username, and application password are required")
        endpoint = f"{site_url}/wp-json/wp/v2/users/me"
        basic = base64.b64encode(f"{username}:{app_password}".encode("utf-8")).decode("ascii")
        request = urllib.request.Request(endpoint, headers={"Authorization": f"Basic {basic}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                if 200 <= int(response.status) < 300:
                    return AuthCheckResult(True, "Live", "WordPress API token valid", auth)
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                return AuthCheckResult(False, "Need Reconnect", "WordPress API token rejected")
            return AuthCheckResult(False, "Failed", f"WordPress API check failed: HTTP {exc.code}")
        except Exception as exc:
            return AuthCheckResult(False, "Failed", f"WordPress API check failed: {exc}")
        return AuthCheckResult(False, "Failed", "WordPress API check failed")

    def _post_oauth_token(
        self,
        url: str,
        payload: dict[str, str],
        existing_auth: dict[str, Any],
        success_reason: str,
    ) -> AuthCheckResult:
        encoded = urllib.parse.urlencode(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=encoded,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.loads(response.read().decode("utf-8"))
            if "error" in data:
                return AuthCheckResult(False, "Need Reconnect", str(data.get("error_description") or data.get("error")))
            tokens = dict(existing_auth)
            tokens.update(data)
            if data.get("expires_in"):
                tokens["expires_at"] = int(datetime.now(timezone.utc).timestamp()) + int(data["expires_in"])
            return AuthCheckResult(True, "Live", success_reason, tokens)
        except Exception as exc:
            return AuthCheckResult(False, "Need Reconnect", f"OAuth refresh failed: {exc}")

    def _check_bearer_me(self, url: str, token: str, auth: dict[str, Any], success_reason: str) -> AuthCheckResult:
        request_url = url + "?" + urllib.parse.urlencode({"access_token": token})
        try:
            data = self._get_json(request_url)
            if isinstance(data, dict) and data.get("id"):
                return AuthCheckResult(True, "Live", success_reason, auth)
        except Exception as exc:
            return AuthCheckResult(False, "Need Reconnect", f"Token check failed: {exc}")
        return AuthCheckResult(False, "Need Reconnect", "Token is invalid")

    def _access_token_only_result(self, auth: dict[str, Any], missing_refresh_reason: str) -> AuthCheckResult:
        expires_at = auth.get("expires_at")
        try:
            if expires_at and int(expires_at) > int(datetime.now(timezone.utc).timestamp()):
                return AuthCheckResult(True, "Token Valid", "Saved access token has not expired", auth)
        except Exception:
            pass
        return AuthCheckResult(False, "Need Reconnect", missing_refresh_reason)

    def _get_json(self, url: str) -> dict[str, Any]:
        with urllib.request.urlopen(url, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi_protect(data: bytes) -> bytes:
    blob_in = _DataBlob(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    blob_out = _DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    blob_in = _DataBlob(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    blob_out = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
