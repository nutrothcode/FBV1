from __future__ import annotations

import logging
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
ACCOUNT_DIR = BASE_DIR / "Account Firefox"
FIREFOX_USER_DATA_DIR = ACCOUNT_DIR / "firefox"
IMAGE_DIR = BASE_DIR / "images"
COOKIE_DIR = BASE_DIR / "cookies"
DATA_FILE = BASE_DIR / "firefox_instances.json"
GECKODRIVER_PATH = ACCOUNT_DIR / "geckodriver.exe"
LOGO_PATH = ACCOUNT_DIR / "fb logo.png"
ICON_PATH = ACCOUNT_DIR / "fb logo.png"

for folder in (FIREFOX_USER_DATA_DIR, IMAGE_DIR, COOKIE_DIR):
    folder.mkdir(parents=True, exist_ok=True)


def image_account_dir(instance_number: int) -> Path:
    folder = IMAGE_DIR / f"Firefox_{instance_number}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


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
