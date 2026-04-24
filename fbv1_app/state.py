from __future__ import annotations

from dataclasses import dataclass, field
from tkinter import BooleanVar, IntVar, StringVar
from typing import Any


@dataclass
class AppState:
    firefox_buttons: list[tuple[Any, Any]] = field(default_factory=list)
    credential_entries: dict[int, Any] = field(default_factory=dict)
    credentials_dict: dict[int, str] = field(default_factory=dict)
    drivers: dict[int, Any] = field(default_factory=dict)
    instance_names: dict[int, str] = field(default_factory=dict)
    profile_names: dict[int, str] = field(default_factory=dict)
    preview_updated_at: dict[int, str] = field(default_factory=dict)
    deleted_instances: set[int] = field(default_factory=set)
    image_labels: dict[int, Any] = field(default_factory=dict)
    cover_labels: dict[int, Any] = field(default_factory=dict)
    avatar_labels: dict[int, Any] = field(default_factory=dict)
    avatar_name_labels: dict[int, Any] = field(default_factory=dict)
    instance_media_frames: dict[int, Any] = field(default_factory=dict)
    instance_text_frames: dict[int, Any] = field(default_factory=dict)
    instance_title_labels: dict[int, Any] = field(default_factory=dict)
    instance_hint_labels: dict[int, Any] = field(default_factory=dict)
    instance_detail_labels: dict[int, Any] = field(default_factory=dict)
    preview_status_labels: dict[int, Any] = field(default_factory=dict)
    run_status_labels: dict[int, Any] = field(default_factory=dict)
    run_states: dict[int, str] = field(default_factory=dict)
    instance_reports: dict[int, dict[str, Any]] = field(default_factory=dict)
    backend_profile_ids: dict[int, str] = field(default_factory=dict)
    photo_upload_paths: dict[int, str] = field(default_factory=dict)
    cover_upload_paths: dict[int, str] = field(default_factory=dict)
    photo_upload_descriptions: dict[int, str] = field(default_factory=dict)
    instance_body_frames: dict[int, Any] = field(default_factory=dict)
    preview_monitor_tokens: dict[int, int] = field(default_factory=dict)
    run_summary: list[str] = field(default_factory=list)
    show_media_previews: bool = False
    batch_running: bool = False
    batch_stop_requested: bool = False


class AppVars:
    def __init__(self, root: Any) -> None:
        self.file_type_var = IntVar(master=root)
        self.watch_video_var = IntVar(master=root)
        self.like_video_var = IntVar(master=root)
        self.comment_video_var = IntVar(master=root)
        self.share_video_var = IntVar(master=root)
        self.link_video_var = IntVar(master=root)
        self.scroll_var = IntVar(master=root)
        self.platform_var = StringVar(master=root, value="facebook")
        self.action_var = StringVar(master=root, value="login")
        self.watch_count_var = StringVar(master=root)
        self.watch_duration_var = StringVar(master=root)
        self.scroll_duration_var = StringVar(master=root)
        self.like_count_var = StringVar(master=root)
        self.comment_text_var = StringVar(master=root)
        self.video_link_var = StringVar(master=root)
        self.group_urls_var = StringVar(master=root)
        self.description_var = StringVar(master=root)
        self.reel_folder_or_file_var = StringVar(master=root)
        self.page_link_var = StringVar(master=root)
        self.share_group_count_var = StringVar(master=root)
        self.post_text_var = StringVar(master=root)
        self.get_id_result_var = StringVar(master=root)
        self.clear_data_var = IntVar(master=root)
        self.switch_reel_var = BooleanVar(master=root)
        self.switch_page_var = BooleanVar(master=root)
        self.paste_back_fb_var = BooleanVar(master=root)
        self.description_check_var = BooleanVar(master=root)
        self.auto_run_var = BooleanVar(master=root)
        self.click_run_var = BooleanVar(master=root)
        self.switch_video_var = BooleanVar(master=root)
        self.switch_picture_var = BooleanVar(master=root)
        self.switch_share_var = BooleanVar(master=root)
        self.start_instance_var = IntVar(master=root)
        self.end_instance_var = IntVar(master=root)
        self.max_instances_var = IntVar(master=root)
        self.time_run_var = BooleanVar(master=root)
        self.browser_mode_var = StringVar(master=root, value="pc")
        self.thread_count_var = IntVar(master=root, value=3)
