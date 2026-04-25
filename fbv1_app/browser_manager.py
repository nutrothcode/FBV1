from __future__ import annotations

import base64
import threading
import json
import logging
import math
import re
import time
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from PIL import Image

from .config import (
    GECKODRIVER_PATH,
    avatar_image_path,
    cover_image_path,
    cookie_dir_for_platform,
    facebook_screenshot_path,
    image_account_dir,
)
from .theme import DANGER, SUCCESS, TEXT_MUTED, WARNING

if TYPE_CHECKING:
    from .ui import FacebookToolApp


class BrowserManager:
    MOBILE_USER_AGENT = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
        "Mobile/15E148 Safari/604.1"
    )
    DESKTOP_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) "
        "Gecko/20100101 Firefox/126.0"
    )

    def __init__(self, app: "FacebookToolApp") -> None:
        self.app = app
        self._launch_lock = threading.Lock()
        self._launching_instances: set[int] = set()
        self._instance_slots: dict[int, int] = {}
        self._driver_modes: dict[int, str] = {}

    @property
    def state(self):
        return self.app.state

    def open_firefox_instance(
        self,
        instance_number: int,
        login: bool = True,
        clear_data_action: bool = False,
        start_url: str | None = None,
        sync_preview: bool = True,
    ) -> None:
        if not self.app.instances.allow_open_for_expected_country(instance_number):
            return
        assigned_slot: int | None = None
        requested_mode = self._current_browser_mode()
        self.app.instances.set_run_status(instance_number, "Launching", WARNING)
        with self._launch_lock:
            if instance_number in self._launching_instances:
                logging.info("Firefox %s launch skipped (already launching).", instance_number)
                self.app.instances.set_run_status(instance_number, "Launching", WARNING)
                return
            existing_driver = self.state.drivers.get(instance_number)
            if existing_driver is not None and self._driver_is_alive(existing_driver):
                existing_mode = self._driver_modes.get(instance_number)
                if existing_mode != requested_mode:
                    logging.info(
                        "Firefox %s relaunching to switch mode from %s to %s.",
                        instance_number,
                        existing_mode or "unknown",
                        requested_mode,
                    )
                    try:
                        existing_driver.quit()
                    except Exception:
                        pass
                    self.state.drivers.pop(instance_number, None)
                    self._driver_modes.pop(instance_number, None)
                    self._instance_slots.pop(instance_number, None)
                    existing_driver = None
                else:
                    self._apply_window_layout(existing_driver, instance_number)
                    self._apply_browser_mode_after_launch(existing_driver)
                    if start_url:
                        current_url = str(existing_driver.current_url or "")
                        if current_url.rstrip("/") != str(start_url).rstrip("/"):
                            existing_driver.get(start_url)
                    logging.info("Firefox %s launch skipped (already running).", instance_number)
                    self.app.instances.set_run_status(instance_number, "Running", SUCCESS)
                    return
            if existing_driver is not None and self._driver_is_alive(existing_driver):
                logging.info("Firefox %s launch skipped (already running).", instance_number)
                self.app.instances.set_run_status(instance_number, "Running", SUCCESS)
                return
            if existing_driver is not None:
                self.state.drivers.pop(instance_number, None)
                self._driver_modes.pop(instance_number, None)
            assigned_slot = self._assign_slot_locked(instance_number)
            self._launching_instances.add(instance_number)

        try:
            firefox_options = FirefoxOptions()

            user_data_dir = self.app.instances.firefox_profile_dir(instance_number)
            user_data_dir.mkdir(parents=True, exist_ok=True)
            firefox_options.add_argument("-profile")
            firefox_options.add_argument(str(user_data_dir))

            firefox_options.set_preference("browser.privatebrowsing.autostart", False)
            firefox_options.set_preference("privacy.clearOnShutdown.cookies", False)
            firefox_options.set_preference("privacy.clearOnShutdown.cache", False)
            firefox_options.set_preference("privacy.clearOnShutdown.sessions", False)
            firefox_options.set_preference("privacy.clearOnShutdown.offlineApps", False)
            firefox_options.set_preference("privacy.clearOnShutdown.siteSettings", False)
            firefox_options.set_preference("privacy.clearOnShutdown.formData", False)
            firefox_options.set_preference("privacy.clearOnShutdown.downloads", False)
            self._apply_browser_mode_preferences(firefox_options)

            logging.debug(
                "Attempting to launch Firefox instance %s with user data dir: %s",
                instance_number,
                user_data_dir,
            )

            service = FirefoxService(executable_path=str(GECKODRIVER_PATH))
            driver = webdriver.Firefox(service=service, options=firefox_options)
            self.state.drivers[instance_number] = driver
            self._driver_modes[instance_number] = requested_mode
            self._apply_window_layout(driver, instance_number, slot_index=assigned_slot)
            self._apply_browser_mode_after_launch(driver)
            self.app.instances.set_run_status(instance_number, "Running", SUCCESS)

            if clear_data_action:
                self.clear_data(driver)
                self.app.instances.set_run_status(instance_number, "Cache cleared", SUCCESS)
                return

            initial_url = start_url or "https://www.facebook.com"
            driver.get(initial_url)
            if start_url:
                logging.info("Firefox %s opened %s.", instance_number, initial_url)
            elif login:
                self.prepare_login(instance_number)
            else:
                logging.info("Firefox %s is ready for action.", instance_number)

            if sync_preview:
                self.try_sync_profile_preview(instance_number)
        except Exception as exc:
            logging.error("Failed to open Firefox instance %s: %s", instance_number, exc)
            self.state.run_summary.append(f"Firefox {instance_number}: Error")
            self.app.instances.set_run_status(instance_number, "Launch failed", DANGER)
        finally:
            with self._launch_lock:
                self._launching_instances.discard(instance_number)
                driver = self.state.drivers.get(instance_number)
                if driver is None or not self._driver_is_alive(driver):
                    self._instance_slots.pop(instance_number, None)
                    self._driver_modes.pop(instance_number, None)

    def _driver_is_alive(self, driver) -> bool:
        try:
            _ = driver.current_url
            return True
        except Exception:
            return False

    def is_instance_running(self, instance_number: int) -> bool:
        driver = self.state.drivers.get(instance_number)
        if driver is None:
            return False
        if self._driver_is_alive(driver):
            return True
        with self._launch_lock:
            self.state.drivers.pop(instance_number, None)
            self._launching_instances.discard(instance_number)
            self._instance_slots.pop(instance_number, None)
            self._driver_modes.pop(instance_number, None)
        return False

    def prepare_platform_publish(
        self,
        *,
        instance_number: int,
        platform: str,
        media_paths: str,
        caption: str,
    ) -> bool:
        """Best-effort media/caption preparation for non-Facebook upload pages.

        The final Publish/Post click is intentionally left for the operator.
        """
        driver = self.state.drivers.get(instance_number)
        if driver is None or not self._driver_is_alive(driver):
            return False

        media_path = self._first_existing_media_path(media_paths)
        prepared_any = False
        try:
            if platform == "instagram":
                self._open_instagram_create_dialog(driver)

            if media_path:
                prepared_any = self._send_file_to_any_input(driver, str(media_path))
                if prepared_any:
                    logging.info("Prepared %s media for Firefox %s.", platform, instance_number)

            if caption.strip():
                caption_ready = self._fill_platform_caption(driver, caption.strip())
                prepared_any = prepared_any or caption_ready
                if caption_ready:
                    logging.info("Prepared %s caption for Firefox %s.", platform, instance_number)
        except Exception as exc:
            logging.warning("Platform publish preparation failed for Firefox %s: %s", instance_number, exc)
            return prepared_any
        return prepared_any

    def _first_existing_media_path(self, media_paths: str) -> Path | None:
        for raw_path in re.split(r"[,;\n]+", media_paths or ""):
            candidate = raw_path.strip().strip('"')
            if not candidate:
                continue
            path = Path(candidate).expanduser()
            if path.exists() and path.is_file():
                return path.resolve()
        return None

    def _open_instagram_create_dialog(self, driver) -> bool:
        return self._click_first(
            driver,
            [
                (By.XPATH, "//*[@aria-label='New post']/ancestor::*[@role='link' or @role='button'][1]"),
                (By.XPATH, "//*[normalize-space()='Create']/ancestor::*[@role='link' or @role='button'][1]"),
                (By.XPATH, "//*[normalize-space()='Post']/ancestor::*[@role='link' or @role='button'][1]"),
            ],
            timeout_seconds=5,
        )

    def _fill_platform_caption(self, driver, caption: str) -> bool:
        selectors = [
            (By.XPATH, "//textarea[contains(@aria-label,'caption') or contains(@aria-label,'description')]"),
            (By.XPATH, "//textarea[contains(@placeholder,'caption') or contains(@placeholder,'description')]"),
            (By.XPATH, "//div[@role='textbox']"),
            (By.XPATH, "//*[@contenteditable='true']"),
            (By.XPATH, "//textarea"),
        ]
        for by, locator in selectors:
            try:
                elements = driver.find_elements(by, locator)
            except Exception:
                elements = []
            for element in elements:
                try:
                    if hasattr(element, "is_displayed") and not element.is_displayed():
                        continue
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
                    try:
                        element.clear()
                        element.send_keys(caption)
                    except Exception:
                        driver.execute_script(
                            """
                            const el = arguments[0];
                            const text = arguments[1];
                            el.focus();
                            if ('value' in el) {
                                el.value = text;
                            } else {
                                el.textContent = text;
                            }
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                            """,
                            element,
                            caption,
                        )
                    return True
                except Exception:
                    continue
        return False

    def count_active_instances(self, start_instance: int, end_instance: int) -> int:
        with self._launch_lock:
            self._cleanup_dead_instances_locked()
            launching_count = sum(
                1 for instance_number in self._launching_instances if start_instance <= instance_number <= end_instance
            )

        running_count = 0
        for instance_number in range(start_instance, end_instance + 1):
            if self.is_instance_running(instance_number):
                running_count += 1
        return launching_count + running_count

    def _apply_window_layout(self, driver, instance_number: int, slot_index: int | None = None) -> None:
        if self._current_browser_mode() == "phone":
            try:
                driver.set_window_rect(x=80, y=24, width=430, height=820)
            except Exception:
                try:
                    driver.set_window_size(430, 820)
                    driver.set_window_position(80, 24)
                except Exception as exc:
                    logging.debug("Could not apply phone window for Firefox %s: %s", instance_number, exc)
            return

        if slot_index is None:
            with self._launch_lock:
                slot_index = self._instance_slots.get(instance_number)
                if slot_index is None:
                    slot_index = self._assign_slot_locked(instance_number)
        x, y, width, height = self._window_rect_for_slot(slot_index)
        try:
            driver.set_window_rect(x=x, y=y, width=width, height=height)
        except Exception:
            try:
                driver.set_window_size(width, height)
                driver.set_window_position(x, y)
            except Exception as exc:
                logging.debug("Could not position Firefox %s window: %s", instance_number, exc)

    def _current_browser_mode(self) -> str:
        try:
            mode = self.app.vars.browser_mode_var.get()
        except Exception:
            mode = "pc"
        return "phone" if mode == "phone" else "pc"

    def _apply_browser_mode_preferences(self, firefox_options: FirefoxOptions) -> None:
        if self._current_browser_mode() == "phone":
            firefox_options.set_preference("general.useragent.override", self.MOBILE_USER_AGENT)
            firefox_options.set_preference("dom.w3c_touch_events.enabled", 1)
            firefox_options.set_preference("apz.allow_zooming", True)
            firefox_options.set_preference("browser.viewport.desktopWidth", 390)
            return

        firefox_options.set_preference("general.useragent.override", self.DESKTOP_USER_AGENT)
        firefox_options.set_preference("dom.w3c_touch_events.enabled", 0)

    def _apply_browser_mode_after_launch(self, driver) -> None:
        if self._current_browser_mode() != "phone":
            return
        try:
            driver.execute_script(
                """
                Object.defineProperty(navigator, 'maxTouchPoints', {get: () => 5});
                Object.defineProperty(navigator, 'platform', {get: () => 'iPhone'});
                """
            )
        except Exception as exc:
            logging.debug("Could not apply phone runtime hints: %s", exc)

    def _window_rect_for_instance(self, instance_number: int) -> tuple[int, int, int, int]:
        with self._launch_lock:
            slot_index = self._instance_slots.get(instance_number, max(1, instance_number) - 1)
        return self._window_rect_for_slot(slot_index)

    def _window_rect_for_slot(self, slot_index: int) -> tuple[int, int, int, int]:
        try:
            screen_width = int(self.app.root.winfo_screenwidth() or 1920)
            screen_height = int(self.app.root.winfo_screenheight() or 1080)
        except Exception:
            screen_width, screen_height = 1920, 1080

        margin_x = 12
        margin_y = 24
        gap = 10
        taskbar_reserved = 96

        usable_width = max(800, screen_width - (margin_x * 2))
        usable_height = max(500, screen_height - taskbar_reserved - (margin_y * 2))

        window_width = max(360, min(460, (usable_width // 3) - gap))
        window_height = max(260, min(340, (usable_height // 2) - gap))

        cols = max(1, (usable_width + gap) // (window_width + gap))
        rows = max(1, (usable_height + gap) // (window_height + gap))
        slots = max(1, cols * rows)

        normalized_slot = max(0, slot_index) % slots
        col = normalized_slot % cols
        row = normalized_slot // cols

        x = margin_x + (col * (window_width + gap))
        y = margin_y + (row * (window_height + gap))
        return x, y, window_width, window_height

    def _assign_slot_locked(self, instance_number: int) -> int:
        self._cleanup_dead_instances_locked()
        existing_slot = self._instance_slots.get(instance_number)
        if existing_slot is not None:
            return existing_slot

        _, _, _, _, cols, rows = self._layout_meta()
        slots = max(1, cols * rows)
        active_instances = set(self._launching_instances)
        for active_instance, driver in self.state.drivers.items():
            if self._driver_is_alive(driver):
                active_instances.add(active_instance)

        used_slots = {
            self._instance_slots[active_instance]
            for active_instance in active_instances
            if active_instance in self._instance_slots
        }

        for candidate_slot in range(slots):
            if candidate_slot not in used_slots:
                self._instance_slots[instance_number] = candidate_slot
                return candidate_slot

        fallback_slot = (max(1, instance_number) - 1) % slots
        self._instance_slots[instance_number] = fallback_slot
        return fallback_slot

    def _cleanup_dead_instances_locked(self) -> None:
        for instance_number, driver in list(self.state.drivers.items()):
            if not self._driver_is_alive(driver):
                self.state.drivers.pop(instance_number, None)
                self._launching_instances.discard(instance_number)
                self._instance_slots.pop(instance_number, None)
                self._driver_modes.pop(instance_number, None)

        active_instances = set(self._launching_instances) | set(self.state.drivers.keys())
        for instance_number in list(self._instance_slots.keys()):
            if instance_number not in active_instances:
                self._instance_slots.pop(instance_number, None)
                self._driver_modes.pop(instance_number, None)

    def _layout_meta(self) -> tuple[int, int, int, int, int, int]:
        try:
            screen_width = int(self.app.root.winfo_screenwidth() or 1920)
            screen_height = int(self.app.root.winfo_screenheight() or 1080)
        except Exception:
            screen_width, screen_height = 1920, 1080

        margin_x = 12
        margin_y = 24
        gap = 10
        taskbar_reserved = 96

        usable_width = max(800, screen_width - (margin_x * 2))
        usable_height = max(500, screen_height - taskbar_reserved - (margin_y * 2))

        window_width = max(360, min(460, (usable_width // 3) - gap))
        window_height = max(260, min(340, (usable_height // 2) - gap))

        cols = max(1, (usable_width + gap) // (window_width + gap))
        rows = max(1, (usable_height + gap) // (window_height + gap))
        return margin_x, margin_y, window_width, window_height, cols, rows

    def prepare_login(self, instance_number: int) -> None:
        driver = self.state.drivers.get(instance_number)
        if not driver:
            logging.error("Firefox %s is not running.", instance_number)
            self.state.run_summary.append(f"Firefox {instance_number}: Error")
            self.app.instances.set_run_status(instance_number, "Not running", DANGER)
            return

        try:
            platform = self.app.vars.platform_var.get()
            url = self.app.instances.PLATFORM_HOME_URLS.get(platform, "https://www.facebook.com")
            driver.get(url)
            logging.info("Opened %s for Firefox %s. Password/2FA automation is disabled.", platform, instance_number)
            self.app.instances.set_preview_status(instance_number, "Opened platform home", TEXT_MUTED)
            self.app.instances.set_run_status(instance_number, "Manual/OAuth only", WARNING)
        except Exception as exc:
            logging.error("Failed opening platform home: %s", exc)
            self.state.run_summary.append(f"Firefox {instance_number}: Error")
            self.app.instances.set_run_status(instance_number, "Open failed", DANGER)

    def get_2fa_code(self, secret: str, driver) -> str | None:
        logging.info("2FA automation is disabled. Complete authorization manually through the official provider.")
        return None

    def get_id(self, instance_number: int) -> str | None:
        driver = self.state.drivers.get(instance_number)
        if not driver:
            logging.warning("Get ID skipped: Firefox %s is not running.", instance_number)
            return None

        self.app.instances.set_run_status(instance_number, "Getting ID", WARNING)
        return self._sync_profile_identity_from_driver(instance_number, driver, restore_url=False)

    def _sync_profile_identity_from_driver(self, instance_number: int, driver, restore_url: bool = True) -> str | None:
        original_url = ""
        try:
            original_url = str(driver.current_url or "")
        except Exception:
            original_url = ""

        try:
            # Ensure we're on an authenticated Facebook page so cookie + profile signals are available.
            driver.get("https://www.facebook.com/me")
            time.sleep(1.0)
            account_id = self._extract_account_id_from_driver(driver)
            date_birth, gender, gmail = self._extract_profile_identity(driver, account_id=account_id or "")
            self.app.instances.set_profile_identity(
                instance_number,
                date_birth=date_birth,
                gender=gender,
                gmail=gmail,
            )
            if account_id:
                self.app.instances.set_account_id(instance_number, account_id)
                logging.info("Firefox %s account id detected: %s", instance_number, account_id)
                return account_id
        except Exception as exc:
            logging.error("Identity sync failed for Firefox %s: %s", instance_number, exc)
        finally:
            if restore_url and original_url:
                try:
                    driver.get(original_url)
                except Exception:
                    pass

        logging.warning("Identity sync did not find a numeric account id for Firefox %s.", instance_number)
        return None

    def _sync_profile_identity_from_current_page(self, instance_number: int, driver) -> bool:
        try:
            profile_name = self._extract_profile_name_from_current_page(driver)
            account_id = self._extract_account_id_from_driver(driver)
            source = str(getattr(driver, "page_source", "") or "")
            body_text = self._safe_body_text(driver)
            center_profile_name, center_date_birth, center_gmail = self._extract_accounts_center_identity_from_visible_text(body_text)
            if not profile_name:
                profile_name = center_profile_name
            date_birth = center_date_birth or self._extract_date_birth_from_text_or_source(source, body_text)
            gender = self._extract_gender_from_visible_page(driver)
            if not gender:
                gender = self._extract_gender_from_text_or_source(source, body_text)
            gmail = center_gmail or self._extract_gmail_from_text_or_source(source, body_text)
            if profile_name:
                self.app.instances.set_profile_name(instance_number, profile_name)
            if account_id:
                self.app.instances.set_account_id(instance_number, account_id)
            self.app.instances.set_profile_identity(
                instance_number,
                date_birth=date_birth,
                gender=gender,
                gmail=gmail,
            )
            return bool(profile_name or account_id or date_birth or gender or gmail)
        except Exception as exc:
            logging.debug("Current-page identity sync failed for Firefox %s: %s", instance_number, exc)
            return False

    def _extract_profile_name_from_current_page(self, driver) -> str:
        try:
            profile_name_element = self._find_profile_name_element(driver)
            if profile_name_element:
                name = str(profile_name_element.text or "").strip()
                if name and not self._looks_generic_name(name):
                    return name
        except Exception:
            pass

        try:
            title = str(driver.title or "").strip()
        except Exception:
            title = ""
        if title:
            title = re.sub(r"^\(\d+\)\s*", "", title).strip()
            title = re.sub(r"\s*\|\s*Facebook\s*$", "", title, flags=re.IGNORECASE).strip()
            if title and not self._looks_generic_name(title):
                return title
        return ""

    def _extract_account_id_from_driver(self, driver) -> str | None:
        # Common source in profile URLs. Cookies are intentionally not read.
        url_id = self._extract_numeric_id_from_url(getattr(driver, "current_url", ""))
        if url_id:
            return url_id

        try:
            for link in driver.find_elements(By.CSS_SELECTOR, 'a[href*="profile.php?id="]'):
                link_url = str(link.get_attribute("href") or "").strip()
                link_id = self._extract_numeric_id_from_url(link_url)
                if link_id:
                    return link_id
        except Exception:
            pass

        # Final fallback for embedded page state.
        source = str(getattr(driver, "page_source", "") or "")
        patterns = (
            r'"entity_id":"(\d{5,25})"',
            r'"userID":"(\d{5,25})"',
            r'"profile_id":"(\d{5,25})"',
        )
        for pattern in patterns:
            match = re.search(pattern, source)
            if match:
                return match.group(1)
        return None

    def _extract_profile_identity(self, driver, account_id: str = "") -> tuple[str, str, str]:
        date_birth = ""
        gender = ""
        gmail = ""

        # Try from current page source first.
        source = str(getattr(driver, "page_source", "") or "")
        body_text = self._safe_body_text(driver)
        date_birth = self._extract_date_birth_from_text_or_source(source, body_text)
        gender = self._extract_gender_from_text_or_source(source, body_text)
        gmail = self._extract_gmail_from_text_or_source(source, body_text)
        if date_birth and gender and gmail:
            return date_birth, gender, gmail

        # Accounts Center is the most reliable place for primary email + birthday.
        accounts_center_urls = [
            "https://accountscenter.facebook.com/profiles",
            "https://accountscenter.facebook.com/personal_info",
        ]
        for url in accounts_center_urls:
            try:
                driver.get(url)
                time.sleep(1.6)
                page_source = str(getattr(driver, "page_source", "") or "")
                body_text = self._safe_body_text(driver)
                _center_profile_name, center_date_birth, center_gmail = self._extract_accounts_center_identity_from_visible_text(body_text)

                if not date_birth:
                    date_birth = center_date_birth or self._extract_date_birth_from_text_or_source(page_source, body_text)
                if not gender:
                    gender = self._extract_gender_from_text_or_source(page_source, body_text)
                if not gmail:
                    gmail = center_gmail or self._extract_gmail_from_text_or_source(page_source, body_text)

                if date_birth and gender and gmail:
                    break
            except Exception:
                continue

        # About page usually has explicit birthday/gender text.
        about_urls = []
        if account_id.isdigit():
            about_urls.extend(
                [
                    f"https://www.facebook.com/profile.php?id={account_id}&sk=directory_personal_details",
                    f"https://www.facebook.com/profile.php?id={account_id}&sk=about_contact_and_basic_info",
                ]
            )
        about_urls.extend(
            [
                "https://www.facebook.com/me/about_details",
                "https://www.facebook.com/me/about_contact_and_basic_info",
                "https://www.facebook.com/me/about",
            ]
        )

        for url in about_urls:
            try:
                driver.get(url)
                time.sleep(1.4)
                page_source = str(getattr(driver, "page_source", "") or "")
                body_text = self._safe_body_text(driver)

                if not date_birth:
                    date_birth = self._extract_date_birth_from_text_or_source(page_source, body_text)
                if not gender:
                    gender = self._extract_gender_from_text_or_source(page_source, body_text)
                if not gender:
                    gender = self._extract_gender_from_visible_page(driver)
                if not gmail:
                    gmail = self._extract_gmail_from_text_or_source(page_source, body_text)
                if date_birth and gender and gmail:
                    break
            except Exception:
                continue

        return date_birth, gender, gmail

    def _safe_body_text(self, driver) -> str:
        try:
            return str(driver.execute_script("return document.body ? document.body.innerText : '';") or "")
        except Exception:
            return ""

    def _extract_accounts_center_identity_from_visible_text(self, body_text: str) -> tuple[str, str, str]:
        lines = [line.strip() for line in str(body_text or "").splitlines() if line.strip()]
        profile_name = ""
        date_birth = ""
        email = ""
        for index, line in enumerate(lines):
            label = line.lower()
            if label == "profiles" and not profile_name:
                for candidate in lines[index + 1 : index + 8]:
                    if candidate.lower() in {"facebook", "add accounts"}:
                        continue
                    if "@" in candidate:
                        continue
                    if not self._looks_generic_name(candidate):
                        profile_name = candidate
                        break
            elif label == "contact info" and not email:
                for candidate in lines[index + 1 : index + 5]:
                    extracted = self._extract_gmail_from_text_or_source("", candidate)
                    if extracted:
                        email = extracted
                        break
            elif label == "birthday" and not date_birth:
                for candidate in lines[index + 1 : index + 4]:
                    if re.search(r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\b", candidate, flags=re.IGNORECASE):
                        date_birth = candidate
                        break
                    if re.search(r"\b\d{1,2}[/-]\d{1,2}[/-](?:19|20)\d{2}\b", candidate):
                        date_birth = candidate
                        break
        if not email:
            contact_match = re.search(r"Contact info\s*\n\s*([^\n]+@[^\n]+)", body_text or "", flags=re.IGNORECASE)
            if contact_match:
                email = self._extract_gmail_from_text_or_source("", contact_match.group(1))
        if not date_birth:
            birthday_match = re.search(r"Birthday\s*\n\s*([^\n]+)", body_text or "", flags=re.IGNORECASE)
            if birthday_match:
                date_birth = birthday_match.group(1).strip()
        return profile_name, date_birth, email

    def _extract_date_birth_from_text_or_source(self, source: str, body_text: str) -> str:
        # JSON-ish payload pattern
        birth_json = re.search(
            r'"birthdate"\s*:\s*\{\s*"day"\s*:\s*(\d{1,2})\s*,\s*"month"\s*:\s*(\d{1,2})\s*,\s*"year"\s*:\s*(\d{4})',
            source,
        )
        if birth_json:
            day, month, year = birth_json.group(1), birth_json.group(2), birth_json.group(3)
            return f"{year}-{int(month):02d}-{int(day):02d}"

        # Visible text patterns (English)
        text = body_text or ""
        patterns = [
            r"Birthday\s*\n([^\n]+)",
            r"Date of birth\s*\n([^\n]+)",
            r"Born on\s*([^\n]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                birthday_value = match.group(1).strip()
                if re.search(r"\b(19|20)\d{2}\b", birthday_value):
                    return birthday_value
                year_value = self._extract_birth_year(source, text)
                if year_value:
                    return f"{birthday_value}, {year_value}"
                return birthday_value
        return ""

    def _extract_birth_year(self, source: str, body_text: str) -> str:
        text = body_text or ""
        text_patterns = [
            r"Birth year\s*\n(\d{4})",
            r"\bYear\s*\n(\d{4})",
            r"Birthday\s*\n[^\n]+\n(\d{4})",
        ]
        for pattern in text_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1)

        source_patterns = [
            r'"birthdate"\s*:\s*\{[^}]*"year"\s*:\s*(\d{4})',
            r'"birth_year"\s*:\s*(\d{4})',
            r'"birthday_year"\s*:\s*(\d{4})',
        ]
        for pattern in source_patterns:
            match = re.search(pattern, source, flags=re.IGNORECASE | re.DOTALL)
            if match:
                return match.group(1)
        return ""

    def _extract_gender_from_text_or_source(self, source: str, body_text: str) -> str:
        gender_json = re.search(r'"gender"\s*:\s*"([A-Za-z_]+)"', source)
        if gender_json:
            return self._normalize_gender(gender_json.group(1))

        text = body_text or ""
        match = re.search(r"Gender\s*\n([^\n]+)", text, flags=re.IGNORECASE)
        if match:
            return self._normalize_gender(match.group(1))
        return ""

    def _extract_gender_from_visible_page(self, driver) -> str:
        try:
            body_text = self._safe_body_text(driver)
            gender = self._extract_gender_from_visible_text(body_text)
            if gender:
                return gender
        except Exception:
            pass

        xpath_candidates = (
            "//*[normalize-space()='Gender']/following::*[normalize-space()='Female' or normalize-space()='Male' or normalize-space()='Custom'][1]",
            "//*[normalize-space()='Female' or normalize-space()='Male' or normalize-space()='Custom'][following::*[normalize-space()='Gender'] or preceding::*[normalize-space()='Gender']]",
        )
        for xpath in xpath_candidates:
            try:
                for element in driver.find_elements(By.XPATH, xpath):
                    text = str(element.text or "").strip()
                    gender = self._normalize_gender(text)
                    if gender in {"Female", "Male", "Custom"}:
                        return gender
            except Exception:
                continue
        return ""

    def _extract_gender_from_visible_text(self, text: str) -> str:
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        for index, line in enumerate(lines):
            if line.lower() != "gender":
                continue
            for candidate in lines[index + 1 : index + 5]:
                gender = self._normalize_gender(candidate)
                if gender in {"Female", "Male", "Custom"}:
                    return gender
        compact = "\n".join(lines)
        match = re.search(r"\bGender\s*\n\s*(Female|Male|Custom)\b", compact, flags=re.IGNORECASE)
        if match:
            return self._normalize_gender(match.group(1))
        return ""

    def _extract_gmail_from_text_or_source(self, source: str, body_text: str) -> str:
        candidates: list[str] = []
        source_text = unescape(str(source or "")).replace("\\/", "/")
        source_text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), source_text)
        body = str(body_text or "")
        email_pattern = r"([A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"

        source_patterns = [
            r'"(?:primary_)?email"\s*:\s*"([^"]+@[^"]+)"',
            r'"contact(?:_point)?"\s*:\s*"([^"]+@[^"]+)"',
        ]
        for pattern in source_patterns:
            for match in re.findall(pattern, source_text, flags=re.IGNORECASE):
                candidates.append(str(match).strip())

        for match in re.findall(email_pattern, source_text):
            candidates.append(str(match).strip())
        for match in re.findall(email_pattern, body):
            candidates.append(str(match).strip())

        text_patterns = [
            r"Contact info\s*\n([^\n]+@[^\n]+)",
            r"Email(?: address)?\s*\n([^\n]+@[^\n]+)",
        ]
        for pattern in text_patterns:
            match = re.search(pattern, body, flags=re.IGNORECASE)
            if match:
                candidates.append(str(match.group(1)).strip())

        valid: list[str] = []
        for candidate in candidates:
            clean = re.sub(r"[,\s]+$", "", candidate)
            clean = clean.replace("\\", "")
            lower = clean.lower()
            if not re.match(rf"^{email_pattern}$", clean):
                continue
            if any(skip in lower for skip in ("facebookmail.com", "@facebook.com", "noreply", "notification")):
                continue
            if clean not in valid:
                valid.append(clean)

        if not valid:
            return ""

        def candidate_score(value: str) -> int:
            local, _, domain = value.partition("@")
            score = len(local)
            if "+" in local:
                score += 4
            if "#" in local:
                score += 4
            if domain.lower() == "gmail.com":
                score += 2
            return score

        gmail_values = [value for value in valid if value.lower().endswith("@gmail.com")]
        if gmail_values:
            return max(gmail_values, key=candidate_score)
        return max(valid, key=candidate_score)

    def _normalize_gender(self, value: str) -> str:
        raw = str(value or "").strip().replace("_", " ").lower()
        if not raw:
            return ""
        if raw == "female" or re.search(r"\bfemale\b", raw):
            return "Female"
        if raw == "male" or re.search(r"\bmale\b", raw):
            return "Male"
        if raw == "custom" or re.search(r"\bcustom\b", raw):
            return "Custom"
        return raw.title()

    def _extract_numeric_id_from_url(self, url: str) -> str | None:
        if not url:
            return None
        try:
            parts = urlsplit(url)
        except Exception:
            return None
        query_values = dict(parse_qsl(parts.query))
        query_id = str(query_values.get("id", "")).strip()
        if query_id.isdigit():
            return query_id
        match = re.search(r"/profile\.php/(\d{5,25})", parts.path)
        if match:
            return match.group(1)
        return None

    def get_gmail(self, instance_number: int) -> None:
        try:
            driver = self.state.drivers.get(instance_number)
            if not driver:
                print(f"Error: Firefox {instance_number} is not running.")
                return
            driver.get("https://accountscenter.facebook.com/personal_info")
            self._start_identity_refresh_monitor(instance_number)
        except Exception as exc:
            print(f"Error: Please Continue^.^: {exc}")

    def get_date(self, instance_number: int) -> None:
        try:
            driver = self.state.drivers.get(instance_number)
            if not driver:
                print(f"Error: Firefox {instance_number} is not running.")
                return
            driver.get("https://www.facebook.com/your_information/?tab=your_information&tile=personal_info_grouping")
            self._start_identity_refresh_monitor(instance_number)
        except Exception as exc:
            print(f"Error: Please Continue^.^: {exc}")

    def get_cover(self, instance_number: int) -> None:
        cover_path = self.state.cover_upload_paths.get(instance_number, "")
        self.upload_profile_media(instance_number, photo_path="", cover_path=cover_path)

    def get_photo(self, instance_number: int) -> None:
        photo_path = self.state.photo_upload_paths.get(instance_number, "")
        profile_description = self.state.photo_upload_descriptions.get(instance_number, "")
        self.upload_profile_media(
            instance_number,
            photo_path=photo_path,
            cover_path="",
            profile_description=profile_description,
        )

    def upload_profile_media(
        self,
        instance_number: int,
        photo_path: str = "",
        cover_path: str = "",
        profile_description: str = "",
    ) -> bool:
        driver = self.state.drivers.get(instance_number)
        if not driver:
            logging.warning("Upload media skipped: Firefox %s is not running.", instance_number)
            return False

        requested = []
        photo_path = str(photo_path or "").strip()
        cover_path = str(cover_path or "").strip()
        if photo_path:
            requested.append(("profile", photo_path))
        if cover_path:
            requested.append(("cover", cover_path))
        if not requested:
            logging.warning("Upload media skipped for Firefox %s: no media configured.", instance_number)
            return False

        for media_kind, media_path in requested:
            if not Path(media_path).is_file():
                logging.warning("Upload media missing file for Firefox %s (%s): %s", instance_number, media_kind, media_path)
                return False

        try:
            driver.get("https://www.facebook.com/profile.php?id")
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='main']")))
            time.sleep(1)
        except Exception as exc:
            logging.error("Upload media navigation failed for Firefox %s: %s", instance_number, exc)
            return False

        success_count = 0
        for media_kind, media_path in requested:
            try:
                uploaded = (
                    self._upload_profile_photo(driver, media_path, profile_description=profile_description)
                    if media_kind == "profile"
                    else self._upload_cover_photo(driver, media_path)
                )
                if uploaded:
                    success_count += 1
                else:
                    logging.warning("Upload %s failed for Firefox %s.", media_kind, instance_number)
                    return False
            except Exception as exc:
                logging.warning("Upload %s error for Firefox %s: %s", media_kind, instance_number, exc)
                return False

        if success_count == len(requested):
            logging.info("Upload media complete for Firefox %s (profile=%s, cover=%s).", instance_number, bool(photo_path), bool(cover_path))
            return True
        return False

    def _upload_profile_photo(self, driver, photo_path: str, profile_description: str = "") -> bool:
        if not self._click_first(
            driver,
            [
                (By.CSS_SELECTOR, 'div[aria-label="Profile picture actions"]'),
                (By.CSS_SELECTOR, 'div[aria-label="Update profile picture"]'),
                (By.XPATH, "//div[@role='button' and .//span[contains(.,'Profile picture')]]"),
            ],
            timeout_seconds=8,
        ):
            return False

        # Preferred flow: Choose profile picture -> Upload photo -> Save.
        # If "Choose profile picture" is not shown in this account UI variant, fallback still works.
        self._click_first(
            driver,
            [
                (By.XPATH, "//span[normalize-space()='Choose profile picture']/ancestor::*[@role='menuitem'][1]"),
                (By.XPATH, "//span[normalize-space()='Choose profile picture']/ancestor::*[@role='button'][1]"),
                (By.XPATH, "//div[@role='menuitem' and .//span[contains(.,'Choose profile picture')]]"),
            ],
            timeout_seconds=4,
        )

        if not self._send_file_via_upload_label(driver, "Upload photo", photo_path):
            if not self._click_first(
                driver,
                [
                    (By.XPATH, "//span[normalize-space()='Upload photo']/ancestor::div[@role='menuitem'][1]"),
                    (By.XPATH, "//span[normalize-space()='Upload photo']/ancestor::div[@role='button'][1]"),
                    (By.XPATH, "//span[contains(normalize-space(),'Upload photo')]/ancestor::*[@role='button'][1]"),
                    (By.XPATH, "//span[contains(normalize-space(),'Upload photo')]/ancestor::*[@role='menuitem'][1]"),
                    (By.XPATH, "//div[@role='menuitem' and .//span[contains(.,'Upload')]]"),
                ],
                timeout_seconds=10,
            ):
                return False
        if not self._send_file_to_any_input(driver, photo_path):
            return False

        if profile_description.strip():
            self._set_profile_description(driver, profile_description.strip())

        saved = self._click_optional_save(driver)
        if not saved:
            return False

        self._finalize_profile_upload(driver)
        return True

    def _upload_cover_photo(self, driver, cover_path: str) -> bool:
        """Corrected cover upload flow with cover-specific Save changes click."""
        try:
            try:
                self._dismiss_leave_page_prompt(driver)
            except Exception:
                pass

            if not self._click_first(
                driver,
                [
                    (By.XPATH, "//span[normalize-space()='Edit cover photo']/ancestor::div[@role='button']"),
                    (By.CSS_SELECTOR, 'div[aria-label=\"Edit cover photo\"]'),
                ],
                timeout_seconds=12,
            ):
                logging.warning("Could not find 'Edit Cover Photo' button.")
                return False

            upload_item = self._find_first_element(
                driver,
                [
                    (By.XPATH, "//span[normalize-space()='Upload photo']/ancestor::div[@role='menuitem']"),
                    (By.XPATH, "//span[normalize-space()='Upload photo']/ancestor::div[@role='button']"),
                ],
                timeout_seconds=10,
            )
            if not upload_item:
                logging.warning("Could not find 'Upload photo' menu item.")
                return False

            try:
                file_input = upload_item.find_element(By.XPATH, ".//input[@type='file']")
            except Exception:
                file_input = driver.find_element(By.XPATH, "//input[@type='file' and contains(@accept,'image')]")

            driver.execute_script(
                "arguments[0].style.display='block';"
                "arguments[0].style.visibility='visible';"
                "arguments[0].style.opacity=1;",
                file_input,
            )
            file_input.send_keys(str(Path(cover_path).resolve()))
            logging.info("Cover file sent successfully.")

            if not self._wait_cover_editor_ready(driver):
                logging.warning("Cover editor did not become ready.")
                return False

            saved = self._click_cover_save_changes(driver)
            if not saved:
                logging.warning("Save changes click failed in cover editor.")
                return False

            time.sleep(1.2)
            return True
        except Exception as exc:
            logging.error("Cover upload failed: %s", exc)
            return False

    def _click_first(self, driver, selectors: list[tuple[str, str]], timeout_seconds: int = 10) -> bool:
        for by, locator in selectors:
            try:
                element = WebDriverWait(driver, timeout_seconds).until(EC.element_to_be_clickable((by, locator)))
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
                try:
                    element.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", element)
                time.sleep(0.6)
                return True
            except Exception:
                continue
        return False

    def _find_first_element(self, driver, selectors: list[tuple[str, str]], timeout_seconds: int = 10):
        for by, locator in selectors:
            try:
                return WebDriverWait(driver, timeout_seconds).until(EC.presence_of_element_located((by, locator)))
            except Exception:
                continue
        return None

    def _send_file_to_any_input(self, driver, file_path: str) -> bool:
        normalized_path = str(Path(file_path).resolve())
        for _ in range(8):
            try:
                inputs = driver.find_elements(By.XPATH, "//input[@type='file']")
                for file_input in reversed(inputs):
                    try:
                        file_input.send_keys(normalized_path)
                        time.sleep(1.0)
                        return True
                    except Exception:
                        continue
            except Exception:
                pass
            time.sleep(0.4)
        return False

    def _send_file_via_upload_label(self, driver, label_text: str, file_path: str) -> bool:
        normalized_path = str(Path(file_path).resolve())
        label_xpath = (
            f"//span[contains(normalize-space(),'{label_text}')]/ancestor::*[self::div or self::label][1]"
        )
        candidate_xpaths = [
            f"{label_xpath}//input[@type='file']",
            f"{label_xpath}/following::input[@type='file'][1]",
            f"{label_xpath}/preceding::input[@type='file'][1]",
            f"//input[@type='file' and contains(@accept,'image')]",
        ]
        for xpath in candidate_xpaths:
            try:
                elements = driver.find_elements(By.XPATH, xpath)
            except Exception:
                elements = []
            for element in reversed(elements):
                try:
                    element.send_keys(normalized_path)
                    time.sleep(0.8)
                    return True
                except Exception:
                    continue
        return False

    def _send_file_to_menu_context_input(self, driver, menu_item, file_path: str) -> bool:
        normalized_path = str(Path(file_path).resolve())
        candidate_lists = []
        try:
            candidate_lists.append(menu_item.find_elements(By.XPATH, ".//input[@type='file']"))
        except Exception:
            pass
        try:
            menu_root = driver.execute_script(
                "return arguments[0].closest('[role=\"menu\"]') || arguments[0].closest('[role=\"dialog\"]');",
                menu_item,
            )
            if menu_root is not None:
                candidate_lists.append(menu_root.find_elements(By.XPATH, ".//input[@type='file']"))
        except Exception:
            pass
        try:
            candidate_lists.append(menu_item.find_elements(By.XPATH, "./ancestor::*[@role='menu'][1]//input[@type='file']"))
        except Exception:
            pass
        try:
            candidate_lists.append(
                menu_item.find_elements(By.XPATH, "./ancestor::*[@role='dialog'][1]//input[@type='file']")
            )
        except Exception:
            pass

        for elements in candidate_lists:
            for element in reversed(elements):
                try:
                    driver.execute_script(
                        "arguments[0].style.display='block';arguments[0].style.visibility='visible';arguments[0].style.opacity='1';",
                        element,
                    )
                    element.send_keys(normalized_path)
                    time.sleep(0.8)
                    return True
                except Exception:
                    continue
        return False

    def _click_optional_save(self, driver) -> bool:
        return self._click_first(
            driver,
            [
                (By.XPATH, "//span[normalize-space()='Save']/ancestor::div[@role='button'][1]"),
                (By.XPATH, "//span[normalize-space()='Save']/ancestor::button[1]"),
                (By.XPATH, "//div[@aria-label='Save']"),
                (By.XPATH, "//div[@role='button' and @aria-label='Save']"),
                (By.XPATH, "//div[@role='button' and .//span[normalize-space()='Save changes']]"),
            ],
            timeout_seconds=8,
        )

    def _set_profile_description(self, driver, description_text: str) -> bool:
        for _ in range(8):
            textarea_selectors = [
                (By.XPATH, "//textarea[@aria-label='Description']"),
                (By.XPATH, "//textarea[contains(@placeholder, 'Description')]"),
                (By.XPATH, "//textarea"),
            ]
            for by, locator in textarea_selectors:
                try:
                    field = WebDriverWait(driver, 2).until(EC.presence_of_element_located((by, locator)))
                    if not field.is_displayed():
                        continue
                    try:
                        field.clear()
                    except Exception:
                        pass
                    field.send_keys(description_text)
                    return True
                except Exception:
                    continue

            editable_selectors = [
                (By.XPATH, "//div[@role='textbox']"),
                (By.XPATH, "//div[@contenteditable='true']"),
            ]
            for by, locator in editable_selectors:
                try:
                    field = WebDriverWait(driver, 2).until(EC.presence_of_element_located((by, locator)))
                    if not field.is_displayed():
                        continue
                    driver.execute_script(
                        """
                        const el = arguments[0];
                        const text = arguments[1];
                        el.focus();
                        if (el.tagName && el.tagName.toLowerCase() === 'textarea') {
                            el.value = text;
                        } else {
                            el.textContent = text;
                        }
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        """,
                        field,
                        description_text,
                    )
                    return True
                except Exception:
                    continue
            time.sleep(0.4)
        return False

    def _click_cover_save_changes(self, driver) -> bool:
        """Click Save changes in cover editor with retries and enabled-state checks."""
        selectors = [
            (By.XPATH, "//span[normalize-space()='Save changes']/ancestor::*[@role='button'][1]"),
            (By.XPATH, "//button[.//span[normalize-space()='Save changes']]"),
            (By.XPATH, "//div[@aria-label='Save changes']"),
            (By.XPATH, "//span[normalize-space()='Save']/ancestor::*[@role='button'][1]"),
        ]
        for _ in range(5):
            for by, locator in selectors:
                elements = driver.find_elements(by, locator)
                for button in elements:
                    try:
                        if not button.is_displayed():
                            continue
                        if str(button.get_attribute("aria-disabled") or "").strip().lower() == "true":
                            continue
                        if str(button.get_attribute("disabled") or "").strip().lower() in {"true", "disabled"}:
                            continue
                        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", button)
                        try:
                            button.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", button)
                        time.sleep(0.7)
                        return True
                    except Exception:
                        continue
            time.sleep(0.6)
        return False

    def _wait_cover_editor_ready(self, driver) -> bool:
        """Wait until cover editor is active and Save changes is ready/clickable."""
        def editor_ready(_driver) -> bool:
            save_candidates = _driver.find_elements(
                By.XPATH,
                "//span[normalize-space()='Save changes']/ancestor::*[@role='button'][1]|"
                "//button[.//span[normalize-space()='Save changes']]|"
                "//div[@aria-label='Save changes']",
            )
            for button in save_candidates:
                try:
                    if not button.is_displayed():
                        continue
                    if str(button.get_attribute("aria-disabled") or "").strip().lower() == "true":
                        continue
                    return True
                except Exception:
                    continue

            # Some accounts show reposition text first before button becomes enabled.
            hints = _driver.find_elements(
                By.XPATH,
                "//*[contains(normalize-space(),'Drag or use arrow keys to reposition image')]",
            )
            return any(item.is_displayed() for item in hints)

        try:
            WebDriverWait(driver, 20).until(editor_ready)
            return True
        except Exception:
            return False

    def _finalize_profile_upload(self, driver) -> None:
        # After saving profile picture, Facebook can keep a transient modal state.
        # Give it a moment and dismiss "Leave page?" if it appears before cover step.
        time.sleep(1.0)
        self._dismiss_leave_page_prompt(driver)

    def _dismiss_leave_page_prompt(self, driver) -> None:
        self._click_first(
            driver,
            [
                (By.XPATH, "//span[normalize-space()='Leave Page']/ancestor::div[@role='button'][1]"),
                (By.XPATH, "//span[normalize-space()='Leave Page']/ancestor::button[1]"),
                (By.XPATH, "//span[normalize-space()='Discard']/ancestor::div[@role='button'][1]"),
                (By.XPATH, "//span[normalize-space()='Discard']/ancestor::button[1]"),
            ],
            timeout_seconds=2,
        )

    def clear_data(self, driver) -> None:
        try:
            driver.execute_script("window.open('');")
            driver.switch_to.window(driver.window_handles[-1])
            driver.get("about:preferences#privacy")
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "historySection")))
            driver.execute_script("document.getElementById('historySection').scrollIntoView();")
            driver.execute_script(
                """
                document.querySelector("button[data-l10n-id='clear-data-button']").click();
                document.querySelector("input[data-id='cache']").checked = true;
                document.querySelector("input[data-id='cookies']").checked = false;
                """
            )
            driver.execute_script(
                "document.querySelector('dialog[open] button[data-l10n-id=\"clear-data-button\"]').click();"
            )
            logging.info("Cleared temporary cached files and pages, kept cookies.")
        except Exception as exc:
            logging.error("Error clearing data: %s", exc)

    def save_cookies(self, driver, instance_number: int) -> None:
        logging.info("Cookie export is disabled. Firefox %s cookies were not saved.", instance_number)

    def load_cookies(self, driver, instance_number: int) -> None:
        logging.info("Cookie import/injection is disabled. Firefox %s cookies were not loaded.", instance_number)

    def delete_cookie_file(self, instance_number: int) -> None:
        cookie_file = self._cookie_file(instance_number)
        if cookie_file.exists():
            cookie_file.unlink()

    def try_sync_profile_preview(self, instance_number: int) -> None:
        driver = self.state.drivers.get(instance_number)
        if not driver:
            self.app.instances.set_preview_status(instance_number, "Browser not running", WARNING)
            return

        if not self._is_logged_in(driver):
            self.app.instances.set_preview_status(instance_number, "Login required", WARNING)
            return

        original_url = driver.current_url
        self.app.instances.set_preview_status(instance_number, "Refreshing...", WARNING)
        try:
            avatar_image, cover_image, profile_name = self._capture_profile_media(driver)
            if not cover_image and not avatar_image:
                self.app.instances.set_preview_status(instance_number, "No preview found", WARNING)
                return

            cover_path = cover_image_path(instance_number)
            avatar_path = avatar_image_path(instance_number)

            if avatar_image:
                avatar_image.save(avatar_path)
                logging.info(
                    "Avatar downloaded size: %sx%s",
                    avatar_image.width,
                    avatar_image.height,
                )
            elif avatar_path.exists():
                avatar_path.unlink()
            if cover_image:
                cover_image.save(cover_path)
            elif cover_path.exists():
                cover_path.unlink()
            if profile_name:
                self.app.instances.set_profile_name(instance_number, profile_name)
            self._sync_profile_identity_from_driver(instance_number, driver, restore_url=True)
            self._save_profile_screenshot(driver, instance_number, profile_name)

            self.app.instances.reload_instance_image(instance_number)
            self.app.instances.set_preview_timestamp(instance_number)
            logging.info("Profile preview synced for Firefox %s.", instance_number)
        except Exception as exc:
            self.app.instances.set_preview_status(instance_number, "Refresh failed", WARNING)
            logging.debug("Could not sync profile preview for Firefox %s: %s", instance_number, exc)
        finally:
            try:
                if original_url and driver.current_url != original_url:
                    driver.get(original_url)
            except Exception:
                pass

    def _cookie_file(self, instance_number: int) -> Path:
        platform = self.app.vars.platform_var.get()
        return cookie_dir_for_platform(platform) / f"cookies_{instance_number}.json"

    def _is_logged_in(self, driver) -> bool:
        current_url = str(driver.current_url or "").lower()
        if "login" in current_url or "checkpoint" in current_url:
            return False
        return not driver.find_elements(By.ID, "email")

    def _start_manual_login_monitor(
        self,
        instance_number: int,
        delay_seconds: int = 5,
        timeout_seconds: int = 180,
        poll_seconds: int = 3,
    ) -> None:
        token = self.state.preview_monitor_tokens.get(instance_number, 0) + 1
        self.state.preview_monitor_tokens[instance_number] = token

        def monitor() -> None:
            deadline = time.time() + timeout_seconds
            while time.time() < deadline:
                if self.state.preview_monitor_tokens.get(instance_number) != token:
                    return

                driver = self.state.drivers.get(instance_number)
                if not driver:
                    return

                try:
                    if self._is_logged_in(driver):
                        if self.state.preview_monitor_tokens.get(instance_number) != token:
                            return
                        self.app.instances.set_preview_status(instance_number, "Login detected. Refreshing soon...", TEXT_MUTED)
                        self.app.instances.set_run_status(instance_number, "Login detected", SUCCESS)
                        time.sleep(delay_seconds)
                        if self.state.preview_monitor_tokens.get(instance_number) != token:
                            return
                        driver = self.state.drivers.get(instance_number)
                        if driver and self._is_logged_in(driver):
                            self.try_sync_profile_preview(instance_number)
                            self._sync_profile_identity_from_driver(instance_number, driver, restore_url=True)
                            self.app.instances.check_live_instance(instance_number, self.app.vars.platform_var.get())
                        return
                except Exception as exc:
                    logging.debug("Manual login monitor error for Firefox %s: %s", instance_number, exc)

                time.sleep(poll_seconds)

            if self.state.preview_monitor_tokens.get(instance_number) == token:
                self.app.instances.set_preview_status(instance_number, "Login not detected", WARNING)
                self.app.instances.set_run_status(instance_number, "Login timeout", WARNING)
                self.app.instances.set_account_health(
                    instance_number,
                    "Login required",
                    "Login was not detected before the monitor timed out.",
                )

        threading.Thread(target=monitor, daemon=True).start()

    def _start_identity_refresh_monitor(
        self,
        instance_number: int,
        timeout_seconds: int = 180,
        poll_seconds: int = 8,
    ) -> None:
        token = self.state.preview_monitor_tokens.get(instance_number, 0) + 1
        self.state.preview_monitor_tokens[instance_number] = token

        def monitor() -> None:
            deadline = time.time() + timeout_seconds
            while time.time() < deadline:
                if self.state.preview_monitor_tokens.get(instance_number) != token:
                    return

                driver = self.state.drivers.get(instance_number)
                if not driver:
                    return

                if self._is_logged_in(driver):
                    if self._sync_profile_identity_from_current_page(instance_number, driver):
                        self.app.instances.set_run_status(instance_number, "Identity synced", SUCCESS)

                time.sleep(poll_seconds)

        threading.Thread(target=monitor, daemon=True).start()

    def _capture_profile_media(self, driver) -> tuple[Image.Image | None, Image.Image | None, str | None]:
        driver.get("https://www.facebook.com/profile.php?id")
        WebDriverWait(driver, 12).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='main']")))
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(3)

        profile_name_element = self._find_profile_name_element(driver)
        profile_name = profile_name_element.text.strip() if profile_name_element else None

        header_media = self._extract_profile_header_media(driver, profile_name_element)
        avatar_image = self._download_best_facebook_image_with_session(
            driver,
            header_media.get("avatar_url"),
            media_kind="avatar",
        )
        cover_image = self._download_best_facebook_image_with_session(
            driver,
            header_media.get("cover_url"),
            media_kind="cover",
        )

        if not profile_name or self._looks_generic_name(profile_name):
            profile_name = header_media.get("name") or None

        return avatar_image, cover_image, profile_name

    def _find_profile_name_element(self, driver):
        candidates = []
        for element in driver.find_elements(By.CSS_SELECTOR, "div[role='main'] h1, div[role='main'] [role='heading']"):
            try:
                if not element.is_displayed():
                    continue
                text = element.text.strip()
                rect = element.rect
                top = rect.get("y", rect.get("top", 0))
                if not text or top < 80 or top > 900:
                    continue
                score = 0
                if element.tag_name.lower() == "h1":
                    score += 1000
                score += min(len(text), 80) * 10
                score -= int(top)
                candidates.append((score, element))
            except Exception:
                continue

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _find_avatar_element(self, driver, profile_name_element):
        images = driver.find_elements(By.CSS_SELECTOR, "div[role='main'] img")
        candidates = []
        name_rect = profile_name_element.rect if profile_name_element is not None else None

        for image in images:
            try:
                if not image.is_displayed():
                    continue
                rect = image.rect
                width = rect.get("width", 0)
                height = rect.get("height", 0)
                top = rect.get("y", rect.get("top", 0))
                left = rect.get("x", rect.get("left", 0))
                if width < 110 or height < 110:
                    continue
                if abs(width - height) > 90:
                    continue
                if top < 320 or top > 1150 or left > 520:
                    continue

                area = width * height
                score = area
                if name_rect:
                    name_left = name_rect.get("x", name_rect.get("left", 0))
                    name_top = name_rect.get("y", name_rect.get("top", 0))
                    name_height = name_rect.get("height", 0)
                    dx = name_left - (left + width)
                    dy = abs((top + (height / 2)) - (name_top + (name_height / 2)))
                    if -80 <= dx <= 260:
                        score += 200000 - int(abs(dx) * 500)
                    if dy <= 260:
                        score += 120000 - int(dy * 300)
                candidates.append((score, image))
            except Exception:
                continue

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _find_cover_element(self, driver, profile_name_element):
        images = driver.find_elements(By.CSS_SELECTOR, "div[role='main'] img")
        candidates = []
        name_top = None
        if profile_name_element is not None:
            try:
                name_top = profile_name_element.rect.get("y", profile_name_element.rect.get("top", 0))
            except Exception:
                name_top = None

        for image in images:
            try:
                if not image.is_displayed():
                    continue
                rect = image.rect
                width = rect.get("width", 0)
                height = rect.get("height", 0)
                top = rect.get("y", rect.get("top", 0))
                left = rect.get("x", rect.get("left", 0))
                if width < 420 or height < 120:
                    continue
                if top > 520 or left > 320:
                    continue
                score = width * height
                if name_top is not None and top < name_top:
                    score += 150000
                candidates.append((score, image))
            except Exception:
                continue

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _element_screenshot(self, element) -> Image.Image | None:
        if element is None:
            return None
        try:
            png = element.screenshot_as_png
            return Image.open(BytesIO(png)).convert("RGB")
        except Exception as exc:
            logging.debug("Element screenshot failed: %s", exc)
            return None

    def _capture_avatar_element_image(self, driver, profile_name_element) -> Image.Image | None:
        name_text = profile_name_element.text.strip() if profile_name_element is not None else ""
        avatar_rect = driver.execute_script(
            """
            const headingText = arguments[0] || "";
            const svgHref = (node) => (
              node.getAttribute("href") ||
              node.getAttribute("xlink:href") ||
              node.getAttributeNS("http://www.w3.org/1999/xlink", "href") ||
              ""
            );
            const isVisible = (el) => {
              if (!el) return false;
              const rect = el.getBoundingClientRect();
              const style = window.getComputedStyle(el);
              return rect.width > 40 && rect.height > 40 && rect.bottom > 0 && rect.right > 0 && style.visibility !== "hidden" && style.display !== "none";
            };
            const rectData = (rect) => ({
              left: rect.left,
              top: rect.top,
              right: rect.right,
              bottom: rect.bottom,
              width: rect.width,
              height: rect.height
            });

            const main = document.querySelector("div[role='main']");
            if (!main) return null;

            const heading = [...main.querySelectorAll("h1, [role='heading'], div[role='button'], a[role='link'], a")]
              .find((el) => isVisible(el) && (el.innerText || "").trim() === headingText);
            const headingRect = heading ? heading.getBoundingClientRect() : null;
            const cover = [...main.querySelectorAll("img[data-imgperflogname='profileCoverPhoto']")].find((el) => isVisible(el));
            const coverRect = cover ? cover.getBoundingClientRect() : null;

            const candidates = [
              ...[...main.querySelectorAll("img")].map((node) => ({ el: node, rect: node.getBoundingClientRect(), kind: "img-direct", src: node.currentSrc || node.src || "", alt: (node.getAttribute("alt") || "").toLowerCase() })),
              ...[...main.querySelectorAll("svg image")].map((node) => ({ el: node, rect: node.getBoundingClientRect(), kind: "svg-image", src: svgHref(node) })),
              ...[...main.querySelectorAll("svg")].map((node) => ({ el: node, rect: node.getBoundingClientRect(), kind: "svg", src: "" })),
            ].filter((item) => {
              if (!isVisible(item.el)) return false;
              const { width, height, left } = item.rect;
              if (width < 110 || height < 110 || width > 260 || height > 260) return false;
              if (Math.abs(width - height) > 45) return false;
              if (left > window.innerWidth * 0.35) return false;
              return true;
            }).map((item) => {
              let score = item.rect.width * item.rect.height;
              if (item.kind === "img-direct") score += 260000;
              if (item.kind === "svg-image") score += 300000;
              if (item.kind === "svg") score += 120000;
              if (
                item.kind === "img-direct" &&
                item.el.getAttribute("data-visualcompletion") === "media-vc-image" &&
                item.el.getAttribute("referrerpolicy") === "origin-when-cross-origin"
              ) {
                score += 400000;
              }
              if (item.kind === "img-direct" && (item.alt.includes("may be an image") || item.alt.includes("child") || item.alt.includes("smiling"))) {
                score += 80000;
              }

              if (coverRect) {
                const dxCover = Math.abs(item.rect.left - (coverRect.left + 24));
                if (dxCover > 320) {
                  return null;
                }
                score += 160000 - dxCover * 350;
              }
              if (headingRect) {
                const dx = headingRect.left - item.rect.right;
                const dy = Math.abs((item.rect.top + item.rect.height / 2) - (headingRect.top + headingRect.height / 2));
                if (dx < -60 || dx > 320 || dy > 220) {
                  return null;
                }
                score += 90000 - Math.abs(dx) * 300;
                score += 60000 - dy * 200;
              }
              return { score, rect: rectData(item.rect) };
            }).filter(Boolean).sort((a, b) => b.score - a.score);

            return candidates.length ? candidates[0].rect : null;
            """,
            name_text,
        )

        viewport_image = self._viewport_screenshot(driver)
        viewport_size = self._viewport_size(driver)
        return self._crop_viewport_rect(viewport_image, avatar_rect, viewport_size, padding=6)

    def _viewport_screenshot(self, driver) -> Image.Image | None:
        try:
            return Image.open(BytesIO(driver.get_screenshot_as_png())).convert("RGB")
        except Exception as exc:
            logging.debug("Viewport screenshot failed: %s", exc)
            return None

    def _viewport_size(self, driver) -> tuple[float, float]:
        try:
            width, height = driver.execute_script("return [window.innerWidth || 0, window.innerHeight || 0];")
            return float(width or 0), float(height or 0)
        except Exception as exc:
            logging.debug("Viewport size lookup failed: %s", exc)
            return 0.0, 0.0

    def _crop_viewport_rect(
        self,
        image: Image.Image | None,
        rect: object,
        viewport_size: tuple[float, float],
        padding: int = 0,
    ) -> Image.Image | None:
        if image is None or not isinstance(rect, dict):
            return None
        try:
            viewport_width, viewport_height = viewport_size
            scale_x = image.width / viewport_width if viewport_width > 0 else 1.0
            scale_y = image.height / viewport_height if viewport_height > 0 else 1.0

            left = (float(rect.get("left", 0)) - padding) * scale_x
            top = (float(rect.get("top", 0)) - padding) * scale_y
            right = (float(rect.get("right", rect.get("left", 0) + rect.get("width", 0))) + padding) * scale_x
            bottom = (float(rect.get("bottom", rect.get("top", 0) + rect.get("height", 0))) + padding) * scale_y

            left = max(0, math.floor(left))
            top = max(0, math.floor(top))
            right = min(image.width, math.ceil(right))
            bottom = min(image.height, math.ceil(bottom))
            if right - left < 40 or bottom - top < 40:
                return None
            return image.crop((left, top, right, bottom)).convert("RGB")
        except Exception as exc:
            logging.debug("Viewport crop failed: %s", exc)
            return None

    def _extract_profile_header_media(self, driver, profile_name_element) -> dict[str, object]:
        name_text = profile_name_element.text.strip() if profile_name_element is not None else ""
        return driver.execute_script(
            """
            const headingText = arguments[0] || "";
            const extractBackgroundUrl = (value) => {
              const match = /url\\(["']?(.*?)["']?\\)/.exec(value || "");
              return match ? match[1] : "";
            };
            const svgImageHref = (node) => {
              if (!node) return "";
              return (
                node.getAttribute("href") ||
                node.getAttribute("xlink:href") ||
                node.getAttributeNS("http://www.w3.org/1999/xlink", "href") ||
                ""
              );
            };
            const bestSrc = (img) => {
              const entries = [];
              const srcset = img.getAttribute("srcset") || "";
              for (const chunk of srcset.split(",")) {
                const part = chunk.trim();
                if (!part) continue;
                const pieces = part.split(/\\s+/);
                const url = pieces[0] || "";
                const sizeToken = pieces[1] || "";
                const size = parseInt(sizeToken.replace(/[^0-9]/g, ""), 10) || 0;
                if (url) {
                  entries.push({ url, size });
                }
              }
              const current = img.currentSrc || img.src || "";
              if (current) {
                entries.push({ url: current, size: Math.max(img.naturalWidth || 0, img.naturalHeight || 0, 1) });
              }
              entries.sort((a, b) => b.size - a.size);
              return entries.length ? entries[0].url : current;
            };
            const normalizeName = (value) => (value || "").replace(/\\s+/g, " ").trim();
            const pageTitleName = () => {
              const title = normalizeName(document.title);
              if (!title) return "";
              const parts = title.split("|").map((part) => normalizeName(part)).filter(Boolean);
              const candidate = parts[0] || title;
              if (!candidate || /^\\(?\\d+\\)?\\s*facebook$/i.test(candidate) || /^facebook$/i.test(candidate)) {
                return "";
              }
              return candidate;
            };
            const metaName = () => {
              const meta = document.querySelector('meta[property="og:title"], meta[name="title"]');
              const value = meta ? normalizeName(meta.getAttribute("content") || "") : "";
              if (!value || /^\\(?\\d+\\)?\\s*facebook$/i.test(value) || /^facebook$/i.test(value)) {
                return "";
              }
              return value;
            };
            const genericNames = new Set([
              "facebook",
              "notifications",
              "dashboard",
              "edit",
              "friends",
              "followers",
              "following",
              "about",
              "all",
              "posts",
              "photos",
              "videos",
              "reels",
              "more"
            ]);
            const validName = (value) => {
              const normalized = normalizeName(value);
              if (!normalized) return "";
              if (genericNames.has(normalized.toLowerCase())) return "";
              if (/^\\(?\\d+\\)?\\s*facebook$/i.test(normalized)) return "";
              return normalized;
            };

            const isVisible = (el) => {
              if (!el) return false;
              const style = window.getComputedStyle(el);
              if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity || 1) === 0) {
                return false;
              }
              const rect = el.getBoundingClientRect();
              return rect.width > 40 && rect.height > 40 && rect.bottom > 0 && rect.right > 0;
            };
            const isVisibleGraphic = (el) => {
              if (!el) return false;
              const rect = el.getBoundingClientRect();
              return rect.width > 40 && rect.height > 40 && rect.bottom > 0 && rect.right > 0;
            };

            const main = document.querySelector("div[role='main']");
            if (!main) {
                const fallbackName = validName(headingText) || metaName() || pageTitleName();
                return { name: fallbackName, avatar_url: "", cover_url: "" };
            }

            const h1s = [...main.querySelectorAll("h1")]
              .filter((el) => isVisible(el) && (el.innerText || "").trim());
            const headings = [...main.querySelectorAll("[role='heading']")]
              .filter((el) => isVisible(el) && (el.innerText || "").trim());
            const buttonNames = [...main.querySelectorAll("div[role='button'], a[role='link'], a")]
              .filter((el) => {
                if (!isVisible(el)) return false;
                const text = validName(el.innerText || "");
                if (!text) return false;
                const rect = el.getBoundingClientRect();
                return rect.top > 80 && rect.top < window.innerHeight && rect.left < window.innerWidth * 0.7;
              });

            let heading = null;
            if (headingText && validName(headingText)) {
              heading = h1s.find((el) => normalizeName(el.innerText || "") === normalizeName(headingText)) || null;
            }
            if (!heading) {
              heading = h1s
                .filter((el) => {
                  const rect = el.getBoundingClientRect();
                  return rect.top > 80 && rect.top < window.innerHeight;
                })
                .sort((a, b) => {
                  const aRect = a.getBoundingClientRect();
                  const bRect = b.getBoundingClientRect();
                  const aScore = ((a.innerText || "").trim().length * 20) - aRect.top;
                  const bScore = ((b.innerText || "").trim().length * 20) - bRect.top;
                  return bScore - aScore;
                })[0] || null;
            }
            if (!heading) {
              heading = headings
                .filter((el) => {
                  const text = validName(el.innerText || "");
                  const rect = el.getBoundingClientRect();
                  return !!text && rect.top > 80 && rect.top < window.innerHeight;
                })
                .sort((a, b) => {
                  const aRect = a.getBoundingClientRect();
                  const bRect = b.getBoundingClientRect();
                  const aScore = ((a.innerText || "").trim().length * 10) - aRect.top;
                  const bScore = ((b.innerText || "").trim().length * 10) - bRect.top;
                  return bScore - aScore;
                })[0] || null;
            }
            if (!heading) {
              heading = buttonNames
                .sort((a, b) => {
                  const aRect = a.getBoundingClientRect();
                  const bRect = b.getBoundingClientRect();
                  const aText = validName(a.innerText || "");
                  const bText = validName(b.innerText || "");
                  const aScore = (aText.length * 25) - (aRect.top * 2) - aRect.left;
                  const bScore = (bText.length * 25) - (bRect.top * 2) - bRect.left;
                  return bScore - aScore;
                })[0] || null;
            }

            const headingRect = heading ? heading.getBoundingClientRect() : null;
            let resolvedName = validName(heading ? (heading.innerText || "") : "") || validName(headingText) || metaName() || pageTitleName();
            const directCoverElement = [...main.querySelectorAll("img[data-imgperflogname='profileCoverPhoto']")]
              .find((img) => isVisible(img) && !!bestSrc(img));
            const directAvatarActionImage = [
              ...main.querySelectorAll("svg[aria-label='Profile picture actions'] image"),
              ...main.querySelectorAll("svg[aria-label='Profile picture'] image"),
              ...main.querySelectorAll("[aria-label='Profile picture actions'] image"),
              ...main.querySelectorAll("[aria-label='Profile picture'] image")
            ]
              .map((node) => {
                const rect = node.getBoundingClientRect();
                const src = svgImageHref(node);
                if (!isVisibleGraphic(node) || !src) return null;
                return { score: 5000000 + (rect.width * rect.height), src, rect };
              })
              .filter(Boolean)
              .sort((a, b) => b.score - a.score)[0] || null;
            const images = [...main.querySelectorAll("img")].filter((img) => {
              if (!isVisible(img) || !img.complete) return false;
              const rect = img.getBoundingClientRect();
              const src = img.currentSrc || img.src || "";
              return rect.width >= 60 && rect.height >= 60 && !!src;
            });
            const svgImages = [...main.querySelectorAll("svg image")]
              .map((node) => {
                const rect = node.getBoundingClientRect();
                const src = svgImageHref(node);
                if (!isVisibleGraphic(node) || !src) return null;
                return { node, rect, src };
              })
              .filter(Boolean);

            const coverCandidates = [];

            if (directCoverElement) {
              const rect = directCoverElement.getBoundingClientRect();
              coverCandidates.push({
                score: 10000000 + (rect.width * rect.height),
                src: bestSrc(directCoverElement),
                rect,
              });
            }

            for (const img of images) {
              const rect = img.getBoundingClientRect();
              if (rect.width < Math.min(700, window.innerWidth * 0.6) || rect.height < 180) {
                continue;
              }
              if (rect.top > 220 || rect.left > window.innerWidth * 0.25) {
                continue;
              }
              if ((rect.width / Math.max(rect.height, 1)) < 1.8) {
                continue;
              }

              let score = rect.width * rect.height;
              const naturalWidth = img.naturalWidth || rect.width;
              const naturalHeight = img.naturalHeight || rect.height;
              if (headingRect) {
                if (rect.bottom < headingRect.top + 30) {
                  score += 200000;
                } else {
                  score -= 150000;
                }
                score += Math.max(0, 120 - rect.top) * 1200;
              }
              if (naturalWidth < 700 || naturalHeight < 200) {
                score -= 250000;
              }
              score += naturalWidth * 10;
              score += naturalHeight * 4;
              if (headingRect && rect.left <= headingRect.left + 60) {
                score += 35000;
              }
              coverCandidates.push({ score, src: bestSrc(img), rect });
            }

            const backgroundCandidates = [...main.querySelectorAll("div")]
              .map((el) => {
                if (!isVisible(el)) return null;
                const rect = el.getBoundingClientRect();
                const backgroundUrl = extractBackgroundUrl(window.getComputedStyle(el).backgroundImage);
                if (!backgroundUrl) return null;
                if (rect.width < Math.min(700, window.innerWidth * 0.6) || rect.height < 180) return null;
                if (rect.top > 220 || rect.left > window.innerWidth * 0.25) return null;
                if ((rect.width / Math.max(rect.height, 1)) < 1.8) return null;

                let score = rect.width * rect.height;
                if (headingRect && rect.bottom < headingRect.top + 30) {
                  score += 150000;
                }
                score -= 40000;
                return { score, src: backgroundUrl, rect };
              })
              .filter(Boolean);

            coverCandidates.push(...backgroundCandidates);
            coverCandidates.sort((a, b) => b.score - a.score);

            const chosenCover = coverCandidates[0] || null;
            const coverRect = chosenCover ? chosenCover.rect : null;
            const directAvatarHeaderImg = images
              .map((img) => {
                const rect = img.getBoundingClientRect();
                const width = rect.width;
                const height = rect.height;
                const alt = normalizeName(img.getAttribute("alt") || "");
                const visual = (img.getAttribute("data-visualcompletion") || "").toLowerCase();
                const referrer = (img.getAttribute("referrerpolicy") || "").toLowerCase();
                if (visual !== "media-vc-image" || referrer !== "origin-when-cross-origin") {
                  return null;
                }
                if (width < 130 || height < 130 || Math.abs(width - height) > 30) {
                  return null;
                }
                if (width > 220 || height > 220) {
                  return null;
                }
                if (rect.left > window.innerWidth * 0.3 || rect.top < 180 || rect.top > window.innerHeight) {
                  return null;
                }

                let score = 1800000 + (width * height);
                if (coverRect) {
                  const dxCover = Math.abs(rect.left - (coverRect.left + 24));
                  if (dxCover > 320) {
                    return null;
                  }
                  score += 180000 - (dxCover * 400);
                }
                if (headingRect) {
                  const dx = headingRect.left - rect.right;
                  const dy = Math.abs((rect.top + height / 2) - (headingRect.top + headingRect.height / 2));
                  if (dx < -60 || dx > 320 || dy > 220) {
                    return null;
                  }
                  score += 110000 - (Math.abs(dx) * 250);
                  score += 70000 - (dy * 180);
                }
                if (alt.includes("may be an image") || alt.includes("child") || alt.includes("smiling")) {
                  score += 100000;
                }
                return { score, src: bestSrc(img), rect };
              })
              .filter(Boolean)
              .sort((a, b) => b.score - a.score)[0] || null;
            const directAvatarImgCandidate = images
              .map((img) => {
                const rect = img.getBoundingClientRect();
                const width = rect.width;
                const height = rect.height;
                const alt = normalizeName(img.getAttribute("alt") || "");
                if (width < 130 || height < 130 || Math.abs(width - height) > 30) {
                  return null;
                }
                if (width > 220 || height > 220) {
                  return null;
                }
                if (rect.left > window.innerWidth * 0.3) {
                  return null;
                }
                if (coverRect) {
                  if (rect.left > coverRect.left + 280) {
                    return null;
                  }
                }

                let score = 1200000 + (width * height);
                if (coverRect) {
                  score += 180000 - (Math.abs(rect.left - (coverRect.left + 24)) * 400);
                }
                if (headingRect) {
                  score += 120000 - (Math.abs(headingRect.left - rect.right) * 250);
                }
                if (alt.includes("may be an image") || alt.includes("child") || alt.includes("smiling")) {
                  score += 80000;
                }
                return { score, src: bestSrc(img), rect };
              })
              .filter(Boolean)
              .sort((a, b) => b.score - a.score)[0] || null;
            const directAvatarCandidate = svgImages
              .map((item) => {
                const rect = item.rect;
                const width = rect.width;
                const height = rect.height;
                if (width < 130 || height < 130 || Math.abs(width - height) > 30) {
                  return null;
                }
                if (width > 220 || height > 220) {
                  return null;
                }
                if (rect.left > window.innerWidth * 0.3) {
                  return null;
                }
                if (coverRect) {
                  if (rect.left > coverRect.left + 280) {
                    return null;
                  }
                }

                let score = 1000000 + (width * height);
                if (coverRect) {
                  score += 180000 - (Math.abs(rect.left - (coverRect.left + 24)) * 400);
                }
                if (headingRect) {
                  score += 120000 - (Math.abs(headingRect.left - rect.right) * 250);
                }
                return { score, src: item.src, rect };
              })
              .filter(Boolean)
              .sort((a, b) => b.score - a.score)[0] || null;
            const avatarCandidates = images
              .map((img) => {
                const rect = img.getBoundingClientRect();
                const width = rect.width;
                const height = rect.height;
                if (width < 110 || height < 110 || Math.abs(width - height) > 50) {
                  return null;
                }
                if (width > 320 || height > 320) {
                  return null;
                }
                if (rect.left > window.innerWidth * 0.35) {
                  return null;
                }

                let score = width * height;
                const src = bestSrc(img);
                const alt = normalizeName(img.getAttribute("alt") || "");
                const style = window.getComputedStyle(img);
                const borderRadius = parseFloat(style.borderTopLeftRadius || "0") || 0;
                const naturalWidth = img.naturalWidth || width;
                const naturalHeight = img.naturalHeight || height;

                if (coverRect) {
                  const dxCover = Math.abs(rect.left - (coverRect.left + 24));
                  if (dxCover > 320) {
                    return null;
                  }
                  score += 160000 - (dxCover * 400);
                }

                if (headingRect) {
                  const dxName = headingRect.left - rect.right;
                  const dyName = Math.abs((rect.top + height / 2) - (headingRect.top + headingRect.height / 2));
                  if (dxName < -40 || dxName > 280) {
                    return null;
                  }
                  if (dyName > 180) {
                    return null;
                  }
                  score += 180000 - (Math.abs(dxName) * 450);
                  score += 120000 - (dyName * 350);
                }

                if (alt && resolvedName && (alt.includes(resolvedName) || resolvedName.includes(alt))) {
                  score += 220000;
                }
                if (borderRadius >= Math.min(width, height) / 4) {
                  score += 90000;
                }
                score += naturalWidth * 12;
                score += naturalHeight * 8;
                return { score, src, rect };
              })
              .filter(Boolean);

            const svgAvatarCandidates = svgImages
              .map((item) => {
                const rect = item.rect;
                const width = rect.width;
                const height = rect.height;
                if (width < 110 || height < 110 || Math.abs(width - height) > 60) {
                  return null;
                }
                if (width > 320 || height > 320) {
                  return null;
                }
                if (rect.left > window.innerWidth * 0.35) {
                  return null;
                }

                let score = width * height + 250000;
                if (coverRect) {
                  const dxCover = Math.abs(rect.left - (coverRect.left + 24));
                  if (dxCover > 320) {
                    return null;
                  }
                  score += 180000 - (dxCover * 400);
                }
                if (headingRect) {
                  const dxName = headingRect.left - rect.right;
                  const dyName = Math.abs((rect.top + height / 2) - (headingRect.top + headingRect.height / 2));
                  if (dxName < -40 || dxName > 280) {
                    return null;
                  }
                  if (dyName > 180) {
                    return null;
                  }
                  score += 180000 - (Math.abs(dxName) * 450);
                  score += 120000 - (dyName * 350);
                }
                return { score, src: item.src, rect };
              })
              .filter(Boolean)
              .sort((a, b) => b.score - a.score);

            const headerAvatarCandidates = [...svgAvatarCandidates, ...avatarCandidates]
              .filter((candidate) => {
                const rect = candidate.rect;
                if (!coverRect) {
                  return rect.left < window.innerWidth * 0.3;
                }
                return (
                  rect.left < Math.min(window.innerWidth * 0.3, coverRect.left + 260) &&
                  (!headingRect || (
                    rect.bottom >= headingRect.top - 220 &&
                    rect.top <= headingRect.bottom + 220
                  ))
                );
              })
              .sort((a, b) => b.score - a.score);

            avatarCandidates.sort((a, b) => b.score - a.score);

            const chosenAvatar = directAvatarActionImage || directAvatarHeaderImg || directAvatarImgCandidate || directAvatarCandidate || headerAvatarCandidates[0] || svgAvatarCandidates[0] || avatarCandidates[0] || null;
            if ((!resolvedName || !validName(resolvedName)) && chosenAvatar) {
              const avatarRect = chosenAvatar.rect;
              const nearbyNames = [...main.querySelectorAll("h1, [role='heading'], span, strong, div[role='button'], a[role='link'], a")]
                .filter((el) => isVisible(el))
                .map((el) => {
                  const text = validName(el.innerText || "");
                  if (!text) return null;
                  const rect = el.getBoundingClientRect();
                  if (rect.left < avatarRect.right - 40 || rect.left > avatarRect.right + 420) return null;
                  if (rect.top < avatarRect.top - 40 || rect.top > avatarRect.bottom + 200) return null;
                  let score = 100000 - Math.abs(rect.left - avatarRect.right) * 200 - Math.abs(rect.top - avatarRect.top) * 120;
                  if (el.tagName === "H1") score += 50000;
                  if ((el.getAttribute("role") || "").toLowerCase() === "button") score += 35000;
                  if (el.tagName === "A") score += 25000;
                  score += text.length * 100;
                  return { text, score };
                })
                .filter(Boolean)
                .sort((a, b) => b.score - a.score);
              resolvedName = nearbyNames[0] ? nearbyNames[0].text : resolvedName;
            }

            if (!resolvedName || !validName(resolvedName)) {
              const buttonName = buttonNames
                .map((el) => {
                  const rect = el.getBoundingClientRect();
                  const text = validName(el.innerText || "");
                  if (!text) return null;
                  let score = 100000 - (rect.top * 2) - rect.left;
                  score += text.length * 120;
                  if ((el.getAttribute("role") || "").toLowerCase() === "button") score += 30000;
                  return { text, score };
                })
                .filter(Boolean)
                .sort((a, b) => b.score - a.score)[0];
              resolvedName = buttonName ? buttonName.text : resolvedName;
            }

            let avatarUrl = chosenAvatar ? chosenAvatar.src : "";
            let coverUrl = coverCandidates[0] ? coverCandidates[0].src : "";

            if (avatarUrl && coverUrl && avatarUrl === coverUrl) {
              coverUrl = coverCandidates.find((candidate) => candidate.src && candidate.src !== avatarUrl)?.src || "";
            }

            return {
              name: validName(resolvedName),
              avatar_url: avatarUrl,
              cover_url: coverUrl,
              avatar_rect: chosenAvatar ? chosenAvatar.rect : null,
              cover_rect: chosenCover ? chosenCover.rect : null
            };
            """,
            name_text,
        )

    def _looks_generic_name(self, value: str) -> bool:
        normalized = re.sub(r"\s+", " ", (value or "").strip()).lower()
        if not normalized:
            return True
        if normalized in {
            "facebook",
            "dashboard",
            "edit",
            "notifications",
            "friends",
            "followers",
            "following",
            "about",
            "all",
            "posts",
            "photos",
            "videos",
            "reels",
            "more",
        }:
            return True
        if re.fullmatch(r"\(?\d+\)?\s*facebook", normalized):
            return True
        return False

    def _is_probable_avatar_image(self, image: Image.Image | None) -> bool:
        if image is None:
            return False
        width, height = image.size
        if width < 80 or height < 80:
            return False
        ratio = width / max(height, 1)
        return 0.75 <= ratio <= 1.25

    def _is_probable_cover_image(self, image: Image.Image | None) -> bool:
        if image is None:
            return False
        width, height = image.size
        if width < 300 or height < 120:
            return False
        ratio = width / max(height, 1)
        return ratio >= 1.6

    def _download_image_with_session(self, driver, url: str | None) -> Image.Image | None:
        if not url:
            return None

        browser_image = self._download_image_via_browser(driver, url)
        if browser_image is not None:
            return browser_image

        try:
            normalized_url = unescape(url)
            headers = {
                "User-Agent": driver.execute_script("return navigator.userAgent;"),
                "Referer": driver.current_url,
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            }
            request = Request(normalized_url, headers=headers)
            with urlopen(request, timeout=20) as response:
                data = response.read()
            return Image.open(BytesIO(data)).convert("RGB")
        except Exception as exc:
            logging.debug("Image download failed for %s: %s", url, exc)
            return None

    def _download_best_facebook_image_with_session(
        self,
        driver,
        url: object,
        media_kind: str = "image",
    ) -> Image.Image | None:
        if not url:
            return None

        best_image = None
        best_score: tuple[int, int, int] | None = None
        source_urls: list[str] = []
        if isinstance(url, str):
            source_urls = [url]
        elif isinstance(url, (list, tuple, set)):
            source_urls = [value for value in url if isinstance(value, str) and value.strip()]

        seen_source_urls: set[str] = set()
        for source_url in source_urls:
            if source_url in seen_source_urls:
                continue
            seen_source_urls.add(source_url)
            for candidate_url in self._facebook_image_url_candidates(source_url, media_kind=media_kind):
                image = self._download_image_with_session(driver, candidate_url)
                if image is None:
                    continue
                score = self._facebook_image_score(image, media_kind=media_kind)
                if best_score is None or score > best_score:
                    best_image = image
                    best_score = score
        return best_image

    def _facebook_image_score(self, image: Image.Image, media_kind: str = "image") -> tuple[int, int, int]:
        width, height = image.size
        area = width * height
        if media_kind == "avatar":
            distance = abs(width - 960) + abs(height - 960)
            exact_match = 1 if width == 960 and height == 960 else 0
            return (exact_match, -distance, area)
        return (0, 0, area)

    def _facebook_image_url_candidates(self, url: str, media_kind: str = "image") -> list[str]:
        normalized_url = unescape(url or "").strip()
        if not normalized_url:
            return []

        parsed = urlsplit(normalized_url)
        if not parsed.scheme or not parsed.netloc:
            return [normalized_url]

        original_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        candidates: list[str] = []
        seen: set[str] = set()

        def add_candidate(path: str | None = None, params: dict[str, str] | None = None) -> None:
            next_url = urlunsplit(
                (
                    parsed.scheme,
                    parsed.netloc,
                    path if path is not None else parsed.path,
                    urlencode(params if params is not None else original_params),
                    parsed.fragment,
                )
            )
            if next_url and next_url not in seen:
                seen.add(next_url)
                candidates.append(next_url)

        add_candidate()

        if "stp" in original_params:
            no_stp = dict(original_params)
            no_stp.pop("stp", None)
            add_candidate(params=no_stp)

            stp_value = original_params.get("stp", "")
            stp_tokens = [token for token in stp_value.split("_") if token]
            trimmed_tokens = [
                token
                for token in stp_tokens
                if not re.fullmatch(r"(?:[sp]\d+x\d+[a-z]?|fb\d+|cp\d+)", token)
            ]
            if trimmed_tokens and "_".join(trimmed_tokens) != stp_value:
                trimmed_params = dict(original_params)
                trimmed_params["stp"] = "_".join(trimmed_tokens)
                add_candidate(params=trimmed_params)

            high_res_stps = []
            if media_kind == "avatar":
                high_res_stps = [
                    "dst-jpg_p960x960",
                    "dst-jpg_s960x960",
                    "dst-jpg_p2048x2048",
                    "dst-jpg_s2048x2048",
                    "dst-jpg_p1080x1080",
                    "dst-jpg_s1080x1080",
                ]
            elif media_kind == "cover":
                high_res_stps = [
                    "dst-jpg_p2048x2048",
                    "dst-jpg_p1600x1600",
                    "dst-jpg_s2048x2048",
                ]

            preserved_suffix = [
                token for token in stp_tokens if token.startswith("tt") or token.startswith("nu")
            ]
            for base_stp in high_res_stps:
                rebuilt = "_".join([base_stp, *preserved_suffix]).strip("_")
                resized_params = dict(original_params)
                resized_params["stp"] = rebuilt
                add_candidate(params=resized_params)

        if media_kind == "avatar" and "/t39.30808-1/" in parsed.path:
            add_candidate(path=parsed.path.replace("/t39.30808-1/", "/t39.30808-6/"))

        return candidates

    def _download_image_via_browser(self, driver, url: str) -> Image.Image | None:
        try:
            normalized_url = unescape(url)
            script = """
                const done = arguments[arguments.length - 1];
                const url = arguments[0];
                fetch(url, { credentials: 'include', mode: 'cors' })
                  .then((response) => {
                    if (!response.ok) {
                      throw new Error(`HTTP ${response.status}`);
                    }
                    return response.arrayBuffer();
                  })
                  .then((buffer) => {
                    const bytes = new Uint8Array(buffer);
                    let binary = '';
                    const chunk = 0x8000;
                    for (let i = 0; i < bytes.length; i += chunk) {
                      binary += String.fromCharCode(...bytes.slice(i, i + chunk));
                    }
                    done({ ok: true, data: btoa(binary) });
                  })
                  .catch((error) => done({ ok: false, error: String(error) }));
            """
            result = driver.execute_async_script(script, normalized_url)
            if not isinstance(result, dict) or not result.get("ok") or not result.get("data"):
                logging.debug("Browser image fetch failed for %s: %s", normalized_url, result)
                return None
            return Image.open(BytesIO(base64.b64decode(result["data"]))).convert("RGB")
        except Exception as exc:
            logging.debug("Browser-side image fetch failed for %s: %s", url, exc)
            return None

    def _save_profile_screenshot(self, driver, instance_number: int, profile_name: str | None) -> None:
        screenshot_path = facebook_screenshot_path(instance_number, profile_name)
        for old_path in image_account_dir(instance_number).glob("facebook_*.png"):
            if old_path != screenshot_path:
                try:
                    old_path.unlink()
                except Exception:
                    pass
        driver.save_screenshot(str(screenshot_path))

    def _facebook_screenshot_name(self, instance_number: int, profile_name: str | None) -> str:
        name = (profile_name or "unknown").strip().lower()
        slug = re.sub(r"[^a-z0-9]+", "_", name).strip("_") or "unknown"
        return f"facebook_{instance_number}_{slug}.png"
