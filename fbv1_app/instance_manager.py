from __future__ import annotations

import csv
from datetime import datetime
from html import unescape
import json
import logging
import os
import queue
import re
import shutil
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

from PIL import Image, ImageOps, ImageTk
from selenium import webdriver
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService

from .auth_manager import AuthManager, AuthCheckResult
from .config import (
    APP_DB_PATH,
    BACKUP_DIR,
    COOKIE_DIR,
    DATA_FILE,
    GECKODRIVER_PATH,
    IMAGE_DIR,
    PLATFORM_FOLDER_DIRS,
    avatar_image_path,
    cover_image_path,
    cookie_dir_for_platform,
    firefox_user_data_dir_for_platform,
    platform_accounts_path,
    platform_settings_path,
)
from .platforms import PLATFORM_CONFIG, PLATFORM_ORDER
from .storage import AccountStateStore
from .theme import ACCENT, BORDER, DANGER, SECTION_FONT, SMALL_FONT, SUCCESS, SURFACE_ALT, SURFACE_BG, TEXT_MUTED, TEXT_PRIMARY, WARNING

if TYPE_CHECKING:
    from .ui import FacebookToolApp


class InstanceManager:
    PLATFORM_HOME_URLS = {platform: str(config["home_url"]) for platform, config in PLATFORM_CONFIG.items()}
    PLATFORM_CHECK_URLS = {platform: str(config["check_url"]) for platform, config in PLATFORM_CONFIG.items()}
    PLATFORM_ACTION_URLS = {
        platform: dict(config.get("action_urls", {}))
        for platform, config in PLATFORM_CONFIG.items()
    }

    def __init__(self, app: "FacebookToolApp") -> None:
        self.app = app
        self.storage = AccountStateStore(APP_DB_PATH, BACKUP_DIR)
        self.auth = AuthManager()
        self.platform_states: dict[str, dict] = {}
        self.current_platform = "facebook"
        self._route_identity_cache: dict[str, tuple[float, str, str]] = {}

    @property
    def state(self):
        return self.app.state

    @property
    def vars(self):
        return self.app.vars

    def firefox_profile_dir(self, instance_number: int, platform: str | None = None):
        platform = platform or self.vars.platform_var.get()
        report = self.state.instance_reports.get(instance_number, {})
        account_type = str(report.get("account_type") or report.get("country") or "").strip()
        try:
            local_index = int(report.get("local_index") or 0)
        except Exception:
            local_index = 0
        if account_type and local_index > 0:
            root = firefox_user_data_dir_for_platform(platform)
            safe_type = self._safe_folder_name(account_type)
            target = root / safe_type / f"Firefox_{local_index}"
            source = root / f"Firefox_{instance_number}"
            if source.exists() and not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.move(str(source), str(target))
                except Exception as exc:
                    logging.warning("Could not migrate Firefox profile %s to %s: %s", source, target, exc)
            return target
        return firefox_user_data_dir_for_platform(platform) / f"Firefox_{instance_number}"

    def _safe_folder_name(self, value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
        cleaned = cleaned.strip("._-")
        return cleaned or "Default"

    def switch_platform(self, platform: str) -> None:
        if platform not in self.PLATFORM_HOME_URLS:
            platform = "facebook"
        previous_platform = self.current_platform
        self.platform_states[previous_platform] = self._snapshot_current_platform_state()
        if platform != previous_platform:
            self._close_current_drivers()
        self.current_platform = platform
        self.vars.platform_var.set(platform)
        self._load_platform_state(platform)
        self.save_instance_data()

    def _snapshot_current_platform_state(self) -> dict:
        return {
            "credentials": dict(self.state.credentials_dict),
            "instance_names": dict(self.state.instance_names),
            "profile_names": dict(self.state.profile_names),
            "preview_updated_at": dict(self.state.preview_updated_at),
            "run_states": dict(self.state.run_states),
            "instance_reports": dict(self.state.instance_reports),
            "backend_profile_ids": dict(self.state.backend_profile_ids),
            "photo_upload_paths": dict(self.state.photo_upload_paths),
            "cover_upload_paths": dict(self.state.cover_upload_paths),
            "photo_upload_descriptions": dict(self.state.photo_upload_descriptions),
            "country_types": [
                value for value in getattr(self.app, "legacy_stores", ["All"]) if str(value or "").strip()
            ],
            "custom_account_types": [
                value for value in getattr(self.app, "account_groups", ["All"]) if str(value or "").strip()
            ],
            "deleted_instances": list(self.state.deleted_instances),
            "active_instances": [
                i + 1 for i, (_button, frame) in enumerate(self.state.firefox_buttons) if frame is not None
            ],
        }

    def _normalize_platform_state(self, raw_state: dict | None) -> dict:
        raw_state = raw_state if isinstance(raw_state, dict) else {}

        def int_keyed_dict(field_name: str) -> dict[int, object]:
            values = raw_state.get(field_name, {})
            if not isinstance(values, dict):
                return {}
            output: dict[int, object] = {}
            for key, value in values.items():
                try:
                    output[int(key)] = value
                except (TypeError, ValueError):
                    continue
            return output

        def int_set(field_name: str) -> set[int]:
            values = raw_state.get(field_name, [])
            if not isinstance(values, list):
                return set()
            output: set[int] = set()
            for value in values:
                try:
                    output.add(int(value))
                except (TypeError, ValueError):
                    continue
            return output

        def int_list(field_name: str) -> list[int]:
            values = raw_state.get(field_name, [])
            if not isinstance(values, list):
                return []
            output: list[int] = []
            for value in values:
                try:
                    output.append(int(value))
                except (TypeError, ValueError):
                    continue
            return output

        def str_list(field_name: str) -> list[str]:
            values = raw_state.get(field_name, [])
            if not isinstance(values, list):
                return []
            output: list[str] = []
            seen: set[str] = set()
            for value in values:
                clean = str(value or "").strip()
                if not clean or clean.lower() in seen:
                    continue
                seen.add(clean.lower())
                output.append(clean)
            return output

        return {
            "credentials": {key: str(value) for key, value in int_keyed_dict("credentials").items()},
            "instance_names": {key: str(value) for key, value in int_keyed_dict("instance_names").items()},
            "profile_names": {key: str(value) for key, value in int_keyed_dict("profile_names").items()},
            "preview_updated_at": {key: str(value) for key, value in int_keyed_dict("preview_updated_at").items()},
            "run_states": {key: str(value) for key, value in int_keyed_dict("run_states").items()},
            "instance_reports": {
                key: value for key, value in int_keyed_dict("instance_reports").items() if isinstance(value, dict)
            },
            "backend_profile_ids": {key: str(value) for key, value in int_keyed_dict("backend_profile_ids").items() if value},
            "photo_upload_paths": {key: str(value) for key, value in int_keyed_dict("photo_upload_paths").items() if value},
            "cover_upload_paths": {key: str(value) for key, value in int_keyed_dict("cover_upload_paths").items() if value},
            "photo_upload_descriptions": {
                key: str(value) for key, value in int_keyed_dict("photo_upload_descriptions").items() if value is not None
            },
            "country_types": str_list("country_types"),
            "custom_account_types": str_list("custom_account_types"),
            "deleted_instances": int_set("deleted_instances"),
            "active_instances": int_list("active_instances"),
        }

    def _empty_platform_state(self) -> dict:
        return {
            "credentials": {},
            "instance_names": {},
            "profile_names": {},
            "preview_updated_at": {},
            "run_states": {},
            "instance_reports": {},
            "backend_profile_ids": {},
            "photo_upload_paths": {},
            "cover_upload_paths": {},
            "photo_upload_descriptions": {},
            "country_types": ["All"],
            "custom_account_types": ["All"],
            "deleted_instances": set(),
            "active_instances": [],
        }

    def _remove_copied_non_facebook_states(self) -> None:
        facebook_state = self._normalize_platform_state(self.platform_states.get("facebook"))
        facebook_active = set(facebook_state["active_instances"])
        if not facebook_active:
            return
        for platform in PLATFORM_ORDER:
            if platform == "facebook":
                continue
            platform_state = self._normalize_platform_state(self.platform_states.get(platform))
            platform_active = set(platform_state["active_instances"])
            if platform_active != facebook_active:
                continue
            profile_root = firefox_user_data_dir_for_platform(platform)
            has_platform_profiles = any(profile_root.glob("Firefox_*"))
            if not has_platform_profiles:
                self.platform_states[platform] = self._empty_platform_state()

    def _serializable_platform_states(self) -> dict[str, dict]:
        output: dict[str, dict] = {}
        for platform, platform_state in self.platform_states.items():
            if platform not in self.PLATFORM_HOME_URLS:
                continue
            normalized = self._normalize_platform_state(platform_state)
            output[platform] = {
                "credentials": normalized["credentials"],
                "instance_names": normalized["instance_names"],
                "profile_names": normalized["profile_names"],
                "preview_updated_at": normalized["preview_updated_at"],
                "run_states": normalized["run_states"],
                "instance_reports": normalized["instance_reports"],
                "backend_profile_ids": normalized["backend_profile_ids"],
                "photo_upload_paths": normalized["photo_upload_paths"],
                "cover_upload_paths": normalized["cover_upload_paths"],
                "photo_upload_descriptions": normalized["photo_upload_descriptions"],
                "country_types": normalized["country_types"],
                "custom_account_types": normalized["custom_account_types"],
                "deleted_instances": sorted(normalized["deleted_instances"]),
                "active_instances": normalized["active_instances"],
            }
        return output

    def _write_platform_data_files(self, platform_states: dict[str, dict]) -> None:
        for platform in PLATFORM_ORDER:
            normalized = self._normalize_platform_state(platform_states.get(platform))
            account_rows = []
            instance_ids = set(normalized["active_instances"])
            instance_ids.update(normalized["instance_names"].keys())
            instance_ids.update(normalized["profile_names"].keys())
            instance_ids.update(normalized["run_states"].keys())
            instance_ids.update(normalized["instance_reports"].keys())
            for instance_number in sorted(instance_ids):
                if instance_number in normalized["deleted_instances"]:
                    continue
                report = normalized["instance_reports"].get(instance_number, {})
                local_account = str(normalized["instance_names"].get(instance_number) or "")
                account_rows.append(
                    {
                        "platform": platform,
                        "firefox": f"Firefox {instance_number}",
                        "local_account": local_account,
                        "account_key": f"{platform}|Firefox {instance_number}|{local_account}",
                        "profile_name": str(normalized["profile_names"].get(instance_number) or ""),
                        "state": str(report.get("account_status") or report.get("last_status") or "Unknown"),
                        "report": report,
                    }
                )
            try:
                with platform_accounts_path(platform).open("w", encoding="utf-8") as handle:
                    json.dump({"platform": platform, "accounts": account_rows}, handle, indent=2)
                with platform_settings_path(platform).open("w", encoding="utf-8") as handle:
                    json.dump(
                        {
                            "platform": platform,
                            "title": PLATFORM_CONFIG[platform]["title"],
                            "import_format": PLATFORM_CONFIG[platform]["import_format"],
                            "country_types": normalized["country_types"],
                            "custom_account_types": normalized["custom_account_types"],
                        },
                        handle,
                        indent=2,
                    )
            except Exception as exc:
                logging.warning("Could not write %s platform data files: %s", platform, exc)

    def _platform_state_from_accounts_file(self, platform: str) -> dict | None:
        path = platform_accounts_path(platform)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return None
        accounts = payload.get("accounts") if isinstance(payload, dict) else None
        if not isinstance(accounts, list):
            return None
        state = self._empty_platform_state()
        for index, account in enumerate(accounts, start=1):
            if not isinstance(account, dict):
                continue
            try:
                instance_number = int(str(account.get("firefox") or "").strip().rsplit(" ", 1)[1])
            except Exception:
                instance_number = index
            report = account.get("report", {})
            if not isinstance(report, dict):
                report = {}
            report.setdefault("account_status", account.get("state") or "Unknown")
            state["instance_reports"][instance_number] = report
            state["instance_names"][instance_number] = str(account.get("local_account") or f"Account {instance_number}")
            profile_name = str(account.get("profile_name") or "").strip()
            if profile_name:
                state["profile_names"][instance_number] = profile_name
            state["active_instances"].append(instance_number)
        return state

    def _load_platform_state(self, platform: str) -> None:
        platform_state = self._normalize_platform_state(self.platform_states.get(platform))
        self._clear_visible_instances()
        self.state.credentials_dict = platform_state["credentials"]
        self.state.instance_names = platform_state["instance_names"]
        self.state.profile_names = platform_state["profile_names"]
        self.state.preview_updated_at = platform_state["preview_updated_at"]
        self.state.run_states = platform_state["run_states"]
        self.state.instance_reports = platform_state["instance_reports"]
        self.state.backend_profile_ids = platform_state["backend_profile_ids"]
        self.state.photo_upload_paths = platform_state["photo_upload_paths"]
        self.state.cover_upload_paths = platform_state["cover_upload_paths"]
        self.state.photo_upload_descriptions = platform_state["photo_upload_descriptions"]
        self.state.deleted_instances = platform_state["deleted_instances"]
        self._hydrate_reports_from_cookie_files()
        for instance_number in platform_state["active_instances"]:
            self.open_firefox_instances(1, start_index=instance_number)
        self.sync_local_profiles_to_backend_async()

    def _clear_visible_instances(self) -> None:
        for _button, frame in self.state.firefox_buttons:
            if frame:
                frame.destroy()
        self.state.firefox_buttons.clear()
        self.state.credential_entries.clear()
        self.state.image_labels.clear()
        self.state.cover_labels.clear()
        self.state.avatar_labels.clear()
        self.state.avatar_name_labels.clear()
        self.state.instance_media_frames.clear()
        self.state.instance_text_frames.clear()
        self.state.instance_title_labels.clear()
        self.state.instance_hint_labels.clear()
        self.state.instance_detail_labels.clear()
        self.state.preview_status_labels.clear()
        self.state.run_status_labels.clear()
        self.state.instance_body_frames.clear()
        self.state.preview_monitor_tokens.clear()

    def _close_current_drivers(self) -> None:
        for driver in list(self.state.drivers.values()):
            try:
                driver.quit()
            except Exception:
                pass
        self.state.drivers.clear()
        self.app.browser._instance_slots.clear()
        self.app.browser._driver_modes.clear()
        self.app.browser._launching_instances.clear()

    def open_firefox_instances(
        self,
        instance_count: int,
        start_index: int = 1,
        padding: int = 5,
    ) -> None:
        for i in range(start_index, start_index + instance_count):
            if i in self.state.deleted_instances:
                continue

            instance_folder = self.firefox_profile_dir(i)
            instance_folder.mkdir(parents=True, exist_ok=True)
            selected_type = self._selected_account_type_from_app()
            if selected_type:
                report = self._ensure_instance_report(i)
                if not str(report.get("account_type") or "").strip():
                    report["account_type"] = selected_type
                if not str(report.get("expected_country") or "").strip():
                    report["expected_country"] = self._expected_country_from_account_type(str(report.get("account_type") or selected_type))

            instance_frame = self.app.Frame(
                self.app.button_frame,
                bg=SURFACE_BG,
                highlightbackground=BORDER,
                highlightthickness=1,
                bd=0,
            )
            instance_frame.pack(fill="x", padx=8, pady=padding)
            self.app.Frame(instance_frame, bg=ACCENT, height=1).pack(fill="x")

            header = self.app.Frame(instance_frame, bg=SURFACE_BG)
            header.pack(fill="x", padx=12, pady=(8, 6))

            button = self.app.create_button(
                header,
                text=self.state.instance_names.get(i, f"Firefox {i}"),
                command=lambda i=i: threading.Thread(target=self.run_firefox_instance, args=(i,), daemon=True).start(),
                kind="primary",
                width=18,
            )
            button.pack(side="left")

            run_status_label = self.app.Label(
                header,
                text=self.state.run_states.get(i, "Idle"),
                bg=SURFACE_BG,
                fg=TEXT_MUTED,
                font=SMALL_FONT,
                padx=8,
                pady=3,
                highlightthickness=1,
                highlightbackground=BORDER,
            )
            run_status_label.pack(side="left", padx=(8, 0))
            self.state.run_status_labels[i] = run_status_label

            action_group = self.app.Frame(header, bg=SURFACE_BG)
            action_group.pack(side="right")

            self.app.create_button(
                action_group,
                text="Rename",
                command=lambda i=i: self.rename_instance(i),
                kind="neutral",
                compact=True,
            ).pack(side="left", padx=(6, 0))

            self.app.create_button(
                action_group,
                text="Picture",
                command=lambda i=i: self.upload_picture(i),
                kind="secondary",
                compact=True,
            ).pack(side="left", padx=(6, 0))

            self.app.create_button(
                action_group,
                text="Refresh Preview",
                command=lambda i=i: threading.Thread(target=self.refresh_preview, args=(i,), daemon=True).start(),
                kind="secondary",
                compact=True,
            ).pack(side="left", padx=(6, 0))

            self.app.create_button(
                action_group,
                text="Stop Waiting",
                command=lambda i=i: self.stop_waiting(i),
                kind="warning",
                compact=True,
            ).pack(side="left", padx=(6, 0))

            self.app.create_button(
                action_group,
                text="Delete",
                command=lambda i=i: self.delete_instance(i),
                kind="danger",
                compact=True,
            ).pack(side="left", padx=(6, 0))

            self.app.Frame(instance_frame, bg=BORDER, height=1).pack(fill="x", padx=12)
            body = self.app.Frame(instance_frame, bg=SURFACE_ALT)
            body.pack(fill="x", padx=12, pady=(8, 10))
            self.state.instance_body_frames[i] = body

            media_panel = self.app.Frame(body, bg=SURFACE_ALT)
            media_panel.pack(side="left", padx=(10, 14), pady=10)
            self.state.instance_media_frames[i] = media_panel

            cover_frame = self.app.Frame(
                media_panel,
                bg=SURFACE_ALT,
                width=300,
                height=112,
            )
            cover_frame.pack(anchor="w")
            cover_frame.pack_propagate(False)
            self.state.image_labels[i] = None

            cover_label = self.app.Label(
                cover_frame,
                bg=SURFACE_ALT,
                text="No cover",
                fg=TEXT_MUTED,
                font=SMALL_FONT,
            )
            cover_label.place(x=0, y=0, width=300, height=112)
            self.state.cover_labels[i] = cover_label

            avatar_label = self.app.Label(
                cover_frame,
                bg=SURFACE_ALT,
                text="No avatar",
                fg=TEXT_MUTED,
                font=SMALL_FONT,
            )
            avatar_label.place(x=10, y=34, width=72, height=72)
            self.state.avatar_labels[i] = avatar_label

            avatar_text = self.app.Frame(media_panel, bg=SURFACE_ALT)
            avatar_text.pack(anchor="w", padx=(90, 0), pady=(6, 0))
            avatar_name_label = self.app.Label(
                avatar_text,
                bg=SURFACE_ALT,
                text=self.state.profile_names.get(i, "No account name"),
                fg=TEXT_PRIMARY,
                font=SECTION_FONT,
                anchor="w",
            )
            avatar_name_label.pack(anchor="w")
            self.state.avatar_name_labels[i] = avatar_name_label

            status_label = self.app.Label(
                avatar_text,
                bg=SURFACE_ALT,
                text="Ready",
                fg=TEXT_MUTED,
                font=SMALL_FONT,
                anchor="w",
            )
            status_label.pack(anchor="w", pady=(2, 0))
            self.state.preview_status_labels[i] = status_label

            text_block = self.app.Frame(body, bg=SURFACE_ALT)
            text_block.pack(side="left", fill="x", expand=True, pady=8, padx=(4, 6))
            self.state.instance_text_frames[i] = text_block
            title_label = self.app.Label(
                text_block,
                text=f"Profile Workspace: Firefox_{i}",
                bg=SURFACE_ALT,
                fg=TEXT_PRIMARY,
                font=SECTION_FONT,
            )
            title_label.pack(anchor="w")
            self.state.instance_title_labels[i] = title_label

            hint_label = self.app.Label(
                text_block,
                text="Session data and media previews are persisted for this profile.",
                bg=SURFACE_ALT,
                fg=TEXT_MUTED,
                font=SMALL_FONT,
            )
            hint_label.pack(anchor="w", pady=(2, 0))
            self.state.instance_hint_labels[i] = hint_label

            detail_label = self.app.Label(
                text_block,
                text="Use Refresh Preview to sync avatar, cover, and latest screenshot.",
                bg=SURFACE_ALT,
                fg=TEXT_MUTED,
                font=SMALL_FONT,
            )
            detail_label.pack(anchor="w", pady=(1, 0))
            self.state.instance_detail_labels[i] = detail_label

            while len(self.state.firefox_buttons) < i:
                self.state.firefox_buttons.append((None, None))
            self.state.firefox_buttons[i - 1] = (button, instance_frame)
            self._apply_saved_run_status(i)
            self._set_instance_body_visibility(i)
            self._load_saved_media(i)
            self.refresh_platform_cards()

        self.app.refresh_dashboard()

    def refresh_platform_cards(self) -> None:
        platform = self.vars.platform_var.get()
        platform_label = self.app._platform_label()
        facebook_mode = platform == "facebook"
        for instance_number in self.active_instance_numbers():
            media_frame = self.state.instance_media_frames.get(instance_number)
            text_frame = self.state.instance_text_frames.get(instance_number)
            if media_frame:
                if facebook_mode:
                    if not media_frame.winfo_ismapped():
                        pack_options = {"side": "left", "padx": (10, 14), "pady": 10}
                        if text_frame:
                            pack_options["before"] = text_frame
                        media_frame.pack(**pack_options)
                else:
                    media_frame.pack_forget()

            title_label = self.state.instance_title_labels.get(instance_number)
            if title_label:
                title_label.config(text=f"{platform_label} Workspace: Firefox_{instance_number}")

            hint_label = self.state.instance_hint_labels.get(instance_number)
            if hint_label:
                if facebook_mode:
                    hint_label.config(text="Session data and media previews are persisted for this profile.")
                else:
                    hint_label.config(text=f"This profile opens the selected {platform_label} tool or page.")

            detail_label = self.state.instance_detail_labels.get(instance_number)
            if detail_label:
                if facebook_mode:
                    detail_label.config(text="Use Refresh Preview to sync avatar, cover, and latest screenshot.")
                else:
                    detail_label.config(text=f"{platform_label} mode hides Facebook photo, cover, and account-only fields.")

    def upload_picture(self, instance_number: int) -> None:
        file_path = self.app.filedialog.askopenfilename(filetypes=[("Image Files", "*.png;*.jpg;*.jpeg")])
        if not file_path:
            return

        dest_path = avatar_image_path(instance_number)
        shutil.copyfile(file_path, dest_path)
        self._load_saved_media(instance_number)
        logging.info("Image for Firefox %s uploaded successfully.", instance_number)
        self.set_preview_status(instance_number, "Avatar updated", SUCCESS)
        self.app.refresh_dashboard()

    def refresh_preview(self, instance_number: int) -> None:
        self.set_preview_status(instance_number, "Refreshing...", WARNING)
        self.state.preview_monitor_tokens[instance_number] = self.state.preview_monitor_tokens.get(instance_number, 0) + 1
        if instance_number in self.state.drivers:
            self.app.browser.try_sync_profile_preview(instance_number)
            return
        self.app.browser.open_firefox_instance(instance_number, login=False)

    def stop_waiting(self, instance_number: int) -> None:
        self.state.preview_monitor_tokens[instance_number] = self.state.preview_monitor_tokens.get(instance_number, 0) + 1
        self.set_preview_status(instance_number, "Waiting stopped", WARNING)

    def run_firefox_instance(self, instance_number: int) -> None:
        if self.state.batch_stop_requested:
            self.set_run_status(instance_number, "Stopped", WARNING)
            return
        if not self.allow_open_for_expected_country(instance_number):
            self._update_instance_report(
                instance_number,
                action=self._action_label(self.vars.action_var.get()),
                status="IP mismatch",
                note="Blocked because current IP country does not match expected country.",
            )
            self.save_instance_data()
            return
        action = self.vars.action_var.get()
        action_label = self._action_label(action)
        self._update_instance_report(instance_number, action=action_label, status="Queued", increment_run=True)
        self.set_run_status(instance_number, "Queued", WARNING)
        try:
            platform = self.vars.platform_var.get()
            if action == "open_home":
                self.open_platform_action(instance_number, "open_home", platform)
                return
            if action in {"refresh_login", "check_login", "check_gmail", "check_channel", "check_api"}:
                self.check_live_instance(instance_number, platform)
                return
            if action == "clear_token":
                self.clear_auth_for_instance(platform, instance_number)
                self.set_run_status(instance_number, "Need Reconnect", WARNING)
                return
            if action == "reconnect_required":
                self.set_run_status(instance_number, "Need Reconnect", WARNING)
                self.set_account_health(instance_number, "Need Reconnect", "Reconnect with official authorization.")
                return
            if platform != "facebook":
                action_urls = self.PLATFORM_ACTION_URLS.get(platform, {})
                target_url = action_urls.get(action, self.PLATFORM_HOME_URLS.get(platform, "https://www.google.com"))
                self.app.browser.open_firefox_instance(
                    instance_number,
                    login=False,
                    start_url=target_url,
                    sync_preview=False,
                )
                if action in {"publish_tool", "upload_video", "create_post", "post_article"}:
                    prepared = self.app.browser.prepare_platform_publish(
                        instance_number=instance_number,
                        platform=platform,
                        media_paths=self.vars.reel_folder_or_file_var.get(),
                        caption=self.vars.description_var.get(),
                    )
                    if prepared:
                        self.set_run_status(instance_number, "Prepared", SUCCESS)
                    else:
                        self.set_run_status(instance_number, "Ready", SUCCESS)
                    return
                self.set_run_status(instance_number, "Ready", SUCCESS)
                return

            if action in {"login", "connect_account"}:
                self.app.browser.open_firefox_instance(instance_number, login=False)
            elif action == "care":
                self.app.browser.open_firefox_instance(instance_number, login=False)
                self.app.actions.watch_facebook_videos([instance_number])
                self.set_run_status(instance_number, "Done", SUCCESS)
            elif action == "clear_data":
                self.app.browser.open_firefox_instance(instance_number, login=False, clear_data_action=True)
                self.set_run_status(instance_number, "Done", SUCCESS)
            elif action == "join_group":
                self.app.browser.open_firefox_instance(instance_number, login=False)
                self.app.actions.join_facebook_groups([instance_number])
                self.set_run_status(instance_number, "Done", SUCCESS)
            elif action == "upload_reel":
                self.app.browser.open_firefox_instance(instance_number, login=False)
                self.app.actions.upload_facebook_reel([instance_number])
                self.set_run_status(instance_number, "Done", SUCCESS)
            elif action == "share_to_groups":
                self.app.browser.open_firefox_instance(instance_number, login=False)
                self.app.actions.share_to_facebook_groups([instance_number])
                self.set_run_status(instance_number, "Done", SUCCESS)
            elif action == "get_id":
                self.app.browser.open_firefox_instance(instance_number, login=False)
                account_id = self.app.browser.get_id(instance_number)
                if account_id:
                    self.set_run_status(instance_number, "Done", SUCCESS)
                else:
                    self.set_run_status(instance_number, "Failed", DANGER)
            elif action == "get_gmail":
                self.check_live_instance(instance_number, platform)
            elif action == "get_date":
                self.check_live_instance(instance_number, platform)
            elif action == "upload_photo_cover":
                self.app.browser.open_firefox_instance(instance_number, login=False)
                photo_path = self.state.photo_upload_paths.get(instance_number, "")
                cover_path = self.state.cover_upload_paths.get(instance_number, "")
                profile_description = self.state.photo_upload_descriptions.get(instance_number, "")
                if not photo_path and not cover_path:
                    self.set_run_status(instance_number, "Failed", DANGER)
                    return
                uploaded = self.app.browser.upload_profile_media(
                    instance_number,
                    photo_path=photo_path,
                    cover_path=cover_path,
                    profile_description=profile_description,
                )
                if uploaded:
                    self.set_run_status(instance_number, "Done", SUCCESS)
                else:
                    self.set_run_status(instance_number, "Failed", DANGER)
            else:
                self.set_run_status(instance_number, "Unknown action", DANGER)
        except Exception as exc:
            logging.error("Action %s failed for Firefox %s: %s", action_label, instance_number, exc)
            self.set_run_status(instance_number, "Failed", DANGER)

    def open_platform_action(self, instance_number: int, action: str = "open_home", platform: str | None = None) -> None:
        platform = platform or self.vars.platform_var.get()
        action_urls = self.PLATFORM_ACTION_URLS.get(platform, {})
        target_url = action_urls.get(action, self.PLATFORM_HOME_URLS.get(platform, "https://www.facebook.com"))
        self.app.browser.open_firefox_instance(
            instance_number,
            login=False,
            start_url=target_url,
            sync_preview=False,
        )
        self.set_run_status(instance_number, "Ready", SUCCESS)

    def start_all_instances(self) -> None:
        if self.state.batch_running:
            return
        selected_type = self._selected_account_type_from_app()
        instance_numbers = self.active_instance_numbers_for_type(selected_type)
        if not instance_numbers:
            suffix = f" for {selected_type}" if selected_type else ""
            self.app.messagebox.showwarning("Start All", f"No active Firefox profiles found{suffix}.")
            return

        try:
            max_workers = int(self.vars.thread_count_var.get())
        except Exception:
            max_workers = 3
        max_workers = max(1, min(10, max_workers))
        self.vars.thread_count_var.set(max_workers)

        self.state.batch_running = True
        self.state.batch_stop_requested = False
        threading.Thread(
            target=self._run_batch_instances,
            args=(instance_numbers, max_workers),
            daemon=True,
        ).start()

    def stop_all_instances(self) -> None:
        self.state.batch_stop_requested = True
        for instance_number in self.active_instance_numbers():
            if not self.is_instance_busy(instance_number):
                self.set_run_status(instance_number, "Stopped", WARNING)

    def check_live_all_instances(self, show_empty_warning: bool = True, account_type: str | None = None) -> None:
        if self.state.batch_running:
            return
        selected_type = (account_type or self._selected_account_type_from_app()).strip()
        if not selected_type:
            if show_empty_warning:
                self.app.messagebox.showwarning("Check Login", "Select one account type first. Check Login does not run on All.")
            return
        instance_numbers = self.active_instance_numbers_for_type(selected_type)
        if not instance_numbers:
            if show_empty_warning:
                suffix = f" in account type {selected_type}" if selected_type else ""
                self.app.messagebox.showwarning("Check Login", f"No active Firefox profiles found{suffix} for this platform.")
            return

        try:
            max_workers = int(self.vars.thread_count_var.get())
        except Exception:
            max_workers = 3
        max_workers = max(1, min(3, max_workers))
        self.vars.thread_count_var.set(max_workers)

        self.state.batch_running = True
        self.state.batch_stop_requested = False
        threading.Thread(
            target=self._check_live_batch,
            args=(instance_numbers, max_workers, self.vars.platform_var.get()),
            daemon=True,
        ).start()

    def _check_live_batch(self, instance_numbers: list[int], max_workers: int, platform: str) -> None:
        work_queue: queue.Queue[int] = queue.Queue()
        for instance_number in instance_numbers:
            self._queue_live_check_result(instance_number)
            work_queue.put(instance_number)

        worker_count = min(max_workers, work_queue.qsize())
        threads: list[threading.Thread] = []

        def worker() -> None:
            while not self.state.batch_stop_requested:
                try:
                    instance_number = work_queue.get_nowait()
                except queue.Empty:
                    return
                try:
                    if self.state.batch_stop_requested:
                        self.set_run_status(instance_number, "Stopped", WARNING)
                        return
                    self.check_live_instance(instance_number, platform)
                    time.sleep(0.2)
                finally:
                    work_queue.task_done()

        try:
            if hasattr(self.app, "refresh_report_table_async"):
                self.app.refresh_report_table_async()
            if work_queue.empty():
                return
            for _index in range(worker_count):
                if self.state.batch_stop_requested:
                    break
                thread = threading.Thread(target=worker, daemon=True)
                threads.append(thread)
                thread.start()
            for thread in threads:
                thread.join()
        finally:
            self.state.batch_running = False
            self.state.batch_stop_requested = False
            self.save_instance_data()
            self.app.refresh_dashboard()

    def _queue_live_check_result(self, instance_number: int) -> None:
        report = self._ensure_instance_report(instance_number)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        report["last_action"] = "Check Login"
        report["last_status"] = "Queued"
        report["last_note"] = "Waiting for check worker..."
        report["account_status"] = "Queued"
        report["account_reason"] = "Waiting for check worker..."
        report["account_checked_at"] = now
        report["last_updated"] = now

    def _apply_live_check_preflight_result(self, instance_number: int, platform: str) -> bool:
        country_guard_result = self._live_check_country_guard_result(instance_number)
        if country_guard_result:
            self._record_live_check_result(instance_number, *country_guard_result)
            return True

        browser_result = self._classify_running_browser_session(instance_number, platform)
        if browser_result and browser_result[0] in {"Disabled", "Checkpoint"}:
            self._record_live_check_result(instance_number, *browser_result)
            return True
        return False

    def _live_check_country_guard_result(self, instance_number: int) -> tuple[str, str, str] | None:
        report = self._ensure_instance_report(instance_number)
        proxy_url = self._normalized_proxy_url(str(report.get("proxy", "") or ""))
        if proxy_url == "unsupported":
            return "Review", "Saved proxy uses an unsupported scheme for background check.", WARNING

        opener = self._build_background_opener(proxy_url)
        self._autofill_route_ip_country(instance_number, opener)
        report = self._ensure_instance_report(instance_number)
        expected_country = self.expected_country_for_instance(instance_number)
        current_country = str(report.get("country") or "").strip()
        if not expected_country:
            return None
        if current_country and not self._countries_match(current_country, expected_country):
            account_type = str(report.get("account_type") or expected_country).strip()
            return (
                "IP Mismatch",
                (
                    f"{account_type} account expects {expected_country} IP, "
                    f"but current IP country is {current_country}. "
                    "Stopped before live check; cookies were not loaded."
                ),
                DANGER,
            )
        if not current_country:
            return (
                "IP unknown",
                f"Could not verify current IP country before checking {expected_country} account.",
                WARNING,
            )
        return None

    def check_live_instance(self, instance_number: int, platform: str | None = None) -> None:
        platform = platform or self.vars.platform_var.get()
        self._begin_live_check_result(instance_number)
        self.set_run_status(instance_number, "Checking", WARNING)
        country_guard = self._live_check_country_guard_result(instance_number)
        if country_guard:
            status, note, color = country_guard
            self._record_live_check_result(instance_number, status, color, note)
            return
        report = self._ensure_instance_report(instance_number)
        key = self.auth_key_for_instance(platform, instance_number)
        result = self.auth.refresh_login(platform, key, report)
        self._record_auth_check_result(platform, instance_number, result)

    def _begin_live_check_result(self, instance_number: int) -> None:
        report = self._ensure_instance_report(instance_number)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        report["last_action"] = "Check Login"
        report["last_status"] = "Checking"
        report["last_note"] = "Checking saved authorization..."
        report["account_status"] = "Checking"
        report["account_reason"] = "Checking saved authorization..."
        report["account_checked_at"] = now
        report["last_updated"] = now
        if hasattr(self.app, "refresh_report_table_async"):
            self.app.refresh_report_table_async()

    def auth_key_for_instance(self, platform: str, instance_number: int) -> str:
        report = self._ensure_instance_report(instance_number)
        firefox_profile = f"Firefox {instance_number}"
        local_account = str(
            report.get("local_account")
            or self.state.instance_names.get(instance_number)
            or firefox_profile
        ).strip()
        return f"{platform}|{firefox_profile}|{local_account}"

    def save_auth_for_instance(self, platform: str, instance_number: int, auth: dict) -> None:
        key = self.auth_key_for_instance(platform, instance_number)
        self.auth.save_auth(platform, key, auth)
        report = self._ensure_instance_report(instance_number)
        report["auth_key"] = key
        report["account_status"] = "Token Valid"
        report["account_reason"] = "Encrypted authorization saved"
        report["account_checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._apply_platform_auth_field(platform, report, "Token Valid")
        self.save_instance_data()
        if hasattr(self.app, "refresh_report_table_async"):
            self.app.refresh_report_table_async()

    def clear_auth_for_instance(self, platform: str, instance_number: int) -> bool:
        key = self.auth_key_for_instance(platform, instance_number)
        removed = self.auth.clear_auth(platform, key)
        report = self._ensure_instance_report(instance_number)
        report["account_status"] = "Need Reconnect"
        report["account_reason"] = "Encrypted authorization token cleared"
        report["account_checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._apply_platform_auth_field(platform, report, "Need Reconnect")
        self.save_instance_data()
        if hasattr(self.app, "refresh_report_table_async"):
            self.app.refresh_report_table_async()
        return removed

    def refresh_login_for_instances(self, instance_numbers: list[int] | None = None, platform: str | None = None) -> None:
        platform = platform or self.vars.platform_var.get()
        targets = instance_numbers or self.active_instance_numbers()
        for instance_number in targets:
            self.check_live_instance(instance_number, platform)
        self.save_instance_data()
        self.app.refresh_dashboard()

    def _record_auth_check_result(
        self,
        platform: str,
        instance_number: int,
        result: AuthCheckResult,
    ) -> None:
        if result.tokens:
            self.auth.save_auth(platform, self.auth_key_for_instance(platform, instance_number), result.tokens)
        status = result.status or ("Live" if result.success else "Need Reconnect")
        color = self._auth_status_color(status)
        report = self._ensure_instance_report(instance_number)
        self._apply_platform_auth_field(platform, report, status)
        self._record_live_check_result(instance_number, status, color, result.reason)

    def _apply_platform_auth_field(self, platform: str, report: dict, status: str) -> None:
        if platform == "facebook":
            report["facebook_session"] = status
        elif platform == "tiktok":
            report["tiktok_session"] = status
        elif platform == "youtube":
            report["gmail_login"] = status
            report["youtube_session"] = status
        elif platform == "instagram":
            report["instagram_session"] = status
        elif platform == "wordpress":
            report["api_login_status"] = status

    def _auth_status_color(self, status: str) -> str:
        normalized = str(status or "").strip().lower()
        if normalized in {"live", "token valid"}:
            return SUCCESS
        if normalized in {"need reconnect", "token expired", "login required", "unknown", "queued", "checking"}:
            return WARNING
        return DANGER

    def _sync_identity_from_open_browser(self, instance_number: int) -> None:
        driver = self.state.drivers.get(instance_number)
        if not driver:
            return
        try:
            self.app.browser._sync_profile_identity_from_current_page(instance_number, driver)
        except Exception:
            logging.debug("Open browser identity sync skipped for Firefox %s.", instance_number)

    def sync_open_browser_pages(self) -> bool:
        changed = False
        for instance_number, driver in list(self.state.drivers.items()):
            if instance_number in self.state.deleted_instances:
                continue
            try:
                before_name = self.state.profile_names.get(instance_number, "")
                before_report = dict(self.state.instance_reports.get(instance_number, {}))
                self.app.browser._sync_profile_identity_from_current_page(instance_number, driver)
                after_report = self.state.instance_reports.get(instance_number, {})
                if before_name != self.state.profile_names.get(instance_number, "") or before_report != after_report:
                    changed = True
            except Exception:
                logging.debug("Open browser page sync failed for Firefox %s.", instance_number)
        return changed

    def _check_live_instance_background(self, instance_number: int, platform: str) -> tuple[str, str, str]:
        result = self.auth.refresh_login(platform, self.auth_key_for_instance(platform, instance_number), self._ensure_instance_report(instance_number))
        return result.status, result.reason, self._auth_status_color(result.status)

    def _autofill_facebook_details_background(
        self,
        instance_number: int,
        opener,
        headers: dict[str, str],
        cookies: dict[str, str],
    ) -> None:
        report = self._ensure_instance_report(instance_number)
        account_id = str(report.get("account_id") or cookies.get("c_user") or "").strip()
        detail_urls = [
            "https://accountscenter.facebook.com/?entry_point=app_settings",
            "https://accountscenter.facebook.com/profiles",
            "https://accountscenter.facebook.com/personal_info",
            "https://accountscenter.facebook.com/personal_info/contact_points",
            "https://accountscenter.facebook.com/personal_info/contact_points/",
        ]
        if account_id.isdigit():
            detail_urls.extend(
                [
                    f"https://www.facebook.com/profile.php?id={account_id}&sk=directory_personal_details",
                    f"https://www.facebook.com/profile.php?id={account_id}&sk=about_contact_and_basic_info",
                    f"https://m.facebook.com/profile.php?id={account_id}&v=info",
                ]
            )
        for detail_url in detail_urls:
            try:
                request = urllib.request.Request(detail_url, headers=headers)
                with opener.open(request, timeout=20) as response:
                    body = response.read(800000).decode("utf-8", errors="ignore")
                self._autofill_identity_from_background_body(instance_number, body)
            except Exception:
                continue

    def _autofill_facebook_details_headless_if_needed(self, instance_number: int, cookies: dict[str, str]) -> None:
        report = self._ensure_instance_report(instance_number)
        needs_email = not self._has_report_value(report.get("gmail"))
        needs_birth = not self._has_report_value(report.get("date_birth"))
        needs_gender = not self._has_report_value(report.get("gender"))
        if not (needs_email or needs_birth or needs_gender):
            return
        if not cookies or not self._has_required_login_cookie("facebook", cookies):
            return

        driver = None
        try:
            options = FirefoxOptions()
            options.add_argument("-headless")
            options.set_preference(
                "general.useragent.override",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
            )
            options.set_preference("permissions.default.image", 2)
            service = FirefoxService(executable_path=str(GECKODRIVER_PATH))
            driver = webdriver.Firefox(service=service, options=options)
            driver.set_page_load_timeout(35)
            driver.get("https://www.facebook.com/")
            self._add_facebook_cookies_to_driver(driver, cookies)

            detail_urls = (
                "https://accountscenter.facebook.com/?entry_point=app_settings",
                "https://accountscenter.facebook.com/personal_info",
                "https://accountscenter.facebook.com/personal_info/contact_points",
                "https://accountscenter.facebook.com/personal_info/profile_info",
                "https://accountscenter.facebook.com/personal_info/gender",
                "https://www.facebook.com/me/about_contact_and_basic_info",
            )
            for detail_url in detail_urls:
                try:
                    driver.get(detail_url)
                    body_text = self._wait_for_rendered_accounts_center_text(driver)
                    page_source = str(driver.page_source or "")
                    if self._autofill_identity_from_rendered_text(instance_number, body_text, page_source):
                        report = self._ensure_instance_report(instance_number)
                        if (
                            self._has_report_value(report.get("gmail"))
                            and self._has_report_value(report.get("date_birth"))
                            and self._has_report_value(report.get("gender"))
                        ):
                            return
                except Exception:
                    continue
        except Exception as exc:
            logging.debug("Headless Accounts Center detail check failed for Firefox %s: %s", instance_number, exc)
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass

    def _add_facebook_cookies_to_driver(self, driver, cookies: dict[str, str]) -> None:
        logging.info("Cookie injection is disabled; no Facebook cookies were added to the browser.")

    def _wait_for_rendered_accounts_center_text(self, driver) -> str:
        body_text = ""
        for _attempt in range(12):
            try:
                body_text = str(driver.execute_script("return document.body ? document.body.innerText : '';") or "")
            except Exception:
                body_text = ""
            if (
                "Contact info" in body_text
                or "Birthday" in body_text
                or "Gender" in body_text
                or "Profiles and personal details" in body_text
            ):
                return body_text
            time.sleep(0.5)
        return body_text

    def _autofill_identity_from_rendered_text(self, instance_number: int, body_text: str, page_source: str = "") -> bool:
        if not body_text and not page_source:
            return False
        profile_name = ""
        date_birth = ""
        gmail = ""
        gender = ""
        try:
            profile_name, date_birth, gmail = self.app.browser._extract_accounts_center_identity_from_visible_text(body_text)
            gender = self.app.browser._extract_gender_from_visible_text(body_text)
        except Exception:
            pass
        if not gmail:
            gmail = self._extract_email_from_text_or_source("\n".join([body_text or "", page_source or ""]))
        if not date_birth:
            date_birth = self._extract_birthdate_from_text_or_source("\n".join([body_text or "", page_source or ""]))
        if not gender:
            gender = self._extract_gender_from_text_or_source(page_source or body_text, body_text)

        changed = False
        if profile_name and self.state.profile_names.get(instance_number) != profile_name:
            self.state.profile_names[instance_number] = profile_name
            changed = True
        before = dict(self._ensure_instance_report(instance_number))
        if gender or gmail or date_birth:
            self.set_profile_identity(
                instance_number,
                date_birth=date_birth,
                gender=gender,
                gmail=gmail,
                save_data=False,
                refresh_table=False,
            )
        after = self._ensure_instance_report(instance_number)
        return changed or before != after

    def _build_background_opener(self, proxy_url: str):
        handlers = []
        if proxy_url:
            handlers.append(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
        handlers.append(urllib.request.HTTPRedirectHandler())
        return urllib.request.build_opener(*handlers)

    def _autofill_route_ip_country(self, instance_number: int, opener) -> None:
        ip_address, country = self._lookup_route_ip_country(opener=opener)
        if ip_address or country:
            self.set_network_identity(
                instance_number,
                ip_address=ip_address,
                country=country,
                save_data=False,
                refresh_table=False,
            )

    def _lookup_route_ip_country(self, proxy_url: str = "", opener=None) -> tuple[str, str]:
        cache_key = str(proxy_url or "__direct__")
        now = time.time()
        cached = self._route_identity_cache.get(cache_key)
        if cached and now - cached[0] < 60:
            return cached[1], cached[2]
        if opener is None:
            opener = self._build_background_opener(proxy_url)
        endpoints = (
            "https://ipwho.is/",
            "https://ipapi.co/json/",
        )
        for endpoint in endpoints:
            try:
                request = urllib.request.Request(
                    endpoint,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "Mozilla/5.0",
                    },
                )
                with opener.open(request, timeout=12) as response:
                    payload = json.loads(response.read().decode("utf-8", errors="ignore") or "{}")
                ip_address = str(payload.get("ip") or "").strip()
                country = str(
                    payload.get("country")
                    or payload.get("country_name")
                    or payload.get("country_code")
                    or ""
                ).strip()
                if ip_address or country:
                    self._route_identity_cache[cache_key] = (now, ip_address, country)
                    return ip_address, country
            except Exception:
                continue
        return "", ""

    def allow_open_for_expected_country(self, instance_number: int) -> bool:
        expected_country = self.expected_country_for_instance(instance_number)
        if not expected_country:
            return True
        report = self._ensure_instance_report(instance_number)
        proxy_url = self._normalized_proxy_url(str(report.get("proxy", "") or ""))
        cache_key = str(proxy_url or "__direct__")
        if proxy_url == "unsupported":
            current_country = ""
            ip_address = ""
        else:
            ip_address, current_country = self._lookup_route_ip_country(proxy_url=proxy_url)
        # Strict country match only. The IP number may change, but the country must stay expected.
        if current_country and self._countries_match(current_country, expected_country):
            if ip_address or current_country:
                self.set_network_identity(
                    instance_number,
                    ip_address=ip_address,
                    country=current_country,
                    save_data=True,
                    refresh_table=True,
                )
            return True
        self._route_identity_cache.pop(cache_key, None)
        account_type = str(report.get("account_type") or expected_country).strip()
        self._warn_country_mismatch(account_type, expected_country, current_country)
        self.set_run_status(instance_number, "IP mismatch", DANGER)
        return False

    def expected_country_for_instance(self, instance_number: int) -> str:
        report = self._ensure_instance_report(instance_number)
        expected = str(report.get("expected_country") or "").strip()
        if expected:
            return expected
        account_type = str(report.get("account_type") or "").strip()
        if account_type:
            expected = self._expected_country_from_account_type(account_type)
            if expected:
                report["expected_country"] = expected
                return expected
        return ""

    def _expected_country_from_account_type(self, account_type: str) -> str:
        value = str(account_type or "").strip()
        normalized = self._country_compare_key(value)
        # This is not a fixed country list. It only expands common aliases;
        # every other account type is kept as the operator-entered country name.
        if normalized == "cambodia":
            return "Cambodia"
        if normalized == "united states":
            return "United States"
        if normalized == "canada":
            return "Canada"
        return value

    def _countries_match(self, current_country: str, expected_country: str) -> bool:
        current_key = self._country_compare_key(current_country)
        expected_key = self._country_compare_key(expected_country)
        return bool(current_key and expected_key and current_key == expected_key)

    def _country_compare_key(self, country: str) -> str:
        value = re.sub(r"[^a-z]+", " ", str(country or "").strip().lower())
        value = " ".join(value.split())
        # Aliases are convenience names only. Any country/account type not listed here
        # still works because the normalized text is compared directly.
        aliases = {
            "khmer": "cambodia",
            "cambodian": "cambodia",
            "kampuchea": "cambodia",
            "kh": "cambodia",
            "ca": "canada",
            "usa": "united states",
            "us": "united states",
            "u s": "united states",
            "u s a": "united states",
            "america": "united states",
            "united states of america": "united states",
            "uk": "united kingdom",
            "gb": "united kingdom",
            "great britain": "united kingdom",
        }
        return aliases.get(value, value)

    def _warn_country_mismatch(self, account_type: str, expected_country: str, current_country: str) -> None:
        account_label = str(account_type or expected_country or "This").strip()
        current = str(current_country or "").strip()
        if current:
            message = (
                f"{account_label} account expects {expected_country} IP, "
                f"but your current IP country is {current}.\n"
                f"Please change VPN/proxy to {expected_country} before opening this account."
            )
        else:
            message = (
                f"{account_label} account expects {expected_country} IP, "
                "but your current IP country could not be checked.\n"
                f"Please change VPN/proxy to {expected_country} before opening this account."
            )
        try:
            self.app.root.after(0, lambda: self.app.messagebox.showwarning("VPN/Proxy Country Mismatch", message))
        except Exception:
            self.app.messagebox.showwarning("VPN/Proxy Country Mismatch", message)

    def _autofill_identity_from_background_body(self, instance_number: int, body: str) -> None:
        if not body:
            return
        report = self._ensure_instance_report(instance_number)
        profile_name = self._extract_profile_name_from_text_or_source(body)
        gender = self._extract_gender_from_text_or_source(body, body)
        gmail = self._extract_email_from_text_or_source(body)
        date_birth = self._extract_birthdate_from_text_or_source(body)
        if profile_name and self.state.profile_names.get(instance_number) != profile_name:
            self.state.profile_names[instance_number] = profile_name
        if gender or gmail or date_birth:
            self.set_profile_identity(
                instance_number,
                date_birth=date_birth,
                gender=gender,
                gmail=gmail,
                save_data=False,
                refresh_table=False,
            )

    def _extract_profile_name_from_text_or_source(self, source: str) -> str:
        text = self._plain_text_from_source(source)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            if line.lower() != "profiles":
                continue
            for candidate in lines[index + 1 : index + 10]:
                if self._looks_generic_profile_text(candidate):
                    continue
                if "@" in candidate:
                    continue
                return candidate
        source_text = self._decode_web_text(source)
        patterns = (
            r'"profile_name"\s*:\s*"([^"]{2,120})"',
            r'"full_name"\s*:\s*"([^"]{2,120})"',
            r'"name"\s*:\s*"([^"]{2,120})"',
        )
        for pattern in patterns:
            for match in re.findall(pattern, source_text, flags=re.IGNORECASE):
                candidate = str(match or "").strip()
                if candidate and not self._looks_generic_profile_text(candidate) and "@" not in candidate:
                    return candidate
        return ""

    def _looks_generic_profile_text(self, value: str) -> bool:
        normalized = re.sub(r"\s+", " ", str(value or "").strip()).lower()
        if not normalized:
            return True
        return normalized in {
            "facebook",
            "profiles",
            "profile",
            "personal details",
            "profiles and personal details",
            "add accounts",
            "accounts center",
            "meta",
            "account settings",
            "contact info",
            "birthday",
            "manage accounts",
        }

    def _has_report_value(self, value: object) -> bool:
        text = str(value or "").strip()
        return bool(text and text not in {"-", "No Gmail"})

    def _extract_gender_from_text_or_source(self, source: str, body_text: str = "") -> str:
        source_text = urllib.parse.unquote(self._decode_web_text(source))
        gender_json_patterns = (
            r'"gender"\s*:\s*"([A-Za-z_ ]+)"',
            r'"gender_label"\s*:\s*"([A-Za-z_ ]+)"',
            r'"gender_display"\s*:\s*"([A-Za-z_ ]+)"',
            r'"selected_gender"\s*:\s*"([A-Za-z_ ]+)"',
        )
        for pattern in gender_json_patterns:
            gender_json = re.search(pattern, source_text, flags=re.IGNORECASE)
            if gender_json:
                gender = self._normalize_gender(gender_json.group(1))
                if gender in {"Female", "Male", "Custom"}:
                    return gender
        text = self._plain_text_from_source(body_text or source)
        patterns = (
            r"\bGender\s+(Female|Male|Custom)\b",
            r"\b(Female|Male|Custom)\s+Gender\b",
            r"\bGender\s*\n\s*(Female|Male|Custom)\b",
            r"\b(Female|Male|Custom)\s*\n\s*Gender\b",
            r"\bGender\s*[:\-]\s*(Female|Male|Custom)\b",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                for group in match.groups():
                    gender = self._normalize_gender(group)
                    if gender in {"Female", "Male", "Custom"}:
                        return gender
        return ""

    def _extract_birthdate_from_text_or_source(self, source: str) -> str:
        source_text = self._decode_web_text(source)
        birth_json = re.search(
            r'"birthdate"\s*:\s*\{\s*"day"\s*:\s*(\d{1,2})\s*,\s*"month"\s*:\s*(\d{1,2})\s*,\s*"year"\s*:\s*(\d{4})',
            source_text,
        )
        if birth_json:
            day, month, year = birth_json.group(1), birth_json.group(2), birth_json.group(3)
            return f"{year}-{int(month):02d}-{int(day):02d}"
        return ""

    def _extract_email_from_text_or_source(self, source: str) -> str:
        source_text = urllib.parse.unquote(self._decode_web_text(source))
        plain_text = self._plain_text_from_source(source_text)
        email_pattern = r"([A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"
        candidates = []
        source_patterns = (
            r'"(?:primary_)?email"\s*:\s*"([^"]+@[^"]+)"',
            r'"(?:normalized_)?email_address"\s*:\s*"([^"]+@[^"]+)"',
            r'"contact(?:_point)?"\s*:\s*"([^"]+@[^"]+)"',
            r'"display_value"\s*:\s*"([^"]+@[^"]+)"',
            r'"subtitle"\s*:\s*"([^"]+@[^"]+)"',
        )
        for pattern in source_patterns:
            for match in re.findall(pattern, source_text, flags=re.IGNORECASE):
                candidates.append(str(match or "").strip())
        for match in re.findall(email_pattern, source_text):
            candidates.append(str(match or "").strip())
        text_patterns = (
            r"Contact info\s*\n\s*([^\n]+@[^\n]+)",
            r"Email(?: address)?\s*\n\s*([^\n]+@[^\n]+)",
        )
        for pattern in text_patterns:
            for match in re.findall(pattern, plain_text, flags=re.IGNORECASE):
                candidates.append(str(match or "").strip())
        valid = []
        for candidate in candidates:
            clean = str(candidate or "").strip().replace("\\", "")
            clean = re.sub(r"^[\"'(<\[]+|[\"'),<>\].;:]+$", "", clean)
            clean = re.sub(r"[,\s]+$", "", clean)
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

    def _decode_web_text(self, value: object) -> str:
        text = unescape(str(value or "")).replace("\\/", "/")
        text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)
        return text.replace('\\"', '"')

    def _plain_text_from_source(self, value: object) -> str:
        text = self._decode_web_text(value)
        text = re.sub(r"(?is)<(script|style).*?</\1>", "\n", text)
        text = re.sub(r"(?is)<[^>]+>", "\n", text)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n+", "\n", text)
        return text

    def _normalize_gender(self, value: str) -> str:
        raw = str(value or "").strip().replace("_", " ").lower()
        if not raw:
            return ""
        if "female" in raw:
            return "Female"
        if "male" in raw:
            return "Male"
        return raw.title()

    def _normalized_proxy_url(self, proxy: str) -> str:
        value = str(proxy or "").strip()
        if not value:
            return ""
        lower = value.lower()
        if lower.startswith(("socks://", "socks4://", "socks5://")):
            return "unsupported"
        if "://" not in value:
            return f"http://{value}"
        if lower.startswith(("http://", "https://")):
            return value
        return "unsupported"

    def _proxy_host(self, proxy: str) -> str:
        value = str(proxy or "").strip()
        if not value:
            return ""
        value = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", value)
        if "@" in value:
            value = value.rsplit("@", 1)[1]
        return value.split(":", 1)[0].strip()

    def _website_name_from_url(self, url: str) -> str:
        value = str(url or "").strip()
        if not value:
            return ""
        try:
            parsed = urllib.parse.urlparse(value if "://" in value else f"https://{value}")
            host = parsed.netloc or parsed.path
        except Exception:
            host = value
        host = host.split("@")[-1].split(":")[0].strip().lower()
        return host.removeprefix("www.") or value

    def _has_required_login_cookie(self, platform: str, cookies: dict[str, str]) -> bool:
        if platform == "facebook":
            return bool(str(cookies.get("c_user") or "").strip().isdigit())
        if platform == "tiktok":
            return any(name in cookies for name in ("sessionid", "sessionid_ss", "sid_guard"))
        if platform == "youtube":
            return any(name in cookies for name in ("SAPISID", "__Secure-1PSID", "__Secure-3PSID", "SID", "HSID", "SSID", "APISID"))
        if platform == "instagram":
            return "sessionid" in cookies
        if platform == "wordpress":
            return any("wordpress" in name.lower() for name in cookies) or bool(cookies)
        return bool(cookies)

    def _load_session_cookies(self, instance_number: int, platform: str) -> dict[str, str]:
        logging.info("Cookie extraction is disabled; using official authorization status only.")
        return {}

    def _load_json_cookie_file(self, instance_number: int, platform: str) -> dict[str, str]:
        cookie_path = self._cookie_file_for_platform(instance_number, platform)
        if not cookie_path.exists():
            return {}
        try:
            with cookie_path.open("r", encoding="utf-8") as handle:
                raw_cookies = json.load(handle)
        except Exception:
            return {}
        output: dict[str, str] = {}
        for cookie in raw_cookies if isinstance(raw_cookies, list) else []:
            name = str(cookie.get("name", "") or "").strip()
            value = str(cookie.get("value", "") or "").strip()
            if name and value:
                output[name] = value
        return output

    def _load_firefox_sqlite_cookies(self, instance_number: int, platform: str) -> dict[str, str]:
        cookie_db = self.firefox_profile_dir(instance_number, platform) / "cookies.sqlite"
        if not cookie_db.exists():
            return {}
        domains = {
            "facebook": ("facebook.com",),
            "tiktok": ("tiktok.com",),
            "youtube": ("youtube.com", "google.com"),
            "instagram": ("instagram.com",),
            "wordpress": ("wordpress.com", "wp.com"),
        }.get(platform, ())
        output: dict[str, str] = {}
        try:
            conn = sqlite3.connect(f"file:{cookie_db}?mode=ro", uri=True, timeout=1)
            try:
                rows = conn.execute("SELECT host, name, value FROM moz_cookies").fetchall()
            finally:
                conn.close()
        except Exception:
            return {}
        for host, name, value in rows:
            host_text = str(host or "").lower()
            if domains and not any(domain in host_text for domain in domains):
                continue
            name_text = str(name or "").strip()
            value_text = str(value or "").strip()
            if name_text and value_text:
                output[name_text] = value_text
        return output

    def _cookie_file_for_platform(self, instance_number: int, platform: str):
        return cookie_dir_for_platform(platform) / f"cookies_{instance_number}.json"

    def _cookie_header(self, cookies: dict[str, str]) -> str:
        return "; ".join(f"{name}={value}" for name, value in cookies.items())

    def _classify_http_session(
        self,
        platform: str,
        final_url: str,
        status_code: int,
        body: str,
        cookies: dict[str, str],
    ) -> tuple[str, str, str]:
        current_url = final_url.lower()
        text = body.lower()
        if status_code in {401, 403}:
            return "Review", f"Background check returned HTTP {status_code}; review this account/session.", WARNING
        disabled_markers = (
            "checkpoint/disabled",
            "account disabled",
            "account has been disabled",
            "your account was disabled",
            "your account has been suspended",
            "account suspended",
            "account permanently disabled",
            "we disabled your account",
            "no longer request a review",
        )
        if any(marker in current_url or marker in text for marker in disabled_markers):
            return "Disabled", "Platform reports the account/session is disabled or suspended.", DANGER
        if any(marker in current_url or marker in text for marker in ("checkpoint", "challenge", "verify your identity", "suspicious activity")):
            return "Checkpoint", "Platform is asking for verification/checkpoint.", DANGER

        if platform == "facebook":
            if "c_user" not in cookies:
                return "Login required", "Facebook c_user session cookie was not found.", DANGER
            login_markers = ('name="email"', 'id="email"', 'data-testid="royal_email"', 'name="pass"', "facebook.com/login")
            if any(marker in current_url or marker in text for marker in login_markers):
                return "Login required", "Facebook returned a login page for this saved session.", DANGER
            return "Live", "Background cookie check reached Facebook without login/checkpoint screen.", SUCCESS

        if platform == "tiktok":
            if "login" in current_url or "login to tiktok" in text:
                return "Login required", "TikTok returned a login page for this saved session.", DANGER
            return "Live", "Background cookie check reached TikTok without login/challenge screen.", SUCCESS

        if platform == "youtube":
            if "accounts.google.com" in current_url or "signin" in current_url:
                return "Login required", "YouTube/Google returned a sign-in page for this saved session.", DANGER
            return "Live", "Background cookie check reached YouTube without sign-in/challenge screen.", SUCCESS

        if platform == "instagram":
            if "accounts/login" in current_url or "login" in current_url:
                return "Login required", "Instagram returned a login page for this saved session.", DANGER
            return "Live", "Background cookie check reached Instagram without login/challenge screen.", SUCCESS

        if platform == "wordpress":
            if "log-in" in current_url or "login" in current_url or "sign in" in text:
                return "Login required", "WordPress returned a login page for this saved session/API check.", DANGER
            return "Live", "WordPress session/API page opened without login/challenge screen.", SUCCESS

        return "Review", "Could not confidently classify this account from the background response.", WARNING

    def _record_live_check_result(self, instance_number: int, status: str, color: str, note: str) -> None:
        report = self._ensure_instance_report(instance_number)
        if str(status or "").strip().lower() in {"ip mismatch", "ip unknown"}:
            report["last_action"] = "Stop"
        else:
            report["last_action"] = "Check Login"
        if str(status or "").strip().lower() == "live" and not self._has_report_value(report.get("gmail")):
            report["gmail"] = "No Gmail"
        report["last_status"] = status
        report["last_note"] = note
        report["account_status"] = status
        report["account_reason"] = note
        report["account_checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if status == "Live":
            report["success_count"] = int(report.get("success_count", 0)) + 1
        elif status != "Checking":
            report["fail_count"] = int(report.get("fail_count", 0)) + 1
        self.set_run_status(instance_number, status, color, persist_report=False)

    def _classify_platform_session(self, driver, platform: str) -> tuple[str, str, str]:
        try:
            current_url = str(driver.current_url or "").lower()
            title = str(driver.title or "").lower()
            body = str(driver.page_source or "").lower()[:500000]
        except Exception as exc:
            return "Check error", f"Could not read page: {exc}", DANGER

        disabled_markers = (
            "checkpoint/disabled",
            "account disabled",
            "account has been disabled",
            "your account was disabled",
            "your account has been suspended",
            "account suspended",
            "account permanently disabled",
            "violated our terms",
            "we disabled your account",
            "no longer request a review",
        )
        checkpoint_markers = (
            "checkpoint",
            "security check",
            "confirm your identity",
            "verify your identity",
            "suspicious activity",
            "challenge_required",
            "challenge",
            "verification required",
            "unusual activity",
        )
        login_markers = (
            "login",
            "log in",
            "sign in",
            "signup",
            "sign up",
            "password",
        )

        if any(marker in current_url or marker in title or marker in body for marker in disabled_markers):
            return "Disabled", "Platform reports the account/session is disabled or suspended.", DANGER
        if any(marker in current_url or marker in title or marker in body for marker in checkpoint_markers):
            return "Checkpoint", "Platform is asking for verification/checkpoint.", DANGER

        if platform == "facebook":
            login_form_markers = (
                'name="email"',
                'id="email"',
                'data-testid="royal_email"',
                'name="pass"',
                'facebook helps you connect and share',
            )
            if "facebook.com/login" in current_url or "/checkpoint/" in current_url:
                return "Login required", "Facebook session is not logged in or needs checkpoint.", DANGER
            if any(marker in body for marker in login_form_markers):
                return "Login required", "Facebook login form is visible in this browser profile.", DANGER
            if "facebook.com" in current_url and "login" not in current_url:
                return "Live", "Facebook opened without checkpoint or disabled screen.", SUCCESS
        elif platform == "tiktok":
            if "login" in current_url or "login to tiktok" in body:
                return "Login required", "TikTok session is not logged in.", DANGER
            if "tiktok.com" in current_url:
                return "Live", "TikTok session opened without disabled/challenge screen.", SUCCESS
        elif platform == "youtube":
            if "accounts.google.com" in current_url or "signin" in current_url:
                return "Login required", "YouTube/Google session is not signed in.", DANGER
            if "youtube.com" in current_url or "studio.youtube.com" in current_url:
                return "Live", "YouTube session opened without disabled/challenge screen.", SUCCESS
        elif platform == "instagram":
            if "accounts/login" in current_url or "login" in current_url:
                return "Login required", "Instagram session is not logged in.", DANGER
            if "instagram.com" in current_url:
                return "Live", "Instagram session opened without disabled/challenge screen.", SUCCESS
        elif platform == "wordpress":
            if "login" in current_url or "log-in" in current_url or "sign in" in body:
                return "Login required", "WordPress session/API login is not active.", DANGER
            if "wordpress.com" in current_url or "wp-admin" in current_url:
                return "Live", "WordPress session opened without disabled/challenge screen.", SUCCESS

        if any(marker in current_url or marker in title for marker in login_markers):
            return "Login required", "Session appears logged out.", DANGER
        return "Review", "Could not confidently classify this account; review the browser page.", WARNING

    def _classify_running_browser_session(self, instance_number: int, platform: str) -> tuple[str, str, str] | None:
        driver = self.state.drivers.get(instance_number)
        if not driver:
            return None
        try:
            status, note, color = self._classify_platform_session(driver, platform)
        except Exception:
            return None
        if status in {"Disabled", "Checkpoint", "Live", "Login required"}:
            return status, f"Open Firefox page check: {note}", color
        return None

    def _platform_label(self, platform: str) -> str:
        for label, value in self.app.PLATFORMS:
            if value == platform:
                return label
        return platform.title()

    def _run_batch_instances(self, instance_numbers: list[int], max_workers: int) -> None:
        semaphore = threading.Semaphore(max_workers)
        threads: list[threading.Thread] = []

        def worker(instance_number: int) -> None:
            with semaphore:
                if self.state.batch_stop_requested:
                    self.set_run_status(instance_number, "Stopped", WARNING)
                    return
                self.run_firefox_instance(instance_number)

        try:
            for instance_number in instance_numbers:
                if self.state.batch_stop_requested:
                    break
                thread = threading.Thread(target=worker, args=(instance_number,), daemon=True)
                threads.append(thread)
                thread.start()
                time.sleep(0.05)
            for thread in threads:
                thread.join()
        finally:
            self.state.batch_running = False
            self.state.batch_stop_requested = False
            self.app.refresh_dashboard()

    def active_instance_numbers(self) -> list[int]:
        numbers = {
            i + 1
            for i, (_button, frame) in enumerate(self.state.firefox_buttons)
            if frame is not None
        }
        numbers.update(self.state.instance_names.keys())
        numbers.update(self.state.profile_names.keys())
        numbers.update(self.state.run_states.keys())
        numbers.update(self.state.instance_reports.keys())
        return sorted(number for number in numbers if number not in self.state.deleted_instances)

    def _selected_account_type_from_app(self) -> str:
        selector = getattr(self.app, "_selected_account_type", None)
        if callable(selector):
            try:
                return str(selector() or "").strip()
            except Exception:
                return ""
        return ""

    def report_matches_account_type(self, report: dict, account_type: str) -> bool:
        selected = str(account_type or "").strip()
        if not selected or selected.lower() in {"all", "store"}:
            return True
        selected_lower = selected.lower()

        account_type_value = str(report.get("country_type") or report.get("account_type", "") or "").strip()
        country_value = str(report.get("country", "") or "").strip()

        # Country Type is the saved account/country grouping. Current country is detected
        # from IP/proxy and can differ, so it must not mix groups.
        values = [account_type_value] if account_type_value and account_type_value != "-" else [country_value]
        normalized_values = {value.lower() for value in values if value and value != "-"}
        if selected_lower in normalized_values:
            return True
        khmer_aliases = {"khmer", "cambodia", "cambodian", "kampuchea"}
        if selected_lower in khmer_aliases and normalized_values.intersection(khmer_aliases):
            return True
        usa_aliases = {"usa", "us", "u.s.", "u.s.a.", "united states", "united states of america", "america"}
        if selected_lower in usa_aliases and normalized_values.intersection(usa_aliases):
            return True
        return any(selected_lower in value for value in normalized_values)

    def instance_matches_account_type(self, instance_number: int, account_type: str) -> bool:
        report = self._ensure_instance_report(instance_number)
        return self.report_matches_account_type(report, account_type)

    def active_instance_numbers_for_type(self, account_type: str | None = None) -> list[int]:
        self._ensure_local_indexes()
        selected = str(account_type or "").strip()
        numbers = self.active_instance_numbers()
        if not selected or selected.lower() in {"all", "store"}:
            return numbers
        return [number for number in numbers if self.instance_matches_account_type(number, selected)]

    def _next_available_instance_number(self) -> int:
        used = set(self.active_instance_numbers())
        used.update(self.state.deleted_instances)
        used.update(self.state.instance_names.keys())
        used.update(self.state.profile_names.keys())
        used.update(self.state.run_states.keys())
        used.update(self.state.instance_reports.keys())
        next_number = 1
        while next_number in used:
            next_number += 1
        return next_number

    def _instance_number_for_local_type(self, account_type: str, local_index: int) -> int | None:
        clean_type = str(account_type or "").strip().lower()
        if not clean_type:
            return None
        for instance_number in self.active_instance_numbers():
            report = self._ensure_instance_report(instance_number)
            report_type = str(report.get("account_type") or report.get("country") or "").strip().lower()
            try:
                saved_local = int(report.get("local_index") or 0)
            except Exception:
                saved_local = 0
            if report_type == clean_type and saved_local == local_index:
                return instance_number
        return None

    def _next_local_index_for_type(self, account_type: str) -> int:
        clean_type = str(account_type or "").strip().lower()
        used: set[int] = set()
        if not clean_type:
            return len(self.active_instance_numbers()) + 1
        for instance_number in self.active_instance_numbers():
            report = self._ensure_instance_report(instance_number)
            report_type = str(report.get("account_type") or report.get("country") or "").strip().lower()
            if report_type != clean_type:
                continue
            try:
                local_index = int(report.get("local_index") or 0)
            except Exception:
                local_index = 0
            if local_index > 0:
                used.add(local_index)
        next_index = 1
        while next_index in used:
            next_index += 1
        return next_index

    def _ensure_local_indexes(self) -> None:
        used_by_type: dict[str, set[int]] = {}
        pending_by_type: dict[str, list[int]] = {}
        for instance_number in self.active_instance_numbers():
            report = self._ensure_instance_report(instance_number)
            account_type = str(report.get("account_type") or report.get("country") or "").strip()
            if not account_type:
                continue
            key = account_type.lower()
            try:
                local_index = int(report.get("local_index") or 0)
            except Exception:
                local_index = 0
            if local_index > 0:
                used_by_type.setdefault(key, set()).add(local_index)
            else:
                pending_by_type.setdefault(key, []).append(instance_number)

        for key, instance_numbers in pending_by_type.items():
            used = used_by_type.setdefault(key, set())
            next_index = 1
            for instance_number in sorted(instance_numbers):
                while next_index in used:
                    next_index += 1
                report = self._ensure_instance_report(instance_number)
                report["local_index"] = next_index
                account_type = str(report.get("account_type") or report.get("country") or "").strip()
                if account_type and not str(self.state.instance_names.get(instance_number, "")).strip():
                    self.state.instance_names[instance_number] = f"{account_type} {next_index}"
                used.add(next_index)

    def _instance_frame_exists(self, instance_number: int) -> bool:
        index = instance_number - 1
        return 0 <= index < len(self.state.firefox_buttons) and self.state.firefox_buttons[index][1] is not None

    def is_instance_busy(self, instance_number: int) -> bool:
        status = str(self.state.run_states.get(instance_number, "")).strip().lower()
        return any(marker in status for marker in ("queue", "launch", "run", "wait", "process"))

    def mark_instance_status(self, instance_number: int, status: str) -> None:
        normalized = status.strip() or "Idle"
        color = TEXT_MUTED
        lower_status = normalized.lower()
        if lower_status in {"live", "done", "ready", "success"}:
            color = SUCCESS
        elif lower_status in {"die", "dead", "failed", "disabled"}:
            color = DANGER
        elif lower_status in {"processing", "queued", "waiting"}:
            color = WARNING
        self._update_instance_report(
            instance_number,
            action="Manual Status",
            status=normalized,
            note="Set from table context menu",
        )
        if lower_status in {"live", "die", "dead", "failed", "disabled", "checkpoint", "login required"}:
            self.set_account_health(
                instance_number,
                "Live" if lower_status in {"live", "done", "ready", "success"} else normalized,
                "Set from table context menu",
                save_data=False,
                refresh_table=False,
            )
        self.set_run_status(instance_number, normalized, color)

    def generate_firefox_instances(self) -> None:
        start_index = self.app.simpledialog.askinteger("Input", "Enter the starting instance index:", minvalue=1)
        if start_index is None:
            return

        end_index = self.app.simpledialog.askinteger(
            "Input",
            "Enter the ending instance index (put the same number if generate just one):",
            minvalue=start_index,
        )
        if end_index is None:
            end_index = start_index

        selected_type = self._selected_account_type_from_app()
        if selected_type:
            generated_instances: list[int] = []
            for local_index in range(start_index, end_index + 1):
                instance_number = self._instance_number_for_local_type(selected_type, local_index)
                if instance_number is None:
                    instance_number = self._next_available_instance_number()
                self.state.deleted_instances.discard(instance_number)
                self.state.instance_names[instance_number] = f"{selected_type} {local_index}"
                report = self._ensure_instance_report(instance_number)
                report["account_type"] = selected_type
                report["expected_country"] = self._expected_country_from_account_type(selected_type)
                report["local_index"] = local_index
                if not self._instance_frame_exists(instance_number):
                    self.open_firefox_instances(1, start_index=instance_number)
                generated_instances.append(instance_number)

            self.save_instance_data()
            self.sync_local_profiles_to_backend_async(generated_instances)
            self.app.refresh_dashboard()
            return

        for i in range(start_index, end_index + 1):
            self.state.deleted_instances.discard(i)

        self.open_firefox_instances(end_index - start_index + 1, start_index=start_index)
        self.save_instance_data()
        self.sync_local_profiles_to_backend_async(list(range(start_index, end_index + 1)))
        self.app.refresh_dashboard()

    def save_instance_data(self) -> None:
        current_state = self._snapshot_current_platform_state()
        self.platform_states[self.vars.platform_var.get()] = current_state
        platform_states = self._serializable_platform_states()
        data = {
            "credentials": current_state["credentials"],
            "instance_names": current_state["instance_names"],
            "profile_names": current_state["profile_names"],
            "preview_updated_at": current_state["preview_updated_at"],
            "run_states": current_state["run_states"],
            "instance_reports": current_state["instance_reports"],
            "backend_profile_ids": current_state["backend_profile_ids"],
            "photo_upload_paths": current_state["photo_upload_paths"],
            "cover_upload_paths": current_state["cover_upload_paths"],
            "photo_upload_descriptions": current_state["photo_upload_descriptions"],
            "browser_mode": self.vars.browser_mode_var.get(),
            "platform_mode": self.vars.platform_var.get(),
            "thread_count": int(self.vars.thread_count_var.get() or 3),
            "platform_states": platform_states,
            "deleted_instances": list(current_state["deleted_instances"]),
            "active_instances": current_state["active_instances"],
            "country_types": [
                value for value in getattr(self.app, "legacy_stores", ["All"]) if str(value or "").strip()
            ],
            "custom_account_types": [
                value for value in getattr(self.app, "account_groups", ["All"]) if str(value or "").strip()
            ],
        }
        self._write_platform_data_files(platform_states)
        self.storage.save_state(data)
        with DATA_FILE.open("w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def backup_instance_data(self) -> None:
        current_state = self._snapshot_current_platform_state()
        self.platform_states[self.vars.platform_var.get()] = current_state
        platform_states = self._serializable_platform_states()
        data = {
            "credentials": current_state["credentials"],
            "instance_names": current_state["instance_names"],
            "profile_names": current_state["profile_names"],
            "preview_updated_at": current_state["preview_updated_at"],
            "run_states": current_state["run_states"],
            "instance_reports": current_state["instance_reports"],
            "backend_profile_ids": current_state["backend_profile_ids"],
            "photo_upload_paths": current_state["photo_upload_paths"],
            "cover_upload_paths": current_state["cover_upload_paths"],
            "photo_upload_descriptions": current_state["photo_upload_descriptions"],
            "browser_mode": self.vars.browser_mode_var.get(),
            "platform_mode": self.vars.platform_var.get(),
            "thread_count": int(self.vars.thread_count_var.get() or 3),
            "platform_states": platform_states,
            "deleted_instances": list(current_state["deleted_instances"]),
            "active_instances": current_state["active_instances"],
            "country_types": [
                value for value in getattr(self.app, "legacy_stores", ["All"]) if str(value or "").strip()
            ],
            "custom_account_types": [
                value for value in getattr(self.app, "account_groups", ["All"]) if str(value or "").strip()
            ],
        }
        self._write_platform_data_files(platform_states)
        self.storage.write_backup(data)

    def import_account_rows(self, rows: list[dict[str, str]]) -> int:
        imported = 0
        existing_ids = {
            *self.state.instance_names.keys(),
            *self.state.profile_names.keys(),
            *self.state.run_states.keys(),
            *self.state.instance_reports.keys(),
            *{
                i + 1
                for i, (_button, frame) in enumerate(self.state.firefox_buttons)
                if frame is not None
            },
        }
        next_instance = max(existing_ids | {0}) + 1

        for source_row in rows:
            clean_row = {
                str(key).strip().lower().replace(" ", "_"): str(value or "").strip()
                for key, value in source_row.items()
            }
            platform = self.vars.platform_var.get()
            account_id = (
                clean_row.get("uid")
                or clean_row.get("account_id")
                or clean_row.get("id")
                or clean_row.get(f"{platform}_id")
                or clean_row.get("facebook_id")
                or clean_row.get("tiktok_user_id")
                or clean_row.get("instagram_user_id")
                or clean_row.get("channel_id")
            )
            profile_name = (
                clean_row.get("name")
                or clean_row.get("account_name")
                or clean_row.get("profile")
                or clean_row.get("facebook_name")
                or clean_row.get("tiktok_username")
                or clean_row.get("instagram_username")
                or clean_row.get("channel_name")
                or clean_row.get("website_name")
            )
            gmail = clean_row.get("gmail") or clean_row.get("email")
            date_birth = clean_row.get("date_birth") or clean_row.get("birthday") or clean_row.get("birthdate")
            gender = clean_row.get("gender") or clean_row.get("sex")
            ip_address = clean_row.get("ip") or clean_row.get("account_ip") or clean_row.get("proxy_ip")
            country = clean_row.get("country") or clean_row.get("account_country") or clean_row.get("region")
            expected_country = clean_row.get("expected_country") or clean_row.get("target_country") or clean_row.get("vpn_country")
            proxy = clean_row.get("proxy") or clean_row.get("proxy_url") or clean_row.get("socks") or clean_row.get("http_proxy")
            explicit_country_type = clean_row.get("country_type") or clean_row.get("country_group")
            custom_account_type = (
                clean_row.get("custom_account_type")
                or clean_row.get("account_group")
                or clean_row.get("usage_type")
                or clean_row.get("work_type")
            )
            legacy_type_value = clean_row.get("account_type") or clean_row.get("type")
            if explicit_country_type:
                account_type = explicit_country_type
                custom_account_type = custom_account_type or legacy_type_value
            else:
                account_type = (
                    legacy_type_value
                    or clean_row.get("store")
                    or clean_row.get("group")
                    or self._selected_account_type_from_app()
                    or country
                )
            try:
                local_index = int(
                    clean_row.get("local_index")
                    or clean_row.get("local")
                    or clean_row.get("no")
                    or clean_row.get("number")
                    or 0
                )
            except Exception:
                local_index = 0
            if account_type and local_index <= 0:
                local_index = self._next_local_index_for_type(account_type)
            if proxy and not ip_address:
                ip_address = self._proxy_host(proxy)
            status = clean_row.get("status") or "Need Reconnect"
            api_token = clean_row.get("api_token") or clean_row.get("application_password")

            while next_instance in self.state.deleted_instances:
                next_instance += 1

            if account_type and local_index > 0:
                self.state.instance_names[next_instance] = f"{account_type} {local_index}"
            else:
                self.state.instance_names[next_instance] = f"Firefox {next_instance}"
            self.open_firefox_instances(1, start_index=next_instance)
            if profile_name:
                self.state.profile_names[next_instance] = profile_name
            report = self._ensure_instance_report(next_instance)
            report["platform"] = platform
            if account_id:
                report["account_id"] = account_id
            if gmail:
                report["gmail"] = gmail
                report["gmail_login"] = "Need Reconnect"
            if date_birth:
                report["date_birth"] = date_birth
            if gender:
                report["gender"] = self._normalize_gender(gender)
            if ip_address:
                report["ip"] = ip_address
            if country:
                report["country"] = country
            if proxy:
                report["proxy"] = proxy
            if account_type:
                report["account_type"] = account_type
                report["expected_country"] = expected_country or self._expected_country_from_account_type(account_type)
            elif expected_country:
                report["expected_country"] = expected_country
            if custom_account_type:
                report["custom_account_type"] = custom_account_type
            if local_index > 0:
                report["local_index"] = local_index
            if platform == "tiktok":
                report["tiktok_username"] = clean_row.get("tiktok_username") or clean_row.get("username") or profile_name
                report["tiktok_user_id"] = clean_row.get("tiktok_user_id") or account_id
                report["tiktok_session"] = "Need Reconnect"
            elif platform == "youtube":
                report["youtube_channel_name"] = clean_row.get("channel_name") or profile_name
                report["channel_id"] = clean_row.get("channel_id") or account_id
                report["channel_url"] = clean_row.get("channel_url", "")
                report["brand_channel"] = clean_row.get("brand_channel") or "-"
                report["gmail_login"] = "Need Reconnect" if gmail else "-"
            elif platform == "instagram":
                report["instagram_username"] = clean_row.get("instagram_username") or clean_row.get("username") or profile_name
                report["instagram_user_id"] = clean_row.get("instagram_user_id") or account_id
                report["instagram_session"] = "Need Reconnect"
            elif platform == "wordpress":
                site_url = clean_row.get("site_url") or clean_row.get("wordpress_site_url")
                report["wordpress_site_url"] = site_url
                report["website_name"] = clean_row.get("website_name") or self._website_name_from_url(site_url)
                report["wordpress_username"] = clean_row.get("username") or clean_row.get("wordpress_username") or profile_name
                report["author_name"] = clean_row.get("author_name") or report["wordpress_username"]
                report["posting_type"] = clean_row.get("posting_type") or "Article"
                report["default_category"] = clean_row.get("default_category") or "-"
                report["api_login_status"] = "Token Valid" if api_token else "Need Reconnect"
                if api_token:
                    self.auth.save_auth(
                        platform,
                        self.auth_key_for_instance(platform, next_instance),
                        {
                            "site_url": site_url,
                            "username": report["wordpress_username"],
                            "application_password": api_token,
                        },
                    )
                    status = "Token Valid"
            elif platform == "facebook":
                report["facebook_session"] = "Need Reconnect"
            report["last_action"] = "Imported"
            report["last_status"] = status
            report["account_status"] = status
            report["account_reason"] = "Imported account row"
            report["account_checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            report["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.state.run_states[next_instance] = status
            self._apply_saved_run_status(next_instance)
            self._load_saved_media(next_instance)
            imported += 1
            next_instance += 1

        if imported:
            self.save_instance_data()
            self.sync_local_profiles_to_backend_async()
            if hasattr(self.app, "refresh_report_table"):
                self.app.refresh_report_table()
            self.app.refresh_dashboard()
        return imported

    def export_report_csv(self, output_path: str) -> int:
        rows = self.get_report_rows()
        platform = self.vars.platform_var.get()
        fieldnames = [key for key, _title, _width in PLATFORM_CONFIG.get(platform, PLATFORM_CONFIG["facebook"])["columns"]]
        with open(output_path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return len(rows)

    def load_instance_data(
        self,
    ) -> tuple[
        dict[int, str],
        dict[int, str],
        dict[int, str],
        dict[int, str],
        dict[int, str],
        dict[int, dict],
        dict[int, str],
        dict[int, str],
        dict[int, str],
        dict[int, str],
        str,
        str,
        int,
        set[int],
        list[int],
        dict,
    ]:
        data = self.storage.load_state()
        if data is None:
            if not DATA_FILE.exists():
                return {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, "pc", "facebook", 3, set(), [], {}
            with DATA_FILE.open("r", encoding="utf-8") as handle:
                data = json.load(handle)

        credentials = {int(key): value for key, value in data.get("credentials", {}).items()}
        instance_names = {int(key): value for key, value in data.get("instance_names", {}).items()}
        profile_names = {int(key): value for key, value in data.get("profile_names", {}).items()}
        preview_updated_at = {int(key): value for key, value in data.get("preview_updated_at", {}).items()}
        run_states = {int(key): value for key, value in data.get("run_states", {}).items()}
        instance_reports = {
            int(key): value for key, value in data.get("instance_reports", {}).items() if isinstance(value, dict)
        }
        backend_profile_ids = {
            int(key): str(value)
            for key, value in data.get("backend_profile_ids", {}).items()
            if value
        }
        photo_upload_paths = {int(key): str(value) for key, value in data.get("photo_upload_paths", {}).items() if value}
        cover_upload_paths = {int(key): str(value) for key, value in data.get("cover_upload_paths", {}).items() if value}
        photo_upload_descriptions = {
            int(key): str(value) for key, value in data.get("photo_upload_descriptions", {}).items() if value is not None
        }
        browser_mode = str(data.get("browser_mode") or "pc")
        if browser_mode not in {"pc", "phone"}:
            browser_mode = "pc"
        platform_mode = str(data.get("platform_mode") or "facebook")
        if platform_mode not in self.PLATFORM_HOME_URLS:
            platform_mode = "facebook"
        try:
            thread_count = int(data.get("thread_count") or 3)
        except Exception:
            thread_count = 3
        thread_count = max(1, min(10, thread_count))
        deleted_instances = {int(value) for value in data.get("deleted_instances", [])}
        active_instances = [int(value) for value in data.get("active_instances", [])]
        platform_states = data.get("platform_states", {})
        saved_country_types = {
            str(value).strip()
            for value in data.get("country_types", [])
            if str(value or "").strip()
        }
        saved_custom_account_types = {
            str(value).strip()
            for value in data.get("custom_account_types", [])
            if str(value or "").strip()
        }
        if isinstance(platform_states, dict):
            for raw_platform_state in platform_states.values():
                if not isinstance(raw_platform_state, dict):
                    continue
                saved_country_types.update(
                    str(value).strip()
                    for value in raw_platform_state.get("country_types", [])
                    if str(value or "").strip()
                )
                saved_custom_account_types.update(
                    str(value).strip()
                    for value in raw_platform_state.get("custom_account_types", [])
                    if str(value or "").strip()
                )
        self.saved_country_types = ["All"] + sorted(value for value in saved_country_types if value != "All")
        self.saved_custom_account_types = ["All"] + sorted(value for value in saved_custom_account_types if value != "All")
        if not isinstance(platform_states, dict) or not platform_states:
            platform_states = {
                "facebook": {
                    "credentials": credentials,
                    "instance_names": instance_names,
                    "profile_names": profile_names,
                    "preview_updated_at": preview_updated_at,
                    "run_states": run_states,
                    "instance_reports": instance_reports,
                    "backend_profile_ids": backend_profile_ids,
                    "photo_upload_paths": photo_upload_paths,
                    "cover_upload_paths": cover_upload_paths,
                    "photo_upload_descriptions": photo_upload_descriptions,
                    "country_types": self.saved_country_types,
                    "custom_account_types": self.saved_custom_account_types,
                    "deleted_instances": list(deleted_instances),
                    "active_instances": active_instances,
                }
            }
        for platform in PLATFORM_ORDER:
            if platform not in platform_states:
                platform_states[platform] = self._platform_state_from_accounts_file(platform) or self._empty_platform_state()
        return (
            credentials,
            instance_names,
            profile_names,
            preview_updated_at,
            run_states,
            instance_reports,
            backend_profile_ids,
            photo_upload_paths,
            cover_upload_paths,
            photo_upload_descriptions,
            browser_mode,
            platform_mode,
            thread_count,
            deleted_instances,
            active_instances,
            platform_states,
        )

    def initialize_app(self) -> None:
        (
            credentials,
            instance_names,
            profile_names,
            preview_updated_at,
            run_states,
            instance_reports,
            backend_profile_ids,
            photo_upload_paths,
            cover_upload_paths,
            photo_upload_descriptions,
            browser_mode,
            platform_mode,
            thread_count,
            deleted_instances,
            active_instances,
            platform_states,
        ) = self.load_instance_data()
        self.vars.browser_mode_var.set(browser_mode)
        self.vars.platform_var.set(platform_mode)
        self.vars.thread_count_var.set(thread_count)
        self.current_platform = platform_mode
        self.platform_states = {
            platform: self._normalize_platform_state(state)
            for platform, state in platform_states.items()
            if platform in self.PLATFORM_HOME_URLS
        }
        if platform_mode not in self.platform_states:
            self.platform_states[platform_mode] = self._normalize_platform_state(
                {
                    "credentials": credentials,
                    "instance_names": instance_names,
                    "profile_names": profile_names,
                    "preview_updated_at": preview_updated_at,
                    "run_states": run_states,
                    "instance_reports": instance_reports,
                    "backend_profile_ids": backend_profile_ids,
                    "photo_upload_paths": photo_upload_paths,
                    "cover_upload_paths": cover_upload_paths,
                    "photo_upload_descriptions": photo_upload_descriptions,
                    "deleted_instances": list(deleted_instances),
                    "active_instances": active_instances,
                }
            )
        self._remove_copied_non_facebook_states()
        self._load_platform_state(platform_mode)

    def save_credentials_from_entries(self) -> None:
        for instance_number, entry in self.state.credential_entries.items():
            self.state.credentials_dict[instance_number] = entry.get()
        self.save_instance_data()

    def rename_instance(self, instance_number: int) -> None:
        new_name = self.app.simpledialog.askstring(
            "Rename Instance",
            f"Enter a new name for Firefox {instance_number}:",
        )
        if not new_name:
            return

        self.state.instance_names[instance_number] = new_name
        self.state.firefox_buttons[instance_number - 1][0].config(text=new_name)
        self.save_instance_data()
        self.sync_local_profiles_to_backend_async([instance_number])
        self.app.refresh_dashboard()

    def delete_instance(self, instance_number: int, confirm: bool = True) -> None:
        if confirm and not self.app.messagebox.askyesno(
            "Delete Instance",
            f"Are you sure you want to delete Firefox {instance_number}?",
        ):
            return

        instance_folder = self.firefox_profile_dir(instance_number)
        self.state.credentials_dict.pop(instance_number, None)
        self.state.instance_names.pop(instance_number, None)
        self.state.profile_names.pop(instance_number, None)
        self.state.preview_updated_at.pop(instance_number, None)
        self.state.run_states.pop(instance_number, None)
        self.state.instance_reports.pop(instance_number, None)
        self.state.photo_upload_paths.pop(instance_number, None)
        self.state.cover_upload_paths.pop(instance_number, None)
        self.state.photo_upload_descriptions.pop(instance_number, None)
        self.state.deleted_instances.add(instance_number)

        if instance_folder.exists():
            try:
                shutil.rmtree(instance_folder)
            except Exception as exc:
                logging.error("Failed to delete folder %s: %s", instance_folder, exc)

        image_path = IMAGE_DIR / f"image_{instance_number}.png"
        if image_path.exists():
            image_path.unlink()
        legacy_cover_path = IMAGE_DIR / f"cover_{instance_number}.png"
        if legacy_cover_path.exists():
            legacy_cover_path.unlink()
        legacy_avatar_path = IMAGE_DIR / f"avatar_{instance_number}.png"
        if legacy_avatar_path.exists():
            legacy_avatar_path.unlink()
        for screenshot_path in IMAGE_DIR.glob(f"facebook_{instance_number}_*.png"):
            if screenshot_path.exists():
                screenshot_path.unlink()
        account_image_dir = IMAGE_DIR / f"Firefox_{instance_number}"
        if account_image_dir.exists():
            shutil.rmtree(account_image_dir, ignore_errors=True)

        self.app.browser.delete_cookie_file(instance_number)
        backend_profile_id = self.state.backend_profile_ids.pop(instance_number, None)
        if backend_profile_id:
            threading.Thread(
                target=self._delete_backend_profile,
                args=(backend_profile_id,),
                daemon=True,
            ).start()

        button, frame = self.state.firefox_buttons[instance_number - 1]
        if frame:
            frame.destroy()
        self.state.firefox_buttons[instance_number - 1] = (None, None)
        self.state.instance_body_frames.pop(instance_number, None)
        self.state.image_labels.pop(instance_number, None)
        self.state.cover_labels.pop(instance_number, None)
        self.state.avatar_labels.pop(instance_number, None)
        self.state.avatar_name_labels.pop(instance_number, None)
        self.state.instance_media_frames.pop(instance_number, None)
        self.state.instance_text_frames.pop(instance_number, None)
        self.state.instance_title_labels.pop(instance_number, None)
        self.state.instance_hint_labels.pop(instance_number, None)
        self.state.instance_detail_labels.pop(instance_number, None)
        self.state.preview_status_labels.pop(instance_number, None)
        self.state.run_status_labels.pop(instance_number, None)

        self.save_instance_data()
        self.app.refresh_dashboard()

    def delete_multiple_instances(self) -> None:
        start_instance = self.app.simpledialog.askinteger("Delete Multiple Instances", "Enter the start instance number:")
        end_instance = self.app.simpledialog.askinteger("Delete Multiple Instances", "Enter the end instance number:")
        if not start_instance or not end_instance:
            return

        if self.app.messagebox.askyesno(
            "Delete Instances",
            f"Are you sure you want to delete Firefox {start_instance} to {end_instance}?",
        ):
            for i in range(start_instance, end_instance + 1):
                self.delete_instance(i, confirm=False)

    def reset_report_data(self) -> None:
        if not self.app.messagebox.askyesno(
            "Reset Table",
            "Reset all table/report data (Runs, Done, Failed, Status) for all Firefox profiles?",
        ):
            return

        self.state.instance_reports.clear()
        for instance_number in list(self.state.run_status_labels.keys()):
            self.state.run_states[instance_number] = "Idle"
            self.set_run_status(
                instance_number,
                "Idle",
                TEXT_MUTED,
                persist_report=False,
                save_data=False,
                refresh_table=False,
            )

        self.save_instance_data()
        if hasattr(self.app, "refresh_report_table"):
            self.app.refresh_report_table()
        self.app.refresh_dashboard()

    def open_data_folder(self) -> None:
        folder_window = self.app.create_modal("Open Folder", "560x520", modal=False)
        body = self.app.create_modal_card(
            folder_window,
            "Open Platform Function Folder",
            "Choose a platform, then open the folder for that platform function.",
        )

        platform_buttons_frame = self.app.Frame(body, bg=SURFACE_BG)
        platform_buttons_frame.pack(fill="x", pady=(0, 10))
        function_buttons_frame = self.app.Frame(body, bg=SURFACE_BG)
        function_buttons_frame.pack(fill="both", expand=True)

        def folder_name(label: str) -> str:
            clean_label = re.sub(r'[<>:"/\\|?*]+', " ", label).strip()
            clean_label = re.sub(r"\s+", " ", clean_label)
            return clean_label or "Folder"

        def platform_label(platform: str) -> str:
            for label, value in self.app.PLATFORMS:
                if value == platform:
                    return label
            return platform.title()

        def function_folder(platform: str, label: str) -> str:
            folder_path = PLATFORM_FOLDER_DIRS[platform] / folder_name(label)
            folder_path.mkdir(parents=True, exist_ok=True)
            return os.path.realpath(folder_path)

        def ensure_platform_folders(platform: str) -> None:
            PLATFORM_FOLDER_DIRS[platform].mkdir(parents=True, exist_ok=True)
            for action_label, _action_value in self.app.ACTIONS_BY_PLATFORM.get(platform, []):
                function_folder(platform, action_label)

        def open_folder(path: str) -> None:
            os.startfile(path)
            if folder_window.winfo_exists():
                folder_window.destroy()

        def show_platform(platform: str) -> None:
            ensure_platform_folders(platform)
            for child in function_buttons_frame.winfo_children():
                child.destroy()

            label = platform_label(platform)
            self.app.Label(
                function_buttons_frame,
                text=f"{label} folders",
                bg=SURFACE_BG,
                fg=TEXT_PRIMARY,
                font=SECTION_FONT,
            ).pack(anchor="w", pady=(0, 8))

            self.app.create_button(
                function_buttons_frame,
                f"Open {label} Main Folder",
                lambda path=os.path.realpath(PLATFORM_FOLDER_DIRS[platform]): open_folder(path),
                kind="primary",
                compact=True,
                full_width=True,
            ).pack(fill="x", pady=(0, 8))

            for action_label, _action_value in self.app.ACTIONS_BY_PLATFORM.get(platform, []):
                self.app.create_button(
                    function_buttons_frame,
                    action_label,
                    lambda path=function_folder(platform, action_label): open_folder(path),
                    kind="secondary",
                    compact=True,
                    full_width=True,
                ).pack(fill="x", pady=3)

        for label, platform in self.app.PLATFORMS:
            self.app.create_button(
                platform_buttons_frame,
                label,
                lambda platform=platform: show_platform(platform),
                kind="primary" if platform == self.vars.platform_var.get() else "secondary",
                compact=True,
            ).pack(side="left", fill="x", expand=True, padx=(0, 6))

        current_platform = self.vars.platform_var.get()
        if current_platform not in PLATFORM_FOLDER_DIRS:
            current_platform = "facebook"
        show_platform(current_platform)

    def reload_instance_image(self, instance_number: int) -> None:
        self._set_instance_body_visibility(instance_number)
        self._load_saved_media(instance_number)
        self.app.refresh_dashboard()

    def reload_all_media(self) -> None:
        for instance_number in sorted(self.state.instance_body_frames.keys()):
            self._set_instance_body_visibility(instance_number)
            if self.state.show_media_previews:
                self._load_saved_media(instance_number)
        self.app.refresh_dashboard()

    def set_profile_name(self, instance_number: int, profile_name: str) -> None:
        clean_name = profile_name.strip()
        if not clean_name:
            return
        if self.state.profile_names.get(instance_number) == clean_name:
            return
        self.state.profile_names[instance_number] = clean_name
        label = self.state.avatar_name_labels.get(instance_number)
        if label:
            label.config(text=clean_name)
        self.save_instance_data()
        self.sync_local_profiles_to_backend_async([instance_number])

    def set_account_id(self, instance_number: int, account_id: str) -> None:
        clean_id = str(account_id or "").strip()
        if not clean_id:
            return
        report = self._ensure_instance_report(instance_number)
        if str(report.get("account_id", "") or "").strip() == clean_id:
            return
        report["account_id"] = clean_id
        self.save_instance_data()
        self.sync_local_profiles_to_backend_async([instance_number])
        if hasattr(self.app, "refresh_report_table_async"):
            self.app.refresh_report_table_async()

    def set_profile_identity(
        self,
        instance_number: int,
        date_birth: str = "",
        gender: str = "",
        gmail: str = "",
        save_data: bool = True,
        refresh_table: bool = True,
    ) -> None:
        report = self._ensure_instance_report(instance_number)
        updates = {
            "date_birth": str(date_birth or "").strip(),
            "gender": self._normalize_gender(gender) if gender else "",
            "gmail": str(gmail or "").strip(),
        }
        changed = False
        for key, value in updates.items():
            if value and report.get(key) != value:
                report[key] = value
                changed = True
        if not changed:
            return
        if save_data:
            self.save_instance_data()
            self.sync_local_profiles_to_backend_async([instance_number])
        if refresh_table and hasattr(self.app, "refresh_report_table_async"):
            self.app.refresh_report_table_async()

    def set_network_identity(
        self,
        instance_number: int,
        ip_address: str = "",
        country: str = "",
        proxy: str = "",
        save_data: bool = True,
        refresh_table: bool = True,
    ) -> None:
        report = self._ensure_instance_report(instance_number)
        updates = {
            "ip": str(ip_address or "").strip(),
            "country": str(country or "").strip(),
            "proxy": str(proxy or "").strip(),
        }
        changed = False
        for key, value in updates.items():
            if value and report.get(key) != value:
                report[key] = value
                changed = True
        if not changed:
            return
        if save_data:
            self.save_instance_data()
            self.sync_local_profiles_to_backend_async([instance_number])
        if refresh_table and hasattr(self.app, "refresh_report_table_async"):
            self.app.refresh_report_table_async()

    def set_account_type(
        self,
        instance_number: int,
        account_type: str,
        save_data: bool = True,
        refresh_table: bool = True,
    ) -> None:
        clean_type = str(account_type or "").strip()
        if not clean_type or clean_type.lower() in {"all", "store"}:
            return
        report = self._ensure_instance_report(instance_number)
        expected_country = self._expected_country_from_account_type(clean_type)
        if (
            str(report.get("account_type", "") or "").strip() == clean_type
            and str(report.get("expected_country", "") or "").strip() == expected_country
        ):
            return
        report["account_type"] = clean_type
        report["expected_country"] = expected_country
        report["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if save_data:
            self.save_instance_data()
            self.sync_local_profiles_to_backend_async([instance_number])
        if refresh_table and hasattr(self.app, "refresh_report_table_async"):
            self.app.refresh_report_table_async()

    def set_custom_account_type(
        self,
        instance_number: int,
        account_type: str,
        save_data: bool = True,
        refresh_table: bool = True,
    ) -> None:
        clean_type = str(account_type or "").strip()
        if not clean_type or clean_type.lower() in {"all", "store"}:
            return
        report = self._ensure_instance_report(instance_number)
        if str(report.get("custom_account_type", "") or "").strip() == clean_type:
            return
        report["custom_account_type"] = clean_type
        report["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if save_data:
            self.save_instance_data()
            self.sync_local_profiles_to_backend_async([instance_number])
        if refresh_table and hasattr(self.app, "refresh_report_table_async"):
            self.app.refresh_report_table_async()

    def set_account_health(
        self,
        instance_number: int,
        status: str,
        reason: str = "",
        save_data: bool = True,
        refresh_table: bool = True,
    ) -> None:
        clean_status = str(status or "").strip() or "Unknown"
        clean_reason = str(reason or "").strip()
        report = self._ensure_instance_report(instance_number)
        report["account_status"] = clean_status
        report["account_reason"] = clean_reason
        report["account_checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if clean_reason:
            report["last_note"] = clean_reason
        if clean_status in {
            "Live",
            "Token Valid",
            "Token Expired",
            "Need Reconnect",
            "Checkpoint",
            "Disabled",
            "Login required",
            "Review",
            "Check error",
            "Launch failed",
        }:
            report["last_status"] = clean_status
        if save_data:
            self.save_instance_data()
            self.sync_local_profiles_to_backend_async([instance_number])
        if refresh_table and hasattr(self.app, "refresh_report_table_async"):
            self.app.refresh_report_table_async()

    def set_preview_status(self, instance_number: int, status: str, color: str = TEXT_MUTED) -> None:
        label = self.state.preview_status_labels.get(instance_number)
        if label:
            label.config(text=status, fg=color)

    def set_run_status(
        self,
        instance_number: int,
        status: str,
        color: str = TEXT_MUTED,
        persist_report: bool = True,
        save_data: bool = True,
        refresh_table: bool = True,
    ) -> None:
        self.state.run_states[instance_number] = status
        if persist_report:
            self._update_instance_report(instance_number, status=status)
        label = self.state.run_status_labels.get(instance_number)
        if not label:
            if save_data:
                self.save_instance_data()
            if refresh_table and hasattr(self.app, "refresh_report_table_async"):
                self.app.refresh_report_table_async()
            return
        try:
            self.app.root.after(
                0,
                lambda: label.config(
                    text=status,
                    fg=color,
                    highlightbackground=color if color != TEXT_MUTED else BORDER,
                ),
            )
        except Exception:
            label.config(
                text=status,
                fg=color,
                highlightbackground=color if color != TEXT_MUTED else BORDER,
            )
        if save_data:
            self.save_instance_data()
            self.sync_local_profiles_to_backend_async([instance_number])
        if refresh_table and hasattr(self.app, "refresh_report_table_async"):
            self.app.refresh_report_table_async()

    def set_preview_timestamp(self, instance_number: int, timestamp: str | None = None) -> None:
        value = timestamp or datetime.now().isoformat(timespec="seconds")
        self.state.preview_updated_at[instance_number] = value
        self.save_instance_data()
        self._apply_saved_status(instance_number)

    def _format_preview_timestamp(self, timestamp: str) -> str:
        try:
            parsed = datetime.fromisoformat(timestamp)
            return parsed.strftime("Updated %I:%M %p").lstrip("0")
        except ValueError:
            return "Updated"

    def _preview_timestamp_color(self, timestamp: str) -> str:
        try:
            parsed = datetime.fromisoformat(timestamp)
            age_seconds = (datetime.now() - parsed).total_seconds()
            if age_seconds <= 900:
                return SUCCESS
            if age_seconds <= 3600:
                return WARNING
            return DANGER
        except ValueError:
            return TEXT_MUTED

    def _apply_saved_status(self, instance_number: int) -> None:
        status_label = self.state.preview_status_labels.get(instance_number)
        if not status_label:
            return

        timestamp = self.state.preview_updated_at.get(instance_number)
        if timestamp:
            status_label.config(
                text=self._format_preview_timestamp(timestamp),
                fg=self._preview_timestamp_color(timestamp),
            )
        else:
            status_label.config(text="Ready", fg=TEXT_MUTED)

    def _apply_saved_run_status(self, instance_number: int) -> None:
        saved_report = self.state.instance_reports.get(instance_number, {})
        text = str(self.state.run_states.get(instance_number) or saved_report.get("last_status") or "Idle")
        color = TEXT_MUTED
        normalized = text.lower()
        if (
            "fail" in normalized
            or "error" in normalized
            or "die" in normalized
            or "dead" in normalized
            or "checkpoint" in normalized
            or "disabled" in normalized
            or "suspended" in normalized
            or "login required" in normalized
        ):
            color = DANGER
        elif "run" in normalized or "launch" in normalized or "done" in normalized or "live" in normalized or "ready" in normalized:
            color = SUCCESS
        elif "queue" in normalized or "wait" in normalized or "process" in normalized:
            color = WARNING
        self.set_run_status(instance_number, text, color, persist_report=False, save_data=False, refresh_table=False)

    def get_report_rows(self) -> list[dict[str, str]]:
        self._ensure_local_indexes()
        instance_ids = {
            *self.state.instance_names.keys(),
            *self.state.profile_names.keys(),
            *self.state.run_states.keys(),
            *self.state.instance_reports.keys(),
            *{
                i + 1
                for i, (_button, frame) in enumerate(self.state.firefox_buttons)
                if frame is not None
            },
        }
        rows: list[dict[str, str]] = []
        for instance_number in sorted(instance_ids):
            if instance_number in self.state.deleted_instances:
                continue
            report = self._ensure_instance_report(instance_number)
            account_status = self.report_account_status(report)
            account_reason = self.report_account_reason(report, account_status)
            gmail_value = str(report.get("gmail", "") or "").strip()
            if not gmail_value and str(account_status or "").strip().lower() == "live":
                gmail_value = "No Gmail"
            rows.append(
                {
                    "instance_id": str(instance_number),
                    "instance": self._display_firefox_label(instance_number, report),
                    "local_account": self._local_account_label(instance_number, report),
                    "country_type": str(report.get("account_type") or report.get("country") or "-"),
                    "account_type": str(report.get("custom_account_type") or "-"),
                    "expected_country": str(report.get("expected_country") or self.expected_country_for_instance(instance_number) or "-"),
                    "facebook_session": str(report.get("facebook_session") or self.state.instance_names.get(instance_number, "") or "-"),
                    "tiktok_session": str(report.get("tiktok_session") or self.state.instance_names.get(instance_number, "") or "-"),
                    "youtube_session": str(report.get("youtube_session") or self.state.instance_names.get(instance_number, "") or "-"),
                    "instagram_session": str(report.get("instagram_session") or self.state.instance_names.get(instance_number, "") or "-"),
                    "profile": self.state.profile_names.get(
                        instance_number,
                        self.state.instance_names.get(instance_number, "No account name"),
                    ),
                    "account_id": str(report.get("account_id", "") or "-"),
                    "tiktok_username": str(report.get("tiktok_username") or "-"),
                    "tiktok_user_id": str(report.get("tiktok_user_id") or "-"),
                    "gmail_login": str(report.get("gmail_login") or ("Saved" if gmail_value else "-")),
                    "youtube_channel_name": str(report.get("youtube_channel_name") or "-"),
                    "channel_id": str(report.get("channel_id") or "-"),
                    "channel_url": str(report.get("channel_url") or "-"),
                    "brand_channel": str(report.get("brand_channel") or "-"),
                    "instagram_username": str(report.get("instagram_username") or "-"),
                    "instagram_user_id": str(report.get("instagram_user_id") or "-"),
                    "website_name": str(report.get("website_name") or "-"),
                    "wordpress_site_url": str(report.get("wordpress_site_url") or report.get("site_url") or "-"),
                    "wordpress_username": str(report.get("wordpress_username") or "-"),
                    "author_name": str(report.get("author_name") or "-"),
                    "posting_type": str(report.get("posting_type") or "-"),
                    "default_category": str(report.get("default_category") or "-"),
                    "api_login_status": str(report.get("api_login_status") or account_status or "-"),
                    "ip": str(report.get("ip", "") or "-"),
                    "country": str(report.get("country", "") or "-"),
                    "proxy": str(report.get("proxy", "") or "-"),
                    "date_birth": str(report.get("date_birth", "") or "-"),
                    "gender": str(report.get("gender", "") or "-"),
                    "gmail": gmail_value or "-",
                    "action": str(report.get("last_action", "None")),
                    "status": account_status,
                    "reason": account_reason,
                    "checked": str(report.get("account_checked_at") or "-"),
                    "time": str(report.get("last_updated") or report.get("account_checked_at") or "-"),
                    "note": str(report.get("last_note") or report.get("account_reason") or "-"),
                    "runs": str(report.get("run_count", 0)),
                    "done": str(report.get("success_count", 0)),
                    "failed": str(report.get("fail_count", 0)),
                    "updated": str(report.get("last_updated", "-")),
                }
        )
        rows.sort(key=self._report_row_sort_key)
        return rows

    def _report_row_sort_key(self, row: dict[str, str]) -> tuple[str, int, int]:
        account_type = str(row.get("country_type") or row.get("account_type") or "").strip().lower()
        try:
            local_index = int(str(row.get("local_account") or "").strip().rsplit(" ", 1)[1])
        except Exception:
            try:
                local_index = int(str(row.get("instance") or "").strip().rsplit(" ", 1)[1])
            except Exception:
                local_index = 0
        try:
            instance_id = int(str(row.get("instance_id") or 0))
        except Exception:
            instance_id = 0
        return account_type, local_index, instance_id

    def _local_account_label(self, instance_number: int, report: dict) -> str:
        account_type = str(report.get("account_type") or report.get("country") or "").strip()
        local_index = str(report.get("local_index") or "").strip()
        if account_type and local_index:
            return f"{account_type} {local_index}"
        if account_type:
            return account_type
        return f"Account {instance_number}"

    def _display_firefox_label(self, instance_number: int, report: dict) -> str:
        try:
            local_index = int(report.get("local_index") or 0)
        except Exception:
            local_index = 0
        if local_index > 0 and str(report.get("account_type") or report.get("country") or "").strip():
            return f"Firefox {local_index}"
        return f"Firefox {instance_number}"

    def _action_label(self, action_key: str) -> str:
        labels = {
            "login": "Login",
            "care": "Care",
            "clear_data": "Clear Data",
            "join_group": "Join Group",
            "upload_reel": "Upload Reel",
            "share_to_groups": "Share To Groups",
            "get_id": "Get ID",
            "get_gmail": "Change Gmail",
            "get_date": "Date Create FB",
            "upload_photo_cover": "Upload Photo+Cover",
            "open_home": "Open Home",
            "upload_video": "Upload Video",
            "open_profile": "Profile",
            "open_inbox": "Inbox",
            "open_analytics": "Analytics",
            "open_studio": "YouTube Studio",
            "open_shorts": "Shorts",
            "create_post": "Create Post",
            "open_reels": "Reels",
            "open_messages": "Messages",
            "check_login": "Check Login",
            "check_gmail": "Check Gmail Login",
            "check_channel": "Check YouTube Channel",
            "open_admin": "WordPress Admin",
            "check_api": "Check API Login",
            "post_article": "Post Article",
        }
        return labels.get(action_key, action_key.replace("_", " ").title())

    def _ensure_instance_report(self, instance_number: int) -> dict:
        report = self.state.instance_reports.get(instance_number)
        if not isinstance(report, dict):
            report = {}
        report.setdefault("last_action", "None")
        report.setdefault("platform", self.vars.platform_var.get())
        report.setdefault("last_status", self.state.run_states.get(instance_number, "Idle"))
        report.setdefault("last_note", "")
        report.setdefault("account_status", "")
        report.setdefault("account_reason", "")
        report.setdefault("account_checked_at", "")
        report.setdefault("account_id", "")
        report.setdefault("account_type", "")
        report.setdefault("custom_account_type", "")
        report.setdefault("local_index", "")
        report.setdefault("expected_country", "")
        report.setdefault("ip", "")
        report.setdefault("country", "")
        report.setdefault("proxy", "")
        report.setdefault("date_birth", "")
        report.setdefault("gender", "")
        report.setdefault("gmail", "")
        report.setdefault("facebook_session", "")
        report.setdefault("tiktok_session", "")
        report.setdefault("tiktok_username", "")
        report.setdefault("tiktok_user_id", "")
        report.setdefault("youtube_session", "")
        report.setdefault("gmail_login", "")
        report.setdefault("youtube_channel_name", "")
        report.setdefault("channel_id", "")
        report.setdefault("channel_url", "")
        report.setdefault("brand_channel", "")
        report.setdefault("instagram_session", "")
        report.setdefault("instagram_username", "")
        report.setdefault("instagram_user_id", "")
        report.setdefault("website_name", "")
        report.setdefault("wordpress_site_url", "")
        report.setdefault("wordpress_username", "")
        report.setdefault("author_name", "")
        report.setdefault("posting_type", "")
        report.setdefault("default_category", "")
        report.setdefault("api_login_status", "")
        report.setdefault("last_updated", "-")
        report.setdefault("run_count", 0)
        report.setdefault("success_count", 0)
        report.setdefault("fail_count", 0)
        report.setdefault("_result_pending", False)
        report.setdefault("_last_counted_signature", "")
        if not str(report.get("expected_country") or "").strip():
            account_type = str(report.get("account_type") or "").strip()
            if account_type:
                report["expected_country"] = self._expected_country_from_account_type(account_type)
        self.state.instance_reports[instance_number] = report
        return report

    def report_account_status(self, report: dict) -> str:
        status = str(report.get("account_status") or "").strip()
        if status and status.lower() != "unknown":
            if status.lower() == "live" and self._is_weak_live_report(report):
                return "Unknown"
            return status

        legacy_status = str(report.get("last_status") or "").strip()
        normalized = legacy_status.lower()
        if normalized in {"live", "checkpoint", "disabled", "login required", "review", "check error"}:
            if normalized == "live" and self._is_weak_live_report(report):
                return "Unknown"
            return legacy_status
        if any(marker in normalized for marker in ("checkpoint", "disabled", "suspended", "login required")):
            return legacy_status
        return "Unknown"

    def report_account_reason(self, report: dict, status: str | None = None) -> str:
        reason = str(report.get("account_reason") or "").strip()
        effective_status = status or self.report_account_status(report)
        if reason and not (effective_status == "Unknown" and self._is_weak_live_report(report)):
            return reason
        note = str(report.get("last_note") or "").strip()
        if note and not (effective_status == "Unknown" and self._is_weak_live_text(note)):
            return note
        if effective_status == "Unknown":
            if str(report.get("account_id") or "").strip():
                return "Saved identity only; run Check Login for token/API state."
            return "Run Check Login for token/API state."
        return "-"

    def _is_weak_live_report(self, report: dict) -> bool:
        reason = str(report.get("account_reason") or report.get("last_note") or "").strip().lower()
        if self._is_weak_live_text(reason):
            return True
        if not str(report.get("account_checked_at") or "").strip():
            return True
        return False

    def _is_weak_live_text(self, text: str) -> bool:
        reason = str(text or "").strip().lower()
        weak_markers = (
            "account id saved",
            "login detected in browser session",
            "identity was read",
        )
        return any(marker in reason for marker in weak_markers)

    def _hydrate_reports_from_cookie_files(self) -> None:
        return

    def _update_instance_report(
        self,
        instance_number: int,
        action: str | None = None,
        status: str | None = None,
        increment_run: bool = False,
        note: str | None = None,
    ) -> None:
        report = self._ensure_instance_report(instance_number)
        if action:
            report["last_action"] = action
        if status:
            report["last_status"] = status
        if note is not None:
            report["last_note"] = note
        if increment_run:
            report["run_count"] = int(report.get("run_count", 0)) + 1
            report["_result_pending"] = True
            report["_last_counted_signature"] = ""

        status_value = str(status or report.get("last_status", "")).strip().lower()
        signature = f"{report.get('last_action', '')}|{status_value}"
        success_markers = {"done", "success", "cache cleared"}
        fail_markers = {
            "failed",
            "launch failed",
            "login prepare failed",
            "credential format error",
            "unknown action",
            "not running",
            "ip mismatch",
            "checkpoint",
            "disabled",
            "suspended",
            "login required",
            "check error",
        }
        if report.get("_result_pending", False):
            if status_value in success_markers and signature != report.get("_last_counted_signature", ""):
                report["success_count"] = int(report.get("success_count", 0)) + 1
                report["_last_counted_signature"] = signature
                report["_result_pending"] = False
            elif status_value in fail_markers and signature != report.get("_last_counted_signature", ""):
                report["fail_count"] = int(report.get("fail_count", 0)) + 1
                report["_last_counted_signature"] = signature
                report["_result_pending"] = False

        report["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _load_saved_media(self, instance_number: int) -> None:
        cover_path = self._cover_image_path(instance_number)
        avatar_path = self._avatar_image_path(instance_number)
        cover_label = self.state.cover_labels.get(instance_number)
        avatar_label = self.state.avatar_labels.get(instance_number)
        avatar_name_label = self.state.avatar_name_labels.get(instance_number)
        status_label = self.state.preview_status_labels.get(instance_number)
        show_media = self.state.show_media_previews

        if cover_label:
            if not show_media:
                cover_label.config(image="", text="Cover hidden")
                cover_label.image = None
            elif cover_path.exists():
                cover_tk = self._build_preview_photo(cover_path, (300, 112), crop=True)
                cover_label.config(image=cover_tk, text="")
                cover_label.image = cover_tk
            else:
                cover_label.config(image="", text="No cover")
                cover_label.image = None

        if avatar_label:
            if not show_media:
                avatar_label.config(image="", text="Avatar hidden")
                avatar_label.image = None
            elif avatar_path.exists():
                avatar_tk = self._build_preview_photo(avatar_path, (72, 72), crop=True)
                avatar_label.config(image=avatar_tk, text="")
                avatar_label.image = avatar_tk
            else:
                avatar_label.config(image="", text="No avatar")
                avatar_label.image = None

        if avatar_name_label:
            avatar_name_label.config(text=self.state.profile_names.get(instance_number, "No account name"))

        if status_label:
            self._apply_saved_status(instance_number)

    def _facebook_screenshot_path(self, instance_number: int):
        account_dir = IMAGE_DIR / f"Firefox_{instance_number}"
        matches = sorted(account_dir.glob("facebook_*.png")) if account_dir.exists() else []
        if not matches:
            legacy_matches = sorted(IMAGE_DIR.glob(f"facebook_{instance_number}_*.png"))
            if not legacy_matches:
                return None
            return legacy_matches[-1]
        return matches[-1]

    def _avatar_image_path(self, instance_number: int):
        account_path = avatar_image_path(instance_number)
        if account_path.exists():
            return account_path
        legacy_path = IMAGE_DIR / f"avatar_{instance_number}.png"
        return legacy_path

    def _cover_image_path(self, instance_number: int):
        account_path = cover_image_path(instance_number)
        if account_path.exists():
            return account_path
        legacy_path = IMAGE_DIR / f"cover_{instance_number}.png"
        return legacy_path

    def _build_preview_photo(self, image_path, size: tuple[int, int], crop: bool = False):
        with Image.open(image_path) as image:
            source = image.convert("RGB")
            method = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
            if crop:
                prepared = ImageOps.fit(source, size, method=method, centering=(0.5, 0.5))
            else:
                prepared = ImageOps.contain(source, size, method=method)
        return ImageTk.PhotoImage(prepared)

    def _set_instance_body_visibility(self, instance_number: int) -> None:
        body = self.state.instance_body_frames.get(instance_number)
        if not body:
            return

        if self.state.show_media_previews:
            if not body.winfo_manager():
                body.pack(fill="x", padx=12, pady=(8, 10))
            return

        if body.winfo_manager():
            body.pack_forget()

    def sync_local_profiles_to_backend_async(self, instance_numbers: list[int] | None = None) -> None:
        threading.Thread(
            target=self._sync_local_profiles_to_backend,
            args=(instance_numbers,),
            daemon=True,
        ).start()

    def _sync_local_profiles_to_backend(self, instance_numbers: list[int] | None = None) -> None:
        try:
            remote_profiles = self._backend_request_json("/api/profiles")
        except Exception:
            return

        profiles_by_id = {str(profile.get("id")): profile for profile in remote_profiles if profile.get("id")}
        profiles_by_instance: dict[int, dict] = {}
        for profile in remote_profiles:
            metadata = profile.get("metadata") or {}
            instance_number = metadata.get("instance_number")
            if isinstance(instance_number, int):
                profiles_by_instance[instance_number] = profile
                self._merge_backend_metadata_into_report(instance_number, profile)

        if instance_numbers is None:
            local_ids = {
                *self.state.instance_names.keys(),
                *self.state.profile_names.keys(),
                *self.state.run_states.keys(),
                *self.state.instance_reports.keys(),
            }
            target_instances = sorted(
                instance_number
                for instance_number in local_ids
                if instance_number not in self.state.deleted_instances
            )
        else:
            target_instances = sorted(
                instance_number
                for instance_number in instance_numbers
                if instance_number not in self.state.deleted_instances
            )

        changed = False
        for instance_number in target_instances:
            report = self._ensure_instance_report(instance_number)
            metadata = {
                "instance_number": instance_number,
                "account_id": str(report.get("account_id", "") or ""),
                "account_type": str(report.get("account_type", "") or ""),
                "custom_account_type": str(report.get("custom_account_type", "") or ""),
                "expected_country": str(report.get("expected_country", "") or ""),
                "ip": str(report.get("ip", "") or ""),
                "country": str(report.get("country", "") or ""),
                "proxy": str(report.get("proxy", "") or ""),
                "date_birth": str(report.get("date_birth", "") or ""),
                "gender": str(report.get("gender", "") or ""),
                "gmail": str(report.get("gmail", "") or ""),
                "account_status": self.report_account_status(report),
                "account_reason": str(report.get("account_reason", "") or ""),
                "account_checked_at": str(report.get("account_checked_at", "") or ""),
            }
            profile_name = self.state.profile_names.get(
                instance_number,
                self.state.instance_names.get(instance_number, f"Firefox {instance_number}"),
            )
            session_label = self.state.instance_names.get(instance_number, f"Firefox {instance_number}")
            last_status = self.report_account_status(report)

            existing_id = self.state.backend_profile_ids.get(instance_number)
            remote_profile = profiles_by_id.get(existing_id) if existing_id else None
            if remote_profile is None:
                remote_profile = profiles_by_instance.get(instance_number)
                if remote_profile and remote_profile.get("id"):
                    self.state.backend_profile_ids[instance_number] = str(remote_profile["id"])
                    changed = True

            payload = {
                "profile_name": profile_name,
                "session_label": session_label,
                "metadata": metadata,
                "last_status": last_status,
            }

            if remote_profile and remote_profile.get("id"):
                self._backend_request_json(
                    f"/api/profiles/{remote_profile['id']}",
                    method="PUT",
                    payload=payload,
                )
                continue

            created = self._backend_request_json(
                "/api/profiles",
                method="POST",
                payload={
                    "profile_name": profile_name,
                    "session_label": session_label,
                    "metadata": metadata,
                },
            )
            created_id = str(created.get("id") or "")
            if created_id:
                self.state.backend_profile_ids[instance_number] = created_id
                changed = True
                self._backend_request_json(
                    f"/api/profiles/{created_id}",
                    method="PUT",
                    payload={"last_status": last_status},
                )

        if changed:
            self.save_instance_data()

    def _merge_backend_metadata_into_report(self, instance_number: int, profile: dict) -> bool:
        if instance_number in self.state.deleted_instances:
            return False
        metadata = profile.get("metadata") or {}
        report = self._ensure_instance_report(instance_number)
        changed = False
        for report_key in (
            "account_id",
            "account_type",
            "custom_account_type",
            "expected_country",
            "ip",
            "country",
            "proxy",
            "date_birth",
            "gender",
            "gmail",
            "account_status",
            "account_reason",
            "account_checked_at",
        ):
            existing_value = str(report.get(report_key, "") or "").strip()
            backend_value = str(metadata.get(report_key, "") or "").strip()
            if not existing_value and backend_value:
                report[report_key] = backend_value
                changed = True

        profile_name = str(profile.get("profile_name") or "").strip()
        if (
            profile_name
            and profile_name != f"Firefox {instance_number}"
            and not self.state.profile_names.get(instance_number)
        ):
            self.state.profile_names[instance_number] = profile_name
            changed = True

        if changed:
            self.save_instance_data()
            if hasattr(self.app, "refresh_report_table_async"):
                self.app.refresh_report_table_async()
        return changed

    def _backend_request_json(self, path: str, method: str = "GET", payload: dict | None = None):
        base_url = os.environ.get("FBV1_BACKEND_URL", "http://127.0.0.1:8010").strip().rstrip("/")
        if not base_url:
            raise RuntimeError("Backend URL is empty.")
        request_data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            request_data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            f"{base_url}{path}",
            data=request_data,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="ignore")
            raise RuntimeError(detail or str(error)) from error

        return json.loads(body) if body else {}

    def _delete_backend_profile(self, profile_id: str) -> None:
        try:
            self._backend_request_json(f"/api/profiles/{profile_id}", method="DELETE")
        except Exception:
            pass
