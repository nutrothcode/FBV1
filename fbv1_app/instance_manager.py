from __future__ import annotations

import csv
from datetime import datetime
import json
import logging
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

from PIL import Image, ImageOps, ImageTk

from .config import (
    APP_DB_PATH,
    BACKUP_DIR,
    COOKIE_DIR,
    DATA_FILE,
    FIREFOX_USER_DATA_DIR,
    IMAGE_DIR,
    avatar_image_path,
    cover_image_path,
)
from .storage import AccountStateStore
from .theme import ACCENT, BORDER, DANGER, SECTION_FONT, SMALL_FONT, SUCCESS, SURFACE_ALT, SURFACE_BG, TEXT_MUTED, TEXT_PRIMARY, WARNING

if TYPE_CHECKING:
    from .ui import FacebookToolApp


class InstanceManager:
    PLATFORM_HOME_URLS = {
        "facebook": "https://www.facebook.com",
        "tiktok": "https://www.tiktok.com",
        "youtube": "https://www.youtube.com",
        "instagram": "https://www.instagram.com",
    }
    PLATFORM_ACTION_URLS = {
        "tiktok": {
            "open_home": "https://www.tiktok.com",
            "publish_tool": "https://www.tiktok.com/upload",
            "upload_video": "https://www.tiktok.com/upload",
            "open_profile": "https://www.tiktok.com/profile",
            "open_inbox": "https://www.tiktok.com/messages",
            "open_analytics": "https://www.tiktok.com/analytics",
        },
        "youtube": {
            "open_home": "https://www.youtube.com",
            "publish_tool": "https://studio.youtube.com/channel/UC/videos/upload",
            "open_studio": "https://studio.youtube.com",
            "upload_video": "https://studio.youtube.com/channel/UC/videos/upload",
            "open_shorts": "https://www.youtube.com/shorts",
            "open_analytics": "https://studio.youtube.com/analytics",
        },
        "instagram": {
            "open_home": "https://www.instagram.com",
            "publish_tool": "https://www.instagram.com",
            "create_post": "https://www.instagram.com",
            "open_reels": "https://www.instagram.com/reels",
            "open_profile": "https://www.instagram.com/accounts/edit/",
            "open_messages": "https://www.instagram.com/direct/inbox/",
        },
    }

    def __init__(self, app: "FacebookToolApp") -> None:
        self.app = app
        self.storage = AccountStateStore(APP_DB_PATH, BACKUP_DIR)

    @property
    def state(self):
        return self.app.state

    @property
    def vars(self):
        return self.app.vars

    def open_firefox_instances(
        self,
        instance_count: int,
        start_index: int = 1,
        padding: int = 5,
    ) -> None:
        for i in range(start_index, start_index + instance_count):
            if i in self.state.deleted_instances:
                continue

            instance_folder = FIREFOX_USER_DATA_DIR / f"Firefox_{i}"
            instance_folder.mkdir(parents=True, exist_ok=True)

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
        action = self.vars.action_var.get()
        action_label = self._action_label(action)
        self._update_instance_report(instance_number, action=action_label, status="Queued", increment_run=True)
        self.set_run_status(instance_number, "Queued", WARNING)
        try:
            platform = self.vars.platform_var.get()
            if platform != "facebook":
                action_urls = self.PLATFORM_ACTION_URLS.get(platform, {})
                target_url = action_urls.get(action, self.PLATFORM_HOME_URLS.get(platform, "https://www.google.com"))
                self.app.browser.open_firefox_instance(
                    instance_number,
                    login=False,
                    start_url=target_url,
                    sync_preview=False,
                )
                if action in {"publish_tool", "upload_video", "create_post"}:
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

            if action == "login":
                self.app.browser.open_firefox_instance(instance_number)
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
                self.app.browser.open_firefox_instance(instance_number, login=False)
                self.app.browser.get_gmail(instance_number)
                self.set_run_status(instance_number, "Done", SUCCESS)
            elif action == "get_date":
                self.app.browser.open_firefox_instance(instance_number, login=False)
                self.app.browser.get_date(instance_number)
                self.set_run_status(instance_number, "Done", SUCCESS)
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

    def start_all_instances(self) -> None:
        if self.state.batch_running:
            return
        instance_numbers = self.active_instance_numbers()
        if not instance_numbers:
            self.app.messagebox.showwarning("Start All", "No active Firefox profiles found.")
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

        for i in range(start_index, end_index + 1):
            self.state.deleted_instances.discard(i)

        self.open_firefox_instances(end_index - start_index + 1, start_index=start_index)
        self.save_instance_data()
        self.sync_local_profiles_to_backend_async(list(range(start_index, end_index + 1)))
        self.app.refresh_dashboard()

    def save_instance_data(self) -> None:
        data = {
            "credentials": self.state.credentials_dict,
            "instance_names": self.state.instance_names,
            "profile_names": self.state.profile_names,
            "preview_updated_at": self.state.preview_updated_at,
            "run_states": self.state.run_states,
            "instance_reports": self.state.instance_reports,
            "backend_profile_ids": self.state.backend_profile_ids,
            "photo_upload_paths": self.state.photo_upload_paths,
            "cover_upload_paths": self.state.cover_upload_paths,
            "photo_upload_descriptions": self.state.photo_upload_descriptions,
            "browser_mode": self.vars.browser_mode_var.get(),
            "platform_mode": self.vars.platform_var.get(),
            "thread_count": int(self.vars.thread_count_var.get() or 3),
            "deleted_instances": list(self.state.deleted_instances),
            "active_instances": [
                i + 1 for i, (_button, frame) in enumerate(self.state.firefox_buttons) if frame is not None
            ],
        }
        self.storage.save_state(data)
        with DATA_FILE.open("w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def backup_instance_data(self) -> None:
        data = {
            "credentials": self.state.credentials_dict,
            "instance_names": self.state.instance_names,
            "profile_names": self.state.profile_names,
            "preview_updated_at": self.state.preview_updated_at,
            "run_states": self.state.run_states,
            "instance_reports": self.state.instance_reports,
            "backend_profile_ids": self.state.backend_profile_ids,
            "photo_upload_paths": self.state.photo_upload_paths,
            "cover_upload_paths": self.state.cover_upload_paths,
            "photo_upload_descriptions": self.state.photo_upload_descriptions,
            "browser_mode": self.vars.browser_mode_var.get(),
            "platform_mode": self.vars.platform_var.get(),
            "thread_count": int(self.vars.thread_count_var.get() or 3),
            "deleted_instances": list(self.state.deleted_instances),
            "active_instances": [
                i + 1 for i, (_button, frame) in enumerate(self.state.firefox_buttons) if frame is not None
            ],
        }
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
            account_id = clean_row.get("uid") or clean_row.get("account_id") or clean_row.get("id")
            profile_name = clean_row.get("name") or clean_row.get("account_name") or clean_row.get("profile")
            gmail = clean_row.get("gmail") or clean_row.get("email")
            status = clean_row.get("status") or "Idle"
            platform = clean_row.get("platform") or self.vars.platform_var.get()
            if platform and platform in self.PLATFORM_HOME_URLS:
                self.vars.platform_var.set(platform)

            while next_instance in self.state.deleted_instances:
                next_instance += 1

            self.open_firefox_instances(1, start_index=next_instance)
            self.state.instance_names[next_instance] = f"Firefox {next_instance}"
            if profile_name:
                self.state.profile_names[next_instance] = profile_name
            report = self._ensure_instance_report(next_instance)
            if account_id:
                report["account_id"] = account_id
            if gmail:
                report["gmail"] = gmail
            report["last_action"] = "Imported"
            report["last_status"] = status
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
        fieldnames = [
            "instance",
            "profile",
            "account_id",
            "date_birth",
            "gender",
            "gmail",
            "action",
            "status",
            "runs",
            "done",
            "failed",
            "updated",
        ]
        with open(output_path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
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
    ]:
        data = self.storage.load_state()
        if data is None:
            if not DATA_FILE.exists():
                return {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, "pc", "facebook", 3, set(), []
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
        ) = self.load_instance_data()
        self.state.credentials_dict = credentials
        self.state.instance_names = instance_names
        self.state.profile_names = profile_names
        self.state.preview_updated_at = preview_updated_at
        self.state.run_states = run_states
        self.state.instance_reports = instance_reports
        self.state.backend_profile_ids = backend_profile_ids
        self.state.photo_upload_paths = photo_upload_paths
        self.state.cover_upload_paths = cover_upload_paths
        self.state.photo_upload_descriptions = photo_upload_descriptions
        self.vars.browser_mode_var.set(browser_mode)
        self.vars.platform_var.set(platform_mode)
        self.vars.thread_count_var.set(thread_count)
        self.state.deleted_instances = deleted_instances
        self._hydrate_reports_from_cookie_files()
        for i in active_instances:
            self.open_firefox_instances(1, start_index=i)
        self.sync_local_profiles_to_backend_async()

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

        instance_folder = FIREFOX_USER_DATA_DIR / f"Firefox_{instance_number}"
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
        os.startfile(os.path.realpath(FIREFOX_USER_DATA_DIR))

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
    ) -> None:
        report = self._ensure_instance_report(instance_number)
        updates = {
            "date_birth": str(date_birth or "").strip(),
            "gender": str(gender or "").strip(),
            "gmail": str(gmail or "").strip(),
        }
        changed = False
        for key, value in updates.items():
            if value and report.get(key) != value:
                report[key] = value
                changed = True
        if not changed:
            return
        self.save_instance_data()
        self.sync_local_profiles_to_backend_async([instance_number])
        if hasattr(self.app, "refresh_report_table_async"):
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
        if "fail" in normalized or "error" in normalized or "die" in normalized or "dead" in normalized:
            color = DANGER
        elif "run" in normalized or "launch" in normalized or "done" in normalized or "live" in normalized or "ready" in normalized:
            color = SUCCESS
        elif "queue" in normalized or "wait" in normalized or "process" in normalized:
            color = WARNING
        self.set_run_status(instance_number, text, color, persist_report=False, save_data=False, refresh_table=False)

    def get_report_rows(self) -> list[dict[str, str]]:
        instance_ids = {
            *self.state.instance_names.keys(),
            *self.state.profile_names.keys(),
            *self.state.run_states.keys(),
            *self.state.instance_reports.keys(),
        }
        rows: list[dict[str, str]] = []
        for instance_number in sorted(instance_ids):
            if instance_number in self.state.deleted_instances:
                continue
            report = self._ensure_instance_report(instance_number)
            rows.append(
                {
                    "instance": f"Firefox {instance_number}",
                    "profile": self.state.profile_names.get(instance_number, "No account name"),
                    "account_id": str(report.get("account_id", "") or "-"),
                    "date_birth": str(report.get("date_birth", "") or "-"),
                    "gender": str(report.get("gender", "") or "-"),
                    "gmail": str(report.get("gmail", "") or "-"),
                    "action": str(report.get("last_action", "None")),
                    "status": str(report.get("last_status", self.state.run_states.get(instance_number, "Idle"))),
                    "runs": str(report.get("run_count", 0)),
                    "done": str(report.get("success_count", 0)),
                    "failed": str(report.get("fail_count", 0)),
                    "updated": str(report.get("last_updated", "-")),
                }
            )
        return rows

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
        }
        return labels.get(action_key, action_key.replace("_", " ").title())

    def _ensure_instance_report(self, instance_number: int) -> dict:
        report = self.state.instance_reports.get(instance_number)
        if not isinstance(report, dict):
            report = {}
        report.setdefault("last_action", "None")
        report.setdefault("last_status", self.state.run_states.get(instance_number, "Idle"))
        report.setdefault("last_note", "")
        report.setdefault("account_id", "")
        report.setdefault("date_birth", "")
        report.setdefault("gender", "")
        report.setdefault("gmail", "")
        report.setdefault("last_updated", "-")
        report.setdefault("run_count", 0)
        report.setdefault("success_count", 0)
        report.setdefault("fail_count", 0)
        report.setdefault("_result_pending", False)
        report.setdefault("_last_counted_signature", "")
        self.state.instance_reports[instance_number] = report
        return report

    def _hydrate_reports_from_cookie_files(self) -> None:
        changed = False
        for cookie_file in COOKIE_DIR.glob("cookies_*.json"):
            match = re.search(r"cookies_(\d+)\.json$", cookie_file.name)
            if not match:
                continue
            instance_number = int(match.group(1))
            if instance_number in self.state.deleted_instances:
                continue

            report = self._ensure_instance_report(instance_number)
            if str(report.get("account_id", "") or "").strip():
                continue

            try:
                with cookie_file.open("r", encoding="utf-8") as handle:
                    cookies = json.load(handle)
            except Exception:
                continue

            for cookie in cookies if isinstance(cookies, list) else []:
                if str(cookie.get("name", "")).strip() != "c_user":
                    continue
                cookie_value = str(cookie.get("value", "")).strip()
                if cookie_value.isdigit():
                    report["account_id"] = cookie_value
                    changed = True
                    break

        if changed:
            self.save_instance_data()

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
                "date_birth": str(report.get("date_birth", "") or ""),
                "gender": str(report.get("gender", "") or ""),
                "gmail": str(report.get("gmail", "") or ""),
            }
            profile_name = self.state.profile_names.get(
                instance_number,
                self.state.instance_names.get(instance_number, f"Firefox {instance_number}"),
            )
            session_label = self.state.instance_names.get(instance_number, f"Firefox {instance_number}")
            last_status = str(report.get("last_status") or self.state.run_states.get(instance_number, "Idle"))

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
        for report_key in ("account_id", "date_birth", "gender", "gmail"):
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
