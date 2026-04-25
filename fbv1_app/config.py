from __future__ import annotations

import logging
from pathlib import Path

from .platforms import PLATFORM_ORDER


BASE_DIR = Path(__file__).resolve().parent.parent
ACCOUNT_DIR = BASE_DIR / "Account Firefox"
FIREFOX_USER_DATA_DIR = ACCOUNT_DIR / "firefox"
IMAGE_DIR = BASE_DIR / "images"
COOKIE_DIR = BASE_DIR / "cookies"
DATA_DIR = BASE_DIR / "data"
BACKUP_DIR = BASE_DIR / "backups"
PLATFORM_FOLDER_DIRS = {
    platform: BASE_DIR / platform.title()
    for platform in PLATFORM_ORDER
}
PLATFORM_FOLDER_DIRS["facebook"] = BASE_DIR / "Facebook"
PLATFORM_FOLDER_DIRS["wordpress"] = BASE_DIR / "WordPress"
PLATFORM_DATA_DIRS = {platform: DATA_DIR / platform for platform in PLATFORM_ORDER}
DATA_FILE = BASE_DIR / "firefox_instances.json"
APP_DB_PATH = DATA_DIR / "fbv1_accounts.db"
GECKODRIVER_PATH = ACCOUNT_DIR / "geckodriver.exe"
LOGO_PATH = ACCOUNT_DIR / "fb logo.png"
ICON_PATH = ACCOUNT_DIR / "fb logo.png"

for folder in (
    FIREFOX_USER_DATA_DIR,
    IMAGE_DIR,
    COOKIE_DIR,
    DATA_DIR,
    BACKUP_DIR,
    *PLATFORM_FOLDER_DIRS.values(),
    *PLATFORM_DATA_DIRS.values(),
):
    folder.mkdir(parents=True, exist_ok=True)
for folder in PLATFORM_DATA_DIRS.values():
    (folder / "sessions").mkdir(parents=True, exist_ok=True)
    (folder / "logs").mkdir(parents=True, exist_ok=True)


def image_account_dir(instance_number: int) -> Path:
    folder = IMAGE_DIR / f"Firefox_{instance_number}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def firefox_user_data_dir_for_platform(platform: str) -> Path:
    if platform == "facebook":
        folder = FIREFOX_USER_DATA_DIR
    else:
        folder = PLATFORM_FOLDER_DIRS.get(platform, BASE_DIR / platform.title()) / "Firefox Profiles"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def cookie_dir_for_platform(platform: str) -> Path:
    if platform == "facebook":
        folder = COOKIE_DIR
    else:
        folder = PLATFORM_FOLDER_DIRS.get(platform, BASE_DIR / platform.title()) / "cookies"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def platform_data_dir(platform: str) -> Path:
    folder = PLATFORM_DATA_DIRS.get(platform, DATA_DIR / platform)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "sessions").mkdir(parents=True, exist_ok=True)
    (folder / "logs").mkdir(parents=True, exist_ok=True)
    return folder


def platform_accounts_path(platform: str) -> Path:
    return platform_data_dir(platform) / "accounts.json"


def platform_settings_path(platform: str) -> Path:
    return platform_data_dir(platform) / "settings.json"


def platform_auth_tokens_path(platform: str) -> Path:
    return platform_data_dir(platform) / "auth_tokens.enc"


def avatar_image_path(instance_number: int) -> Path:
    return image_account_dir(instance_number) / "avatar.png"


def cover_image_path(instance_number: int) -> Path:
    return image_account_dir(instance_number) / "cover.png"


def facebook_screenshot_path(instance_number: int, profile_name: str | None = None) -> Path:
    if profile_name:
        slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in profile_name.strip())
        slug = "_".join(part for part in slug.split("_") if part) or "unknown"
        filename = f"facebook_{slug}.png"
    else:
        filename = "facebook_unknown.png"
    return image_account_dir(instance_number) / filename

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")
