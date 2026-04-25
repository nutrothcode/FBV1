from __future__ import annotations

import importlib.util
import json
import math
import os
import csv
import threading
import time
import tkinter as tk
import tkinter.ttk as ttk
import urllib.error
import urllib.request
from urllib.parse import urlparse
from tkinter import font as tkfont
from tkinter import (
    BOTH,
    LEFT,
    RIGHT,
    X,
    Y,
    Button,
    Canvas,
    Checkbutton,
    Entry,
    Frame,
    Label,
    Scrollbar,
    Toplevel,
    filedialog,
    messagebox,
    simpledialog,
)

import pandas as pd
from PIL import Image, ImageTk

from .browser_manager import BrowserManager
from .config import ICON_PATH, LOGO_PATH, PLATFORM_FOLDER_DIRS
from .facebook_actions import FacebookActions
from .instance_manager import InstanceManager
from .platforms import PLATFORM_CHOICES, PLATFORM_CONFIG, platform_actions, platform_columns, platform_label
from .state import AppState, AppVars
from .theme import (
    ACCENT,
    ACCENT_HOVER,
    APP_BG,
    BADGE_FONT,
    BODY_FONT,
    BORDER,
    BUTTON_FONT,
    BUTTON_STYLES,
    DANGER,
    HEADER_BG,
    INPUT_BG,
    NEUTRAL_HOVER,
    SECTION_FONT,
    SIDEBAR_BG,
    SIDEBAR_PANEL_BG,
    SMALL_FONT,
    SECONDARY,
    SUCCESS,
    SURFACE_ALT,
    SURFACE_BG,
    TEXT_MUTED,
    TEXT_ON_DARK,
    TEXT_PRIMARY,
    TEXT_SUBTLE,
    TITLE_FONT,
    WARNING,
)


class FacebookToolApp:
    THEME_PALETTES = {
        "dark": {
            "app": APP_BG,
            "surface": SURFACE_BG,
            "alt": SURFACE_ALT,
            "border": BORDER,
            "text": TEXT_PRIMARY,
            "muted": TEXT_MUTED,
            "subtle": TEXT_SUBTLE,
            "input_bg": INPUT_BG,
            "input_fg": "#082a39",
            "button_bg": SECONDARY,
            "button_hover": "#1a5369",
        },
        "light": {
            "app": "#eef3f7",
            "surface": "#ffffff",
            "alt": "#f5f8fb",
            "border": "#cbd5e1",
            "text": "#0f172a",
            "muted": "#475569",
            "subtle": "#64748b",
            "input_bg": "#ffffff",
            "input_fg": "#0f172a",
            "button_bg": "#e2e8f0",
            "button_hover": "#cbd5e1",
        },
    }
    PLATFORM_CONFIG = PLATFORM_CONFIG
    PLATFORMS = list(PLATFORM_CHOICES)
    ACTIONS_BY_PLATFORM = {platform: platform_actions(platform) for _label, platform in PLATFORMS}
    # Fixed table layout only. This does not define account types and does not limit row count.
    # Account types and account rows are loaded dynamically and can grow as needed.
    # Third tuple value is the starting column width in pixels.
    ACCOUNT_TYPE_COLORS = [
        ("#d9f99d", "#1f3b08"),
        ("#bae6fd", "#083344"),
        ("#ddd6fe", "#2e1065"),
        ("#fecdd3", "#881337"),
        ("#fed7aa", "#7c2d12"),
        ("#bbf7d0", "#052e16"),
        ("#bfdbfe", "#172554"),
        ("#fde68a", "#713f12"),
        ("#fbcfe8", "#831843"),
        ("#ccfbf1", "#134e4a"),
        ("#e9d5ff", "#581c87"),
        ("#c7d2fe", "#312e81"),
    ]
    REPORT_PAGE_SIZE = 100
    REPORT_COLUMNS_BY_PLATFORM = {platform: platform_columns(platform) for _label, platform in PLATFORMS}

    def __init__(self) -> None:
        self.Frame = Frame
        self.Button = Button
        self.Label = Label
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.simpledialog = simpledialog

        self.root = tk.Tk()
        self.root.title("FBV1 Auto Post Tool")
        self.root.geometry("1180x690")
        self.root.minsize(980, 620)
        self.root.configure(bg=APP_BG)
        self._configure_default_fonts()

        self.state = AppState()
        self.vars = AppVars(self.root)
        self._icon_photo = None
        self.action_buttons: dict[str, Button] = {}
        self.platform_buttons: dict[str, Button] = {}
        self.control_buttons: dict[str, Button] = {}
        self.action_section: Frame | None = None
        self.total_count_label: Label | None = None
        self.live_count_label: Label | None = None
        self.die_count_label: Label | None = None
        self.no_login_count_label: Label | None = None
        self.processing_count_label: Label | None = None
        self.active_count_label: Label | None = None
        self.deleted_count_label: Label | None = None
        self.current_action_label: Label | None = None
        self.workspace_title_label: Label | None = None
        self.workspace_subtitle_label: Label | None = None
        self.account_workspace_label: Label | None = None
        self.account_workspace_hint_label: Label | None = None
        self.import_format_label: Label | None = None
        self.image_toggle_button: Button | None = None
        self.profiles_tab_button: Button | None = None
        self.report_tab_button: Button | None = None
        self.monitor_tab_button: Button | None = None
        self.pc_mode_button: Button | None = None
        self.phone_mode_button: Button | None = None
        self.check_live_buttons: list[Button] = []
        self.workspace_tab: str = "profiles"
        self.report_tree = None
        self.report_column_keys: list[str] = []
        self.monitor_tree = None
        self.platform_tool_windows: dict[str, Toplevel] = {}
        self.platform_tool_trees: dict[str, ttk.Treeview] = {}
        self.platform_tool_status_labels: dict[str, Label] = {}
        self.platform_tool_stat_labels: dict[str, dict[str, Label]] = {}
        self.platform_tool_input_refs: dict[str, dict[str, object]] = {}
        self.platform_tool_country_type_menus: dict[str, ttk.Combobox] = {}
        self.platform_tool_account_type_menus: dict[str, ttk.Combobox] = {}
        self.backend_status_label: Label | None = None
        self.monitor_profile_count_label: Label | None = None
        self.monitor_live_count_label: Label | None = None
        self.monitor_review_count_label: Label | None = None
        self.monitor_failed_count_label: Label | None = None
        self.backend_base_url_var = tk.StringVar(
            master=self.root,
            value=os.environ.get("FBV1_BACKEND_URL", "http://127.0.0.1:8010"),
        )
        self.backend_target_url_var = tk.StringVar(
            master=self.root,
            value=os.environ.get(
                "FBV1_CHECKER_URL",
                f"{os.environ.get('FBV1_BACKEND_URL', 'http://127.0.0.1:8010').rstrip('/')}/api/health",
            ),
        )
        self.backend_review_keywords_var = tk.StringVar(
            master=self.root,
            value="verification required, review",
        )
        self.backend_failure_keywords_var = tk.StringVar(
            master=self.root,
            value="disabled, blocked",
        )
        self.legacy_store_var = tk.StringVar(master=self.root, value="All")
        self.legacy_store_name_var = tk.StringVar(master=self.root)
        self.account_group_var = tk.StringVar(master=self.root, value="All")
        self.account_group_name_var = tk.StringVar(master=self.root)
        self.legacy_find_var = tk.StringVar(master=self.root)
        self.legacy_add_by_var = tk.StringVar(master=self.root, value="Account")
        self.legacy_status_var = tk.StringVar(master=self.root, value="Ready")
        self.theme_mode_var = tk.StringVar(master=self.root, value="dark")
        self.legacy_stores: list[str] = ["All"]
        self.account_groups: list[str] = ["All"]
        self.legacy_store_combo = None
        self.account_group_combo = None
        self.legacy_account_list = None
        self.theme_toggle_button: Button | None = None
        self._backend_refresh_after_id: str | None = None
        self._backup_after_id: str | None = None
        self._open_browser_sync_after_id: str | None = None
        self._auto_live_check_after_id: str | None = None
        self.report_page = 1
        self.report_page_label: Label | None = None
        self.report_prev_button: Button | None = None
        self.report_next_button: Button | None = None

        self._apply_icon()
        self.browser = BrowserManager(self)
        self.actions = FacebookActions(self)
        self.instances = InstanceManager(self)

        self._build_layout()
        self._build_controls()
        self.instances.initialize_app()
        self._restore_saved_account_type_lists()
        self._sync_legacy_account_types_from_reports()
        self._render_action_buttons()
        self.refresh_dashboard()
        self._apply_runtime_theme()
        self._schedule_backend_refresh()
        self._schedule_auto_backup()
        self._schedule_open_browser_sync()
        self._schedule_auto_live_check(initial=True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def run(self) -> None:
        self.root.mainloop()

    def _on_close(self) -> None:
        try:
            if self._backup_after_id:
                self.root.after_cancel(self._backup_after_id)
            if self._backend_refresh_after_id:
                self.root.after_cancel(self._backend_refresh_after_id)
            if self._open_browser_sync_after_id:
                self.root.after_cancel(self._open_browser_sync_after_id)
            if self._auto_live_check_after_id:
                self.root.after_cancel(self._auto_live_check_after_id)
            if hasattr(self, "instances"):
                self.instances.save_instance_data()
        finally:
            self.root.destroy()

    def _configure_default_fonts(self) -> None:
        try:
            family, size = BODY_FONT[0], BODY_FONT[1]
            for font_name in (
                "TkDefaultFont",
                "TkTextFont",
                "TkMenuFont",
                "TkHeadingFont",
                "TkCaptionFont",
                "TkSmallCaptionFont",
                "TkIconFont",
                "TkTooltipFont",
            ):
                try:
                    tkfont.nametofont(font_name).configure(family=family, size=size)
                except tk.TclError:
                    continue
        except Exception:
            pass

    def _apply_icon(self) -> None:
        if not ICON_PATH.exists():
            return
        icon_image = Image.open(ICON_PATH)
        self._icon_photo = ImageTk.PhotoImage(icon_image)
        self.root.iconphoto(False, self._icon_photo)

    def _build_layout(self) -> None:
        self._build_legacy_layout()

    def _build_legacy_layout(self) -> None:
        self.main_frame = Frame(self.root, bg=APP_BG)
        self.main_frame.pack(fill=BOTH, expand=True, padx=8, pady=8)

        self.legacy_header = Frame(self.main_frame, bg=SURFACE_BG, highlightbackground=BORDER, highlightthickness=1, bd=0)
        self.legacy_header.pack(fill=X)

        brand = Frame(self.legacy_header, bg=SURFACE_BG)
        brand.pack(side=LEFT, padx=10, pady=8)
        if LOGO_PATH.exists():
            logo_image = Image.open(LOGO_PATH)
            logo_image.thumbnail((34, 34))
            logo_photo = ImageTk.PhotoImage(logo_image)
            logo_label = Label(brand, image=logo_photo, bg=SURFACE_BG)
            logo_label.image = logo_photo
            logo_label.pack(side=LEFT, padx=(0, 8))
        Label(brand, text="FBV1 Auto Post Tool", bg=SURFACE_BG, fg=TEXT_PRIMARY, font=TITLE_FONT).pack(anchor="w")
        Label(brand, text="System multi-platform session manager", bg=SURFACE_BG, fg=TEXT_MUTED, font=SMALL_FONT).pack(anchor="w")

        top_controls = Frame(self.legacy_header, bg=SURFACE_BG)
        top_controls.pack(side=LEFT, fill=X, expand=True, padx=10, pady=8)
        Label(top_controls, text="Country Type", bg=SURFACE_BG, fg=TEXT_MUTED, font=SMALL_FONT).grid(row=0, column=0, sticky="w")
        self.legacy_store_combo = ttk.Combobox(
            top_controls,
            textvariable=self.legacy_store_var,
            values=tuple(self.legacy_stores),
            state="readonly",
            width=18,
        )
        self.legacy_store_combo.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=(0, 8),
        )
        self.legacy_store_combo.bind("<<ComboboxSelected>>", lambda _event: self._select_account_type())
        Label(top_controls, text="New Country", bg=SURFACE_BG, fg=TEXT_MUTED, font=SMALL_FONT).grid(row=0, column=1, sticky="w")
        self.style_entry(Entry(top_controls, textvariable=self.legacy_store_name_var), width=20).grid(
            row=1,
            column=1,
            sticky="ew",
            padx=(0, 8),
        )
        self.create_button(top_controls, "Create", self._create_legacy_store, kind="secondary", compact=True).grid(
            row=1,
            column=2,
            padx=(0, 6),
        )
        self.create_button(top_controls, "Remove", self._remove_legacy_store, kind="neutral", compact=True).grid(row=1, column=3)
        Label(top_controls, text="Account Type", bg=SURFACE_BG, fg=TEXT_MUTED, font=SMALL_FONT).grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.account_group_combo = ttk.Combobox(
            top_controls,
            textvariable=self.account_group_var,
            values=tuple(self.account_groups),
            state="readonly",
            width=18,
        )
        self.account_group_combo.grid(row=3, column=0, sticky="ew", padx=(0, 8))
        self.account_group_combo.bind("<<ComboboxSelected>>", lambda _event: self._select_custom_account_type())
        Label(top_controls, text="New Account Type", bg=SURFACE_BG, fg=TEXT_MUTED, font=SMALL_FONT).grid(row=2, column=1, sticky="w", pady=(6, 0))
        self.style_entry(Entry(top_controls, textvariable=self.account_group_name_var), width=20).grid(
            row=3,
            column=1,
            sticky="ew",
            padx=(0, 8),
        )
        self.create_button(top_controls, "Add", self._create_custom_account_type, kind="secondary", compact=True).grid(
            row=3,
            column=2,
            padx=(0, 6),
        )
        self.create_button(top_controls, "Remove", self._remove_custom_account_type, kind="neutral", compact=True).grid(row=3, column=3)
        self.import_format_label = Label(
            top_controls,
            text="",
            bg=SURFACE_BG,
            fg=TEXT_MUTED,
            font=SMALL_FONT,
        )
        self.import_format_label.grid(row=4, column=0, columnspan=4, sticky="w", pady=(8, 0))
        top_controls.grid_columnconfigure(0, weight=1)
        top_controls.grid_columnconfigure(1, weight=1)

        self.current_action_label = Label(
            self.legacy_header,
            text="FACEBOOK | LOGIN",
            bg=ACCENT,
            fg=TEXT_ON_DARK,
            font=BADGE_FONT,
            padx=12,
            pady=6,
        )
        self.current_action_label.pack(side=RIGHT, padx=(8, 10), pady=10)

        self.theme_toggle_button = self.create_button(
            self.legacy_header,
            "White Theme",
            self._toggle_theme,
            "neutral",
            True,
        )
        self.theme_toggle_button.pack(side=RIGHT, padx=(0, 4), pady=10)

        stats_wrap = Frame(self.legacy_header, bg=SURFACE_BG)
        stats_wrap.pack(side=RIGHT, pady=8)
        self.total_count_label = self._build_legacy_counter(stats_wrap, "Total", "0", SUCCESS)
        self.no_login_count_label = self._build_legacy_counter(stats_wrap, "No Login", "0", "#6b7280")
        self.die_count_label = self._build_legacy_counter(stats_wrap, "Die", "0", DANGER)
        self.live_count_label = self._build_legacy_counter(stats_wrap, "Live", "0", ACCENT)
        self.processing_count_label = None
        self.active_count_label = None
        self.deleted_count_label = None

        body = Frame(self.main_frame, bg=APP_BG)
        body.pack(fill=BOTH, expand=True, pady=(8, 0))

        self.sidebar = Frame(body, bg=SURFACE_BG, width=252, highlightbackground=BORDER, highlightthickness=1, bd=0)
        self.sidebar.pack(side=LEFT, fill=Y)
        self.sidebar.pack_propagate(False)

        self.workspace = Frame(body, bg=SURFACE_BG, highlightbackground=BORDER, highlightthickness=1, bd=0)
        self.workspace.pack(side=RIGHT, fill=BOTH, expand=True, padx=(8, 0))

        tool_bar = Frame(self.workspace, bg=SURFACE_BG)
        tool_bar.pack(fill=X, padx=10, pady=(8, 6))
        self.account_workspace_label = Label(
            tool_bar,
            text="Account Table",
            bg=SURFACE_BG,
            fg=TEXT_PRIMARY,
            font=SECTION_FONT,
        )
        self.account_workspace_label.pack(side=LEFT)
        self.pc_mode_button = self.create_button(tool_bar, "PC Mode", lambda: self._set_browser_mode("pc"), "secondary", True)
        self.pc_mode_button.pack(side=LEFT, padx=(10, 4))
        self.phone_mode_button = self.create_button(tool_bar, "Phone Mode", lambda: self._set_browser_mode("phone"), "neutral", True)
        self.phone_mode_button.pack(side=LEFT, padx=(0, 10))
        self.create_button(tool_bar, "Find Acc", self._search_report_table, "secondary", True).pack(side=LEFT, padx=(0, 4))
        check_live_button = self.create_button(tool_bar, "Check Login", self._run_manual_check_live, "primary", True)
        check_live_button.pack(side=LEFT, padx=(0, 4))
        check_live_button._check_live_pack_info = check_live_button.pack_info()
        self.check_live_buttons.append(check_live_button)
        find_entry = self.style_entry(Entry(tool_bar, textvariable=self.legacy_find_var), width=24)
        find_entry.pack(side=LEFT)
        find_entry.bind("<Return>", lambda _event: self._search_report_table())
        self.create_button(tool_bar, "Save Setting", self.instances_save_if_ready, "success", True).pack(side=RIGHT)

        self.workspace_title_label = Label(
            self.workspace,
            text="Execution Table",
            bg=SURFACE_BG,
            fg=TEXT_PRIMARY,
            font=TITLE_FONT,
        )
        self.workspace_subtitle_label = Label(
            self.workspace,
            text="",
            bg=SURFACE_BG,
            fg=TEXT_MUTED,
            font=SMALL_FONT,
        )
        self.account_workspace_hint_label = self.workspace_subtitle_label

        self.table_panel = Frame(self.workspace, bg=SURFACE_ALT)
        self.table_panel.pack(fill=BOTH, expand=True, padx=10, pady=(0, 8))
        self._build_report_table(self.table_panel)
        self._build_report_pagination(self.workspace)

        footer = Frame(self.workspace, bg=SURFACE_BG)
        footer.pack(fill=X, padx=10, pady=(0, 8))
        self.create_button(footer, "Clear", self._reset_report_data, "neutral", True).pack(side=LEFT, padx=(0, 6))
        self.create_button(footer, "Export Account", self.export_report_file, "secondary", True).pack(side=LEFT, padx=(0, 6))
        self.create_button(footer, "Save Data", self.instances_save_if_ready, "warning", True).pack(side=LEFT, padx=(0, 6))
        self.create_button(footer, "Backup Account", lambda: self.instances.backup_instance_data(), "success", True).pack(side=LEFT, padx=(0, 6))
        self.create_button(footer, "Open Folder", self.instances_open_if_ready, "neutral", True).pack(side=LEFT, padx=(0, 6))

        self.profiles_panel = Frame(self.root, bg=SURFACE_ALT)
        self.canvas = Canvas(self.profiles_panel, bg=SURFACE_ALT, bd=0, highlightthickness=0)
        self.button_frame = Frame(self.canvas, bg=SURFACE_ALT)
        self._button_window_id = self.canvas.create_window((0, 0), window=self.button_frame, anchor="nw")
        self.scroll_y = Scrollbar(self.profiles_panel, orient="vertical", command=self.canvas.yview)
        self.monitor_panel = Frame(self.root, bg=SURFACE_ALT)
        self.workspace_tab = "table"

    def _build_legacy_counter(self, parent: Frame, label: str, value: str, color: str) -> Label:
        card = Frame(parent, bg=color, width=82, height=54)
        card.pack(side=LEFT, padx=(5, 0))
        card.pack_propagate(False)
        Label(card, text=label, bg=color, fg=TEXT_ON_DARK, font=SMALL_FONT).pack(anchor="w", padx=9, pady=(6, 0))
        value_label = Label(card, text=value, bg=color, fg=TEXT_ON_DARK, font=("Bahnschrift SemiBold", 14))
        value_label.pack(anchor="w", padx=9)
        return value_label

    def instances_save_if_ready(self) -> None:
        if hasattr(self, "instances"):
            self.instances.save_instance_data()

    def instances_open_if_ready(self) -> None:
        if hasattr(self, "instances"):
            self.instances.open_data_folder()

    def _build_header(self) -> None:
        header = Frame(self.root, bg=HEADER_BG, height=86, highlightbackground=BORDER, highlightthickness=1, bd=0)
        header.pack(fill=X, padx=12, pady=(12, 10))
        header.pack_propagate(False)

        logo_wrap = Frame(header, bg=HEADER_BG)
        logo_wrap.pack(side=LEFT, padx=14)

        if LOGO_PATH.exists():
            logo_image = Image.open(LOGO_PATH)
            logo_image.thumbnail((36, 36))
            logo_photo = ImageTk.PhotoImage(logo_image)
            logo_label = Label(logo_wrap, image=logo_photo, bg=HEADER_BG)
            logo_label.image = logo_photo
            logo_label.pack(side=LEFT)

        text_wrap = Frame(logo_wrap, bg=HEADER_BG)
        text_wrap.pack(side=LEFT, padx=(10, 0))

        Label(text_wrap, text="FBV1 MULTI PLATFORM CONSOLE", bg=HEADER_BG, fg=TEXT_PRIMARY, font=TITLE_FONT).pack(anchor="w")
        Label(
            text_wrap,
            text="Select a platform, launch profiles, and review account session data.",
            bg=HEADER_BG,
            fg=TEXT_MUTED,
            font=BODY_FONT,
        ).pack(anchor="w", pady=(2, 0))

        self.current_action_label = Label(
            header,
            text="FACEBOOK | LOGIN",
            bg=ACCENT,
            fg=TEXT_ON_DARK,
            font=BADGE_FONT,
            padx=14,
            pady=6,
            highlightthickness=1,
            highlightbackground=ACCENT_HOVER,
        )
        self.current_action_label.pack(side=RIGHT, padx=14, pady=20)

    def _build_workspace(self) -> None:
        self.workspace_header = Frame(
            self.workspace,
            bg=SURFACE_BG,
            highlightbackground=BORDER,
            highlightthickness=1,
            bd=0,
        )
        self.workspace_header.pack(fill=X)

        header_left = Frame(self.workspace_header, bg=SURFACE_BG)
        header_left.pack(side=LEFT, fill=X, expand=True, padx=16, pady=14)

        self.workspace_title_label = Label(
            header_left,
            text="Profiles Workspace",
            bg=SURFACE_BG,
            fg=TEXT_PRIMARY,
            font=TITLE_FONT,
        )
        self.workspace_title_label.pack(anchor="w")
        self.workspace_subtitle_label = Label(
            header_left,
            text="Launch, rename, delete, and review profile sessions below.",
            bg=SURFACE_BG,
            fg=TEXT_MUTED,
            font=BODY_FONT,
        )
        self.workspace_subtitle_label.pack(anchor="w", pady=(2, 0))

        header_right = Frame(self.workspace_header, bg=SURFACE_BG)
        header_right.pack(side=RIGHT, padx=12, pady=10)

        self.image_toggle_button = self.create_button(
            header_right,
            text="Hide Images",
            command=self.toggle_media_previews,
            kind="neutral",
            compact=True,
        )
        self.image_toggle_button.pack(side=LEFT, padx=(0, 8))

        stats_wrap = Frame(header_right, bg=SURFACE_BG)
        stats_wrap.pack(side=LEFT)

        self.total_count_label = self._build_stat_card(stats_wrap, "Total", "0")
        self.die_count_label = self._build_stat_card(stats_wrap, "Die", "0")
        self.live_count_label = self._build_stat_card(stats_wrap, "Live", "0")
        self.processing_count_label = self._build_stat_card(stats_wrap, "Processing", "0")
        self.active_count_label = self._build_stat_card(stats_wrap, "Active Profiles", "0")
        self.deleted_count_label = self._build_stat_card(stats_wrap, "Deleted", "0")

        instances_shell = Frame(
            self.workspace,
            bg=SURFACE_BG,
            highlightbackground=BORDER,
            highlightthickness=1,
            bd=0,
        )
        instances_shell.pack(fill=BOTH, expand=True, pady=(10, 0))

        toolbar = Frame(instances_shell, bg=SURFACE_BG)
        toolbar.pack(fill=X, padx=14, pady=(12, 8))
        self.account_workspace_label = Label(
            toolbar,
            text="Account Workspace",
            bg=SURFACE_BG,
            fg=TEXT_PRIMARY,
            font=SECTION_FONT,
        )
        self.account_workspace_label.pack(side=LEFT, padx=(0, 10))
        self.pc_mode_button = self.create_button(
            toolbar,
            text="PC Mode",
            command=lambda: self._set_browser_mode("pc"),
            kind="secondary",
            compact=True,
        )
        self.pc_mode_button.pack(side=LEFT, padx=(0, 6))
        self.phone_mode_button = self.create_button(
            toolbar,
            text="Phone Mode",
            command=lambda: self._set_browser_mode("phone"),
            kind="neutral",
            compact=True,
        )
        self.phone_mode_button.pack(side=LEFT, padx=(0, 10))
        self.profiles_tab_button = self.create_button(
            toolbar,
            text="Profiles",
            command=lambda: self.switch_workspace_tab("profiles"),
            kind="secondary",
            compact=True,
        )
        self.profiles_tab_button.pack(side=LEFT, padx=(0, 6))
        self.report_tab_button = self.create_button(
            toolbar,
            text="Table",
            command=lambda: self.switch_workspace_tab("table"),
            kind="neutral",
            compact=True,
        )
        self.report_tab_button.pack(side=LEFT)
        self.monitor_tab_button = self.create_button(
            toolbar,
            text="Monitor",
            command=lambda: self.switch_workspace_tab("monitor"),
            kind="neutral",
            compact=True,
        )
        self.monitor_tab_button.pack(side=LEFT, padx=(6, 0))
        check_live_button = self.create_button(
            toolbar,
            text="Check Login",
            command=self._run_manual_check_live,
            kind="primary",
            compact=True,
        )
        check_live_button.pack(side=LEFT, padx=(6, 0))
        check_live_button._check_live_pack_info = check_live_button.pack_info()
        self.check_live_buttons.append(check_live_button)
        self.create_button(
            toolbar,
            text="Reset Table",
            command=self._reset_report_data,
            kind="danger",
            compact=True,
        ).pack(side=LEFT, padx=(6, 0))
        self.account_workspace_hint_label = Label(
            toolbar,
            text="Each card shows account media preview and quick operator actions.",
            bg=SURFACE_BG,
            fg=TEXT_MUTED,
            font=SMALL_FONT,
        )
        self.account_workspace_hint_label.pack(side=RIGHT)

        content_frame = Frame(instances_shell, bg=SURFACE_ALT)
        content_frame.pack(fill=BOTH, expand=True, padx=12, pady=(0, 12))

        self.profiles_panel = Frame(content_frame, bg=SURFACE_ALT)
        self.profiles_panel.pack(fill=BOTH, expand=True)
        canvas_frame = Frame(self.profiles_panel, bg=SURFACE_ALT)
        canvas_frame.pack(fill=BOTH, expand=True)

        self.canvas = Canvas(canvas_frame, bg=SURFACE_ALT, bd=0, highlightthickness=0)
        self.scroll_y = Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        self.button_frame = Frame(self.canvas, bg=SURFACE_ALT)
        self.button_frame.bind(
            "<Configure>",
            lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )

        self._button_window_id = self.canvas.create_window((0, 0), window=self.button_frame, anchor="nw")
        self.canvas.bind(
            "<Configure>",
            lambda event: self.canvas.itemconfigure(self._button_window_id, width=event.width),
        )
        self.canvas.configure(yscrollcommand=self.scroll_y.set)
        self.canvas.pack(side=LEFT, fill=BOTH, expand=True)
        self.scroll_y.pack(side=RIGHT, fill=Y)

        self.table_panel = Frame(content_frame, bg=SURFACE_ALT)
        self._build_report_table(self.table_panel)
        self.monitor_panel = Frame(content_frame, bg=SURFACE_ALT)
        self._build_backend_monitor(self.monitor_panel)
        self.switch_workspace_tab("profiles")

    def _build_stat_card(self, parent: Frame, label: str, value: str) -> Label:
        card = Frame(parent, bg=SURFACE_ALT, highlightbackground=BORDER, highlightthickness=1, bd=0)
        card.pack(side=LEFT, padx=4)
        Frame(card, bg=ACCENT, height=2).pack(fill=X)
        Label(card, text=label, bg=SURFACE_ALT, fg=TEXT_MUTED, font=SMALL_FONT).pack(anchor="w", padx=10, pady=(6, 0))
        value_label = Label(card, text=value, bg=SURFACE_ALT, fg=TEXT_PRIMARY, font=("Bahnschrift SemiBold", 13))
        value_label.pack(anchor="w", padx=10, pady=(1, 6))
        return value_label

    def _build_report_table(self, parent: Frame) -> None:
        style = ttk.Style(self.root)
        style.configure(
            "Report.Treeview",
            background=SURFACE_BG,
            fieldbackground=SURFACE_BG,
            foreground=TEXT_PRIMARY,
            bordercolor=BORDER,
            rowheight=24,
            relief="flat",
        )
        style.configure(
            "Report.Treeview.Heading",
            background=SIDEBAR_PANEL_BG,
            foreground=TEXT_PRIMARY,
            bordercolor=BORDER,
            relief="flat",
            font=SECTION_FONT,
        )

        shell = Frame(parent, bg=SURFACE_ALT)
        shell.pack(fill=BOTH, expand=True)
        tree_frame = Frame(shell, bg=SURFACE_BG, highlightbackground=BORDER, highlightthickness=1, bd=0)
        tree_frame.pack(fill=BOTH, expand=True)

        columns = tuple(key for key, _title, _width in self._report_columns())
        self.report_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", style="Report.Treeview", selectmode="extended")
        self._apply_report_columns()

        scroll_y = Scrollbar(tree_frame, orient="vertical", command=self.report_tree.yview)
        scroll_x = Scrollbar(tree_frame, orient="horizontal", command=self.report_tree.xview)
        self.report_tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self.report_tree.tag_configure("live", background="#04e51f", foreground="#07320f")
        self.report_tree.tag_configure("review", background="#f59e0b", foreground="#ffffff")
        self.report_tree.tag_configure("login_required", background="#d1d5db", foreground="#111827")
        self.report_tree.tag_configure("failed", background="#ff3b1f", foreground="#ffffff")
        self.report_tree.tag_configure("ip_mismatch", background="#4D1C26", foreground="#ffffff")
        self.report_tree.tag_configure("working", background="#E5DA05", foreground="#010C03")
        self.report_tree.tag_configure("select", background="#051BE5", foreground="#ffffff")
        style.map(
            "Report.Treeview",
            background=[("selected", "#051BE5")],
            foreground=[("selected", "#ffffff")],
        )
        scroll_y.pack(side=RIGHT, fill=Y)
        scroll_x.pack(side="bottom", fill=X)
        self.report_tree.pack(side=LEFT, fill=BOTH, expand=True)
        self.report_tree.bind("<Button-3>", self._show_report_context_menu)
        self.report_tree.bind("<Double-1>", lambda _event: self._open_selected_report_profile())

    def _build_report_pagination(self, parent: Frame) -> None:
        pager = Frame(parent, bg=SURFACE_BG)
        pager.pack(fill=X, padx=10, pady=(0, 8))
        self.report_prev_button = self.create_button(pager, "Prev Page", lambda: self._change_report_page(-1), "neutral", True)
        self.report_prev_button.pack(side=LEFT)
        self.report_page_label = Label(pager, text="Page 1 / 1", bg=SURFACE_BG, fg=TEXT_MUTED, font=SMALL_FONT)
        self.report_page_label.pack(side=LEFT, padx=10)
        self.report_next_button = self.create_button(pager, "Next Page", lambda: self._change_report_page(1), "neutral", True)
        self.report_next_button.pack(side=LEFT)
        Label(pager, text="100 rows per page", bg=SURFACE_BG, fg=TEXT_MUTED, font=SMALL_FONT).pack(side=LEFT, padx=12)

    def _build_backend_monitor(self, parent: Frame) -> None:
        shell = Frame(parent, bg=SURFACE_ALT)
        shell.pack(fill=BOTH, expand=True)

        controls = Frame(shell, bg=SURFACE_BG, highlightbackground=BORDER, highlightthickness=1, bd=0)
        controls.pack(fill=X, pady=(0, 10))

        top_controls = Frame(controls, bg=SURFACE_BG)
        top_controls.pack(fill=X, padx=12, pady=(12, 8))

        Label(top_controls, text="Backend URL", bg=SURFACE_BG, fg=TEXT_MUTED, font=SMALL_FONT).grid(row=0, column=0, sticky="w")
        backend_entry = self.style_entry(Entry(top_controls, textvariable=self.backend_base_url_var), width=34)
        backend_entry.grid(row=1, column=0, sticky="ew", padx=(0, 10), pady=(2, 0))

        Label(top_controls, text="Target URL", bg=SURFACE_BG, fg=TEXT_MUTED, font=SMALL_FONT).grid(row=0, column=1, sticky="w")
        target_entry = self.style_entry(Entry(top_controls, textvariable=self.backend_target_url_var), width=40)
        target_entry.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=(2, 0))

        self.create_button(
            top_controls,
            text="Refresh",
            command=self.refresh_backend_monitor_async,
            kind="secondary",
            compact=True,
        ).grid(row=1, column=2, sticky="ew", pady=(2, 0))

        top_controls.grid_columnconfigure(0, weight=1)
        top_controls.grid_columnconfigure(1, weight=1)

        keyword_controls = Frame(controls, bg=SURFACE_BG)
        keyword_controls.pack(fill=X, padx=12, pady=(0, 8))

        Label(keyword_controls, text="Review Keywords", bg=SURFACE_BG, fg=TEXT_MUTED, font=SMALL_FONT).grid(row=0, column=0, sticky="w")
        review_entry = self.style_entry(Entry(keyword_controls, textvariable=self.backend_review_keywords_var), width=34)
        review_entry.grid(row=1, column=0, sticky="ew", padx=(0, 10), pady=(2, 0))

        Label(keyword_controls, text="Failure Keywords", bg=SURFACE_BG, fg=TEXT_MUTED, font=SMALL_FONT).grid(row=0, column=1, sticky="w")
        failure_entry = self.style_entry(Entry(keyword_controls, textvariable=self.backend_failure_keywords_var), width=34)
        failure_entry.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=(2, 0))

        self.create_button(
            keyword_controls,
            text="Run Checker",
            command=self.run_backend_checker_for_selected,
            kind="warning",
            compact=True,
        ).grid(row=1, column=2, sticky="ew", padx=(0, 6), pady=(2, 0))
        self.create_button(
            keyword_controls,
            text="Reset Health",
            command=self.reset_backend_health,
            kind="secondary",
            compact=True,
        ).grid(row=1, column=3, sticky="ew", padx=(0, 6), pady=(2, 0))
        self.create_button(
            keyword_controls,
            text="Start All",
            command=self.start_all_backend_checkers,
            kind="success",
            compact=True,
        ).grid(row=1, column=4, sticky="ew", padx=(0, 6), pady=(2, 0))
        self.create_button(
            keyword_controls,
            text="Stop All",
            command=self.stop_all_backend_jobs,
            kind="danger",
            compact=True,
        ).grid(row=1, column=5, sticky="ew", pady=(2, 0))

        keyword_controls.grid_columnconfigure(0, weight=1)
        keyword_controls.grid_columnconfigure(1, weight=1)

        status_row = Frame(controls, bg=SURFACE_BG)
        status_row.pack(fill=X, padx=12, pady=(0, 12))
        self.backend_status_label = Label(
            status_row,
            text="Backend monitor idle.",
            bg=SURFACE_BG,
            fg=TEXT_MUTED,
            font=BODY_FONT,
        )
        self.backend_status_label.pack(side=LEFT)

        summary = Frame(shell, bg=SURFACE_ALT)
        summary.pack(fill=X, pady=(0, 10))
        self.monitor_profile_count_label = self._build_stat_card(summary, "Profiles", "0")
        self.monitor_live_count_label = self._build_stat_card(summary, "Live", "0")
        self.monitor_review_count_label = self._build_stat_card(summary, "Review", "0")
        self.monitor_failed_count_label = self._build_stat_card(summary, "Failed", "0")

        tree_frame = Frame(shell, bg=SURFACE_BG, highlightbackground=BORDER, highlightthickness=1, bd=0)
        tree_frame.pack(fill=BOTH, expand=True)

        columns = ("profile", "session", "health", "last_status", "checked", "reason")
        self.monitor_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", style="Report.Treeview")
        headings = {
            "profile": ("Profile", 180),
            "session": ("Session", 160),
            "health": ("Health", 90),
            "last_status": ("Last Status", 110),
            "checked": ("Last Checked", 170),
            "reason": ("Reason", 420),
        }
        for column, (title, width) in headings.items():
            self.monitor_tree.heading(column, text=title)
            self.monitor_tree.column(column, width=width, anchor="w", stretch=False)

        self.monitor_tree.tag_configure("live", background="#e7f8ee", foreground="#0f5f35")
        self.monitor_tree.tag_configure("review", background="#fff4da", foreground="#8b5a00")
        self.monitor_tree.tag_configure("failed", background="#ffe4e8", foreground="#9f1239")
        self.monitor_tree.tag_configure("unknown", background="#f1f5f9", foreground="#475569")

        scroll_y = Scrollbar(tree_frame, orient="vertical", command=self.monitor_tree.yview)
        scroll_x = Scrollbar(tree_frame, orient="horizontal", command=self.monitor_tree.xview)
        self.monitor_tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        scroll_y.pack(side=RIGHT, fill=Y)
        scroll_x.pack(side="bottom", fill=X)
        self.monitor_tree.pack(side=LEFT, fill=BOTH, expand=True)

    def switch_workspace_tab(self, tab_name: str) -> None:
        self.workspace_tab = tab_name
        if hasattr(self, "profiles_panel"):
            self.profiles_panel.pack_forget()
        if hasattr(self, "table_panel"):
            self.table_panel.pack_forget()
        if hasattr(self, "monitor_panel"):
            self.monitor_panel.pack_forget()

        if tab_name == "table":
            self.table_panel.pack(fill=BOTH, expand=True)
            self.refresh_report_table()
        elif tab_name == "monitor":
            self.monitor_panel.pack(fill=BOTH, expand=True)
            self.refresh_backend_monitor_async()
        else:
            self.profiles_panel.pack(fill=BOTH, expand=True)
        self._refresh_workspace_header()
        self._refresh_workspace_tab_buttons()

    def _refresh_workspace_tab_buttons(self) -> None:
        if self.profiles_tab_button:
            if self.workspace_tab == "profiles":
                self.profiles_tab_button.config(bg=ACCENT, fg=TEXT_ON_DARK, activebackground=ACCENT_HOVER, activeforeground=TEXT_ON_DARK)
            else:
                self.profiles_tab_button.config(
                    bg=SIDEBAR_PANEL_BG,
                    fg=TEXT_PRIMARY,
                    activebackground=SECONDARY,
                    activeforeground=TEXT_PRIMARY,
                )
        if self.report_tab_button:
            if self.workspace_tab == "table":
                self.report_tab_button.config(bg=ACCENT, fg=TEXT_ON_DARK, activebackground=ACCENT_HOVER, activeforeground=TEXT_ON_DARK)
            else:
                self.report_tab_button.config(
                    bg=SIDEBAR_PANEL_BG,
                    fg=TEXT_PRIMARY,
                    activebackground=SECONDARY,
                    activeforeground=TEXT_PRIMARY,
                )
        if self.monitor_tab_button:
            if self.workspace_tab == "monitor":
                self.monitor_tab_button.config(bg=ACCENT, fg=TEXT_ON_DARK, activebackground=ACCENT_HOVER, activeforeground=TEXT_ON_DARK)
            else:
                self.monitor_tab_button.config(
                    bg=SIDEBAR_PANEL_BG,
                    fg=TEXT_PRIMARY,
                    activebackground=SECONDARY,
                    activeforeground=TEXT_PRIMARY,
                )

    def refresh_report_table_async(self) -> None:
        try:
            self.root.after(0, self.refresh_report_table)
        except Exception:
            pass

    def _report_columns(self) -> list[tuple[str, str, int]]:
        platform = self.vars.platform_var.get()
        return platform_columns(platform)

    def _apply_report_columns(self) -> None:
        if not self.report_tree:
            return
        columns = self._report_columns()
        self.report_column_keys = [key for key, _title, _width in columns]
        self.report_tree.configure(columns=self.report_column_keys)
        for key, title, default_width in columns:
            self.report_tree.heading(key, text=title)
            self.report_tree.column(
                key,
                width=default_width,
                minwidth=max(60, min(default_width, 100)),
                anchor="w",
                stretch=True,
            )

    def _report_value(self, row: dict, key: str) -> str:
        if key == "platform_session":
            instance_label = str(row.get("instance") or "").strip()
            instance_number = self._instance_number_from_label(instance_label)
            if instance_number is not None:
                saved_name = self.state.instance_names.get(instance_number)
                if saved_name:
                    return saved_name
            platform_label = self._platform_label()
            return f"{platform_label} {instance_label}".strip()
        if key.endswith("_session"):
            session_value = row.get(key) or row.get("platform_session", "")
            if session_value:
                return str(session_value)
            instance_label = str(row.get("instance") or "").strip()
            return f"{self._platform_label()} {instance_label}".strip()

        value = row.get(key, "")
        if value is None:
            return ""
        return str(value)

    def _instance_number_from_label(self, label: str) -> int | None:
        try:
            return int(str(label).strip().rsplit(" ", 1)[1])
        except Exception:
            return None

    def refresh_report_table(self) -> None:
        if not self.report_tree:
            return
        self._apply_report_columns()
        for item in self.report_tree.get_children():
            self.report_tree.delete(item)
        query = self.legacy_find_var.get().strip().lower() if hasattr(self, "legacy_find_var") else ""
        country_type = self._selected_account_type()
        custom_type = self._selected_custom_account_type()
        filtered_rows = []
        for row in self.instances.get_report_rows():
            if country_type and not self.instances.report_matches_account_type(row, country_type):
                continue
            values_by_key = {key: self._report_value(row, key) for key in self.report_column_keys}
            if custom_type and str(row.get("account_type") or "").strip().lower() != custom_type.lower():
                continue
            if query and query not in " ".join(values_by_key.values()).lower():
                continue
            filtered_rows.append((row, values_by_key))

        total_rows = len(filtered_rows)
        total_pages = max(1, math.ceil(total_rows / self.REPORT_PAGE_SIZE))
        self.report_page = max(1, min(self.report_page, total_pages))
        start = (self.report_page - 1) * self.REPORT_PAGE_SIZE
        end = start + self.REPORT_PAGE_SIZE
        for row, values_by_key in filtered_rows[start:end]:
            values = tuple(values_by_key[key] for key in self.report_column_keys)
            instance_id = str(row.get("instance_id") or "")
            try:
                if instance_id:
                    self.report_tree.insert(
                        "",
                        "end",
                        iid=instance_id,
                        values=values,
                        tags=self._report_row_tags(row, self.report_tree),
                    )
                else:
                    self.report_tree.insert("", "end", values=values, tags=self._report_row_tags(row, self.report_tree))
            except tk.TclError:
                self.report_tree.insert("", "end", values=values, tags=self._report_row_tags(row, self.report_tree))
        self._refresh_report_pagination(total_rows, total_pages)
        if hasattr(self, "_refresh_legacy_account_list"):
            self._refresh_legacy_account_list()

    def _search_report_table(self) -> None:
        self.report_page = 1
        self.refresh_report_table()

    def _refresh_report_pagination(self, total_rows: int, total_pages: int) -> None:
        if self.report_page_label:
            self.report_page_label.config(text=f"Page {self.report_page} / {total_pages} ({total_rows} rows)")
        if self.report_prev_button:
            self.report_prev_button.config(state="normal" if self.report_page > 1 else "disabled")
        if self.report_next_button:
            self.report_next_button.config(state="normal" if self.report_page < total_pages else "disabled")

    def _change_report_page(self, delta: int) -> None:
        self.report_page = max(1, self.report_page + delta)
        self.refresh_report_table()

    def _schedule_open_browser_sync(self) -> None:
        self._open_browser_sync_after_id = None

    def _open_browser_sync_tick(self) -> None:
        return

    def _schedule_auto_live_check(self, initial: bool = False) -> None:
        if self._auto_live_check_after_id:
            try:
                self.root.after_cancel(self._auto_live_check_after_id)
            except Exception:
                pass
            self._auto_live_check_after_id = None
        return

    def _auto_live_check_tick(self) -> None:
        return

    def _run_manual_check_live(self) -> None:
        if not hasattr(self, "instances"):
            return
        account_type = self._selected_account_type()
        if not account_type:
            self._set_legacy_status("Select one account type before Check Login")
            self.messagebox.showwarning("Check Login", "Select one account type first. Check Login is disabled for All.")
            return
        self.instances.check_live_all_instances(show_empty_warning=True, account_type=account_type)

    def _report_status_tag(self, row: dict) -> str:
        status = str(row.get("status", "")).strip().lower()
        reason = str(row.get("reason", "")).strip().lower()
        login_text = f"{status} {reason}"
        if any(marker in status for marker in ("live", "success", "ready", "done")):
            return "live"
        if "ip mismatch" in status:
            return "ip_mismatch"
        if any(marker in status for marker in ("checkpoint", "challenge", "verify", "review")):
            return "review"
        if any(
            marker in login_text
            for marker in (
                "login required",
                "login request",
                "login cookie was not found",
                "session cookie was not found",
                "no saved cookies",
                "no cookie",
            )
        ):
            return "login_required"
        if any(marker in status for marker in ("disabled", "suspended", "locked", "failed", "die", "dead", "error")):
            return "failed"
        if any(marker in status for marker in ("checking", "queued", "running", "launch")):
            return "working"
        return ""

    def _report_row_tags(self, row: dict, tree: ttk.Treeview | None = None) -> tuple[str, ...]:
        status_tag = self._report_status_tag(row)
        if status_tag:
            return (status_tag,)
        account_type = str(row.get("country_type") or row.get("account_type") or "").strip()
        if not account_type or account_type == "-":
            return ()
        return (self._account_type_tag(account_type, tree or self.report_tree),)

    def _account_type_tag(self, account_type: str, tree: ttk.Treeview | None = None) -> str:
        clean = str(account_type or "").strip()
        tag = "type_" + "".join(ch.lower() if ch.isalnum() else "_" for ch in clean)[:40]
        score = sum((index + 1) * ord(ch) for index, ch in enumerate(clean.lower()))
        bg, fg = self.ACCOUNT_TYPE_COLORS[score % len(self.ACCOUNT_TYPE_COLORS)]
        target_tree = tree or self.report_tree
        if target_tree:
            try:
                target_tree.tag_configure(tag, background=bg, foreground=fg)
            except Exception:
                pass
        return tag

    def _show_report_context_menu(self, event) -> None:
        if not self.report_tree:
            return
        row_id = self.report_tree.identify_row(event.y)
        if not row_id:
            return
        if row_id not in self.report_tree.selection():
            self.report_tree.selection_set(row_id)
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="Open Browser Profile", command=self._open_selected_report_profile)
        menu.add_command(label="Connect Account", command=self.connect_account)
        menu.add_command(label="Refresh Login", command=self.refresh_login_selected)
        menu.add_command(label="Check Login", command=self.refresh_login_selected)
        menu.add_command(label="Clear Token", command=self.clear_selected_auth_tokens)
        if self.vars.platform_var.get() == "facebook":
            menu.add_command(label="Copy UID", command=self._copy_selected_report_uid)
        menu.add_command(label="Copy Row", command=self._copy_selected_report_row)
        menu.add_separator()
        selected_type = self._selected_account_type()
        if selected_type:
            menu.add_command(label=f"Set Country Type: {selected_type}", command=self._assign_selected_report_type)
        custom_type = self._selected_custom_account_type()
        if custom_type:
            menu.add_command(label=f"Set Account Type: {custom_type}", command=self._assign_selected_custom_account_type)
        menu.add_command(label="Set Account Type...", command=self._prompt_assign_selected_custom_account_type)
        if selected_type or custom_type:
            menu.add_separator()
        menu.add_command(label="Mark Live", command=lambda: self._mark_selected_report_status("Live"))
        menu.add_command(label="Mark Die", command=lambda: self._mark_selected_report_status("Die"))
        menu.add_command(label="Mark Processing", command=lambda: self._mark_selected_report_status("Processing"))
        menu.add_command(label="Mark Idle", command=lambda: self._mark_selected_report_status("Idle"))
        menu.add_separator()
        menu.add_command(label="Delete Account", command=self._delete_selected_report_profile)
        menu.tk_popup(event.x_root, event.y_root)

    def _selected_report_values(self) -> tuple[str, ...] | None:
        if not self.report_tree:
            return None
        selection = self.report_tree.selection()
        if not selection:
            return None
        values = self.report_tree.item(selection[0], "values")
        return tuple(str(value) for value in values)

    def _selected_report_instance_number(self) -> int | None:
        if not self.report_tree:
            return None
        selection = self.report_tree.selection()
        if not selection:
            return None
        try:
            return int(str(selection[0]))
        except Exception:
            values = self._selected_report_values()
            if not values:
                return None
            return self._instance_number_from_label(values[0].strip())

    def _selected_report_instance_numbers(self) -> list[int]:
        if not self.report_tree:
            return []
        numbers: list[int] = []
        for item in self.report_tree.selection():
            try:
                number = int(str(item))
            except Exception:
                values = self.report_tree.item(item, "values")
                if not values:
                    continue
                number = self._instance_number_from_label(str(values[0]))
            if number is not None:
                numbers.append(number)
        return numbers

    def _open_selected_report_profile(self) -> None:
        instance_number = self._selected_report_instance_number()
        if not instance_number:
            return
        platform = self.vars.platform_var.get()
        start_url = self._profile_open_url(instance_number, platform)
        threading.Thread(
            target=self._open_selected_report_profile_worker,
            args=(instance_number, platform, start_url),
            daemon=True,
        ).start()

    def _open_selected_report_profile_worker(self, instance_number: int, platform: str, start_url: str) -> None:
        self.browser.open_firefox_instance(
            instance_number=instance_number,
            login=False,
            start_url=start_url,
            sync_preview=False,
        )

    def _sync_open_profile_identity_when_ready(self, instance_number: int, driver) -> None:
        return

    def _profile_open_url(self, instance_number: int, platform: str) -> str:
        report = self.state.instance_reports.get(instance_number, {})
        account_id = str(report.get("account_id", "") or "").strip()
        if platform == "facebook" and account_id.isdigit():
            return f"https://www.facebook.com/profile.php?id={account_id}&sk=directory_personal_details"
        if platform == "tiktok":
            return "https://www.tiktok.com"
        if platform == "youtube":
            return "https://www.youtube.com"
        if platform == "instagram":
            return "https://www.instagram.com"
        if platform == "wordpress":
            site_url = str(report.get("wordpress_site_url") or report.get("site_url") or "").strip()
            return site_url or "https://wordpress.com"
        return self.PLATFORM_CONFIG.get(platform, self.PLATFORM_CONFIG["facebook"]).get("home_url", "https://www.facebook.com")

    def _copy_selected_report_uid(self) -> None:
        values = self._selected_report_values()
        if not values or "account_id" not in self.report_column_keys:
            return
        index = self.report_column_keys.index("account_id")
        if index >= len(values):
            return
        uid = "" if values[index] == "-" else values[index]
        self.root.clipboard_clear()
        self.root.clipboard_append(uid)

    def _copy_selected_report_row(self) -> None:
        values = self._selected_report_values()
        if not values:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append("|".join(values))

    def _mark_selected_report_status(self, status: str) -> None:
        instance_number = self._selected_report_instance_number()
        if not instance_number:
            return
        self.instances.mark_instance_status(instance_number, status)
        self.refresh_dashboard()

    def _delete_selected_report_profile(self) -> None:
        instance_number = self._selected_report_instance_number()
        if not instance_number:
            return
        self.instances.delete_instance(instance_number)

    def _reset_report_data(self) -> None:
        instances = getattr(self, "instances", None)
        if instances is None:
            return
        instances.reset_report_data()

    def import_accounts_file(self) -> None:
        selected_path = self.filedialog.askopenfilename(
            title="Import Accounts",
            filetypes=[
                ("Account files", "*.csv;*.json;*.txt"),
                ("CSV files", "*.csv"),
                ("JSON files", "*.json"),
                ("Text files", "*.txt"),
            ],
        )
        if not selected_path:
            return

        try:
            rows = self._load_account_import_rows(selected_path)
        except Exception as exc:
            self.messagebox.showerror("Import Failed", str(exc))
            return

        if not rows:
            self.messagebox.showwarning("Import Accounts", "No account rows found.")
            return

        imported = self.instances.import_account_rows(rows)
        self.messagebox.showinfo("Import Accounts", f"Imported {imported} local account rows.")

    def export_report_file(self) -> None:
        output_path = self.filedialog.asksaveasfilename(
            title="Export Report",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile="fbv1_report.csv",
        )
        if not output_path:
            return

        try:
            exported = self.instances.export_report_csv(output_path)
        except Exception as exc:
            self.messagebox.showerror("Export Failed", str(exc))
            return
        self.messagebox.showinfo("Export Report", f"Exported {exported} rows.")

    def _load_account_import_rows(self, file_path: str) -> list[dict[str, str]]:
        path = os.path.abspath(file_path)
        extension = os.path.splitext(path)[1].lower()
        if extension == ".json":
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, dict):
                payload = payload.get("accounts", [])
            if not isinstance(payload, list):
                raise ValueError("JSON import must be a list or contain an 'accounts' list.")
            return [item for item in payload if isinstance(item, dict)]

        if extension == ".csv":
            with open(path, "r", encoding="utf-8-sig", newline="") as handle:
                return list(csv.DictReader(handle))

        rows: list[dict[str, str]] = []
        import_fields = self._platform_import_field_keys()
        with open(path, "r", encoding="utf-8-sig") as handle:
            for line in handle:
                text = line.strip()
                if not text or text.startswith("#"):
                    continue
                parts = [part.strip() for part in text.split("|")]
                row = {field: parts[index] if index < len(parts) else "" for index, field in enumerate(import_fields)}
                row["platform"] = self.vars.platform_var.get()
                rows.append(row)
        return rows

    def _platform_import_field_keys(self) -> list[str]:
        platform = self.vars.platform_var.get()
        import_format = str(self.PLATFORM_CONFIG.get(platform, self.PLATFORM_CONFIG["facebook"]).get("import_format") or "")
        field_map = {
            "mail": "email",
            "gmail": "gmail",
            "username": "username",
            "password": "password",
            "2fa": "two_fa",
            "proxy": "proxy",
            "expectedcountry": "expected_country",
            "facebookname": "facebook_name",
            "facebookid": "facebook_id",
            "tiktokusername": "tiktok_username",
            "tiktokuserid": "tiktok_user_id",
            "channelname": "channel_name",
            "channelid": "channel_id",
            "channelurl": "channel_url",
            "instagramusername": "instagram_username",
            "instagramuserid": "instagram_user_id",
            "siteurl": "site_url",
            "applicationpasswordorapitoken": "api_token",
            "defaultcategory": "default_category",
        }
        fields: list[str] = []
        for field in import_format.split("|"):
            normalized = "".join(ch.lower() for ch in field if ch.isalnum())
            fields.append(field_map.get(normalized, normalized or "value"))
        return fields

    def _build_controls(self) -> None:
        if hasattr(self, "legacy_header"):
            self._build_legacy_controls()
            return

        self._build_sidebar_section(
            "Control Hub",
            [
                ("Generate Firefox Instances", self.instances.generate_firefox_instances, "primary"),
                ("Import Accounts", self.import_accounts_file, "secondary"),
                ("Export Report", self.export_report_file, "secondary"),
                ("Connect Account", self.connect_account, "secondary"),
                ("Refresh Login", self.refresh_login_selected, "secondary"),
                ("Check Login", self.refresh_login_selected, "secondary"),
                ("Open Platform Home", self._open_selected_report_profile, "secondary"),
                ("Reconnect Required", self.show_reconnect_required, "warning"),
                ("Clear Token", self.clear_selected_auth_tokens, "danger"),
                ("Photo/Cover Setup", self._open_photo_cover_setup_window, "secondary"),
                ("Open Folder", self.instances.open_data_folder, "neutral"),
                ("Start All", self.instances.start_all_instances, "success"),
                ("Stop All", self.instances.stop_all_instances, "warning"),
                ("Run Firefox", self.run_firefox_dialog, "success"),
                ("Delete Account", self.instances.delete_multiple_instances, "danger"),
            ],
            description="Generate, import, execute, and manage Firefox profile sessions.",
        )

        platform_section = self._create_sidebar_section(
            "System",
            description="Choose platform mode before launching a profile.",
        )
        thread_row = Frame(platform_section, bg=SIDEBAR_PANEL_BG)
        thread_row.pack(fill=X, pady=(0, 6))
        Label(thread_row, text="Threads", bg=SIDEBAR_PANEL_BG, fg=TEXT_SUBTLE, font=SMALL_FONT).pack(side=LEFT)
        thread_entry = self.style_entry(Entry(thread_row, textvariable=self.vars.thread_count_var), width=5)
        thread_entry.pack(side=RIGHT)
        for label, value in self.PLATFORMS:
            button = self.create_button(
                platform_section,
                text=label,
                command=lambda value=value: self._select_platform(value),
                kind="sidebar",
                compact=True,
                full_width=True,
            )
            button.pack(fill=X, pady=1)
            button.bind("<Double-Button-1>", lambda _event, value=value: self._open_platform_tool_popup(value), add="+")
            self.platform_buttons[value] = button

        self._refresh_action_buttons()
        self._refresh_platform_buttons()
        if hasattr(self, "theme_mode_var"):
            self._apply_runtime_theme()

    def _build_legacy_controls(self) -> None:
        for child in self.sidebar.winfo_children():
            child.destroy()

        system_row = Frame(self.sidebar, bg=SURFACE_BG)
        system_row.pack(fill=X, padx=10, pady=(10, 8))
        Label(system_row, text="System", bg=SURFACE_BG, fg=SUCCESS, font=SECTION_FONT).pack(side=LEFT)
        Label(system_row, textvariable=self.legacy_status_var, bg=SURFACE_BG, fg=TEXT_MUTED, font=SMALL_FONT).pack(side=RIGHT)

        action_row = Frame(self.sidebar, bg=SURFACE_BG)
        action_row.pack(fill=X, padx=10, pady=(4, 10))
        self.create_button(action_row, "Start Add", self.instances.start_all_instances, "secondary", True).pack(
            side=LEFT,
            fill=X,
            expand=True,
            padx=(0, 4),
        )
        self.create_button(action_row, "Stop", self.instances.stop_all_instances, "danger", True).pack(
            side=LEFT,
            fill=X,
            expand=True,
            padx=(4, 0),
        )

        thread_row = Frame(self.sidebar, bg=SURFACE_BG)
        thread_row.pack(fill=X, padx=10, pady=(0, 8))
        Label(thread_row, text="Thread", bg=SURFACE_BG, fg=TEXT_MUTED, font=SMALL_FONT).pack(side=LEFT)
        self.style_entry(Entry(thread_row, textvariable=self.vars.thread_count_var), width=5).pack(side=LEFT, padx=(8, 8))
        self._styled_checkbutton(thread_row, "Store Login Failed", tk.BooleanVar(master=self.root, value=True)).pack(side=LEFT)

        add_by = Frame(self.sidebar, bg=SURFACE_BG)
        add_by.pack(fill=X, padx=10, pady=(0, 8))
        Label(add_by, text="Add By", bg=SURFACE_BG, fg=TEXT_MUTED, font=SMALL_FONT).pack(side=LEFT)
        add_by_combo = ttk.Combobox(
            add_by,
            textvariable=self.legacy_add_by_var,
            values=("Account", "OAuth/API", "Profile"),
            state="readonly",
            width=16,
        )
        add_by_combo.pack(side=RIGHT)
        add_by_combo.bind("<<ComboboxSelected>>", lambda _event: self._set_legacy_status(f"Add mode: {self.legacy_add_by_var.get()}"))

        Label(
            self.sidebar,
            text="Format Login: use platform import format; no passwords, 2FA, or cookies",
            bg=SURFACE_BG,
            fg=TEXT_MUTED,
            font=SMALL_FONT,
            wraplength=220,
        ).pack(anchor="w", padx=10, pady=(0, 6))
        self._styled_checkbutton(self.sidebar, "Auto Backup Acc", tk.BooleanVar(master=self.root, value=True)).pack(
            anchor="w",
            padx=8,
        )

        account_box = tk.Listbox(
            self.sidebar,
            bg=INPUT_BG,
            fg=TEXT_PRIMARY,
            selectbackground=ACCENT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            height=8,
            font=SMALL_FONT,
        )
        account_box.pack(fill=X, padx=10, pady=(8, 10))
        self.legacy_account_list = account_box

        account_buttons = Frame(self.sidebar, bg=SURFACE_BG)
        account_buttons.pack(fill=X, padx=10, pady=(0, 10))
        self.create_button(
            account_buttons,
            "Generate",
            self.instances.generate_firefox_instances,
            "primary",
            True,
        ).pack(side=LEFT, fill=X, expand=True, padx=(0, 3))
        self.create_button(
            account_buttons,
            "Import",
            self.import_accounts_file,
            "secondary",
            True,
        ).pack(side=LEFT, fill=X, expand=True, padx=3)
        self.create_button(
            account_buttons,
            "Delete",
            self.instances.delete_multiple_instances,
            "danger",
            True,
        ).pack(side=LEFT, fill=X, expand=True, padx=(3, 0))

        self._create_legacy_button_group(
            "Platform",
            [(label, lambda value=value: self._select_platform(value), "sidebar", value) for label, value in self.PLATFORMS],
            target="platform",
        )

        bottom = Frame(self.sidebar, bg=SURFACE_BG)
        bottom.pack(fill=X, side="bottom", padx=10, pady=10)
        self.create_button(bottom, "Key Pro", self._show_key_pro_status, "neutral", True).pack(
            side=LEFT,
            fill=X,
            expand=True,
            padx=(0, 4),
        )
        self.create_button(bottom, "Update", self._refresh_legacy_views, "primary", True).pack(
            side=LEFT,
            fill=X,
            expand=True,
            padx=(4, 0),
        )

        self._refresh_action_buttons()
        self._refresh_platform_buttons()

    def _create_legacy_section(self, title: str) -> Frame:
        section = Frame(self.sidebar, bg=SURFACE_BG, highlightbackground=BORDER, highlightthickness=1, bd=0)
        section.pack(fill=X, padx=8, pady=(0, 8))
        Label(section, text=title, bg=SURFACE_BG, fg=TEXT_PRIMARY, font=SECTION_FONT).pack(anchor="w", padx=8, pady=(6, 2))
        inner = Frame(section, bg=SURFACE_BG)
        inner.pack(fill=X, padx=6, pady=(0, 6))
        return inner

    def _create_legacy_button_group(self, title: str, buttons: list[tuple[str, object, str, str]], target: str) -> None:
        section = self._create_legacy_section(title)
        for label, command, kind, value in buttons:
            button = self.create_button(section, label, command, kind=kind, compact=True, full_width=True)
            button.pack(fill=X, pady=1)
            if target == "platform":
                button.bind("<Double-Button-1>", lambda _event, value=value: self._open_platform_tool_popup(value), add="+")
                self.platform_buttons[value] = button

    def _set_legacy_status(self, text: str) -> None:
        if hasattr(self, "legacy_status_var"):
            self.legacy_status_var.set(text)

    def _selected_account_type(self) -> str:
        if not hasattr(self, "legacy_store_var"):
            return ""
        value = self.legacy_store_var.get().strip()
        if value.lower() in {"", "all", "store"}:
            return ""
        return value

    def _selected_custom_account_type(self) -> str:
        if not hasattr(self, "account_group_var"):
            return ""
        value = self.account_group_var.get().strip()
        if value.lower() in {"", "all", "store"}:
            return ""
        return value

    def _sync_legacy_account_types_from_reports(self) -> None:
        values = {"All"}
        created = {value for value in getattr(self, "legacy_stores", ["All"]) if value and value != "All"}
        if hasattr(self, "instances"):
            for row in self.instances.get_report_rows():
                country_type = str(row.get("country_type", "") or row.get("account_type", "") or "").strip()
                if country_type and country_type != "-":
                    values.add(country_type)
                    continue
                country = str(row.get("country", "") or "").strip()
                if country and country != "-":
                    values.add(country)
        current = self.legacy_store_var.get().strip() or "All"
        self.legacy_stores = ["All"] + sorted((values | created) - {"All"})
        if current in self.legacy_stores:
            self.legacy_store_var.set(current)
        else:
            self.legacy_store_var.set("All")
        self._refresh_legacy_store_combo()
        self._sync_custom_account_types_from_reports()
        self._refresh_check_live_buttons()

    def _restore_saved_account_type_lists(self) -> None:
        country_types = {
            str(value).strip()
            for value in getattr(self.instances, "saved_country_types", [])
            if str(value or "").strip()
        }
        custom_types = {
            str(value).strip()
            for value in getattr(self.instances, "saved_custom_account_types", [])
            if str(value or "").strip()
        }
        if country_types:
            self.legacy_stores = ["All"] + sorted(country_types - {"All"})
            if self.legacy_store_var.get() not in self.legacy_stores:
                self.legacy_store_var.set("All")
        if custom_types:
            self.account_groups = ["All"] + sorted(custom_types - {"All"})
            if self.account_group_var.get() not in self.account_groups:
                self.account_group_var.set("All")

    def _sync_custom_account_types_from_reports(self) -> None:
        values = {"All"}
        if hasattr(self, "instances"):
            for row in self.instances.get_report_rows():
                value = str(row.get("account_type", "") or "").strip()
                if value and value != "-":
                    values.add(value)
        current = self.account_group_var.get().strip() or "All"
        created = {value for value in getattr(self, "account_groups", ["All"]) if value and value != "All"}
        self.account_groups = ["All"] + sorted((values | created) - {"All"})
        if current in self.account_groups:
            self.account_group_var.set(current)
        else:
            self.account_group_var.set("All")
        self._refresh_account_group_combo()

    def _select_account_type(self) -> None:
        selected = self._selected_account_type()
        self.report_page = 1
        self._set_legacy_status(f"Country type: {selected or 'All'}")
        self._refresh_check_live_buttons()
        self.refresh_report_table()
        self._refresh_legacy_account_list()
        self.refresh_dashboard()
        for platform in list(self.platform_tool_trees):
            self._refresh_platform_tool_accounts(platform)
        if hasattr(self, "_schedule_auto_live_check"):
            self._schedule_auto_live_check(initial=True)

    def _select_custom_account_type(self) -> None:
        selected = self._selected_custom_account_type()
        self.report_page = 1
        self._set_legacy_status(f"Account type: {selected or 'All'}")
        self.refresh_report_table()
        self._refresh_legacy_account_list()
        self.refresh_dashboard()
        for platform in list(self.platform_tool_trees):
            self._refresh_platform_tool_accounts(platform)

    def _refresh_check_live_buttons(self) -> None:
        enabled = bool(self._selected_account_type())
        for button in getattr(self, "check_live_buttons", []):
            try:
                if enabled:
                    button.config(state="normal", cursor="hand2")
                    if not button.winfo_manager():
                        button.pack(**getattr(button, "_check_live_pack_info", {"side": LEFT}))
                else:
                    if button.winfo_manager():
                        button.pack_forget()
            except Exception:
                continue

    def _assign_selected_report_type(self) -> None:
        instance_numbers = self._selected_report_instance_numbers()
        account_type = self._selected_account_type()
        if not instance_numbers:
            self._set_legacy_status("Select account rows first")
            return
        if not account_type:
            self._set_legacy_status("Select an account type first")
            return
        for instance_number in instance_numbers:
            self.instances.set_account_type(instance_number, account_type, save_data=False, refresh_table=False)
        self.instances.save_instance_data()
        self.instances.sync_local_profiles_to_backend_async(instance_numbers)
        self._sync_legacy_account_types_from_reports()
        self.refresh_report_table()
        self._set_legacy_status(f"{len(instance_numbers)} account(s) country: {account_type}")

    def _assign_selected_custom_account_type(self) -> None:
        account_type = self._selected_custom_account_type()
        if not account_type:
            self._set_legacy_status("Select an account type first")
            return
        self._assign_custom_account_type_to_selection(account_type)

    def _prompt_assign_selected_custom_account_type(self) -> None:
        available_types = [
            str(value).strip()
            for value in self.account_groups
            if str(value or "").strip() and str(value).strip().lower() != "all"
        ]
        if not available_types:
            self._set_legacy_status("Add an account type first")
            return

        selected_var = tk.StringVar(master=self.root, value=available_types[0])
        type_window = self.create_modal("Set Account Type", "460x340")
        type_window.minsize(460, 320)
        body = self.create_modal_card(type_window, "Set Account Type", "Choose an existing account type.")
        Label(body, text="Account Type", bg=SURFACE_BG, fg=TEXT_MUTED, font=SMALL_FONT).pack(anchor="w")
        type_menu = ttk.Combobox(
            body,
            textvariable=selected_var,
            values=tuple(available_types),
            state="readonly",
            width=28,
        )
        type_menu.pack(fill=X, pady=(8, 22), ipady=3)
        type_menu.current(0)
        type_menu.focus_set()

        footer = Frame(body, bg=SURFACE_BG)
        footer.pack(fill=X, pady=(4, 0))

        def apply_type() -> None:
            account_type = selected_var.get().strip()
            if account_type:
                self._assign_custom_account_type_to_selection(account_type)
            type_window.destroy()

        self.create_button(footer, "Apply", apply_type, kind="primary", compact=True).pack(side=LEFT)
        self.create_button(footer, "Close", type_window.destroy, kind="neutral", compact=True).pack(side=LEFT, padx=(8, 0))
        type_window.bind("<Return>", lambda _event: apply_type())

    def _assign_custom_account_type_to_selection(self, account_type: str) -> None:
        instance_numbers = self._selected_report_instance_numbers()
        clean_type = str(account_type or "").strip()
        if not instance_numbers:
            self._set_legacy_status("Select account rows first")
            return
        if not clean_type or clean_type.lower() in {"all", "store"}:
            self._set_legacy_status("Account type name required")
            return
        for instance_number in instance_numbers:
            self.instances.set_custom_account_type(instance_number, clean_type, save_data=False, refresh_table=False)
        self.instances.save_instance_data()
        self.instances.sync_local_profiles_to_backend_async(instance_numbers)
        if clean_type not in self.account_groups:
            self.account_groups.append(clean_type)
        self.account_group_var.set(clean_type)
        self._sync_custom_account_types_from_reports()
        self.report_page = 1
        self.refresh_report_table()
        self._set_legacy_status(f"{len(instance_numbers)} account(s) type: {clean_type}")

    def _create_legacy_store(self) -> None:
        name = self.legacy_store_name_var.get().strip()
        if not name:
            self._set_legacy_status("Country type name required")
            return
        if name not in self.legacy_stores:
            self.legacy_stores.append(name)
        self.legacy_store_var.set(name)
        self.legacy_store_name_var.set("")
        self._refresh_legacy_store_combo()
        self._select_account_type()
        self.instances.save_instance_data()
        self._set_legacy_status(f"Country type created: {name}")

    def _remove_legacy_store(self) -> None:
        name = self.legacy_store_var.get().strip()
        if not name or name == "All":
            self._set_legacy_status("Select a country type")
            return
        self.legacy_stores = [store for store in self.legacy_stores if store != name]
        if "All" not in self.legacy_stores:
            self.legacy_stores.insert(0, "All")
        self.legacy_store_var.set(self.legacy_stores[0])
        self._refresh_legacy_store_combo()
        self._select_account_type()
        self.instances.save_instance_data()
        self._set_legacy_status(f"Country type removed: {name}")

    def _create_custom_account_type(self) -> None:
        name = self.account_group_name_var.get().strip()
        if not name:
            self._set_legacy_status("Account type name required")
            return
        if name not in self.account_groups:
            self.account_groups.append(name)
        self.account_group_var.set(name)
        self.account_group_name_var.set("")
        self._refresh_account_group_combo()
        self._select_custom_account_type()
        self.instances.save_instance_data()
        self._set_legacy_status(f"Account type created: {name}")

    def _remove_custom_account_type(self) -> None:
        name = self.account_group_var.get().strip()
        if not name or name == "All":
            self._set_legacy_status("Select an account type")
            return
        self.account_groups = [group for group in self.account_groups if group != name]
        if "All" not in self.account_groups:
            self.account_groups.insert(0, "All")
        self.account_group_var.set(self.account_groups[0])
        self._refresh_account_group_combo()
        self._select_custom_account_type()
        self.instances.save_instance_data()
        self._set_legacy_status(f"Account type removed: {name}")

    def _refresh_legacy_store_combo(self) -> None:
        if self.legacy_store_combo:
            self.legacy_store_combo.configure(values=tuple(self.legacy_stores))
        for combo in list(getattr(self, "platform_tool_country_type_menus", {}).values()):
            try:
                combo.configure(values=tuple(self.legacy_stores))
            except Exception:
                continue

    def _refresh_account_group_combo(self) -> None:
        if self.account_group_combo:
            self.account_group_combo.configure(values=tuple(self.account_groups))
        for combo in list(getattr(self, "platform_tool_account_type_menus", {}).values()):
            try:
                combo.configure(values=tuple(self.account_groups))
            except Exception:
                continue

    def _refresh_legacy_account_list(self) -> None:
        account_list = getattr(self, "legacy_account_list", None)
        if account_list is None:
            return
        account_list.delete(0, tk.END)
        query = self.legacy_find_var.get().strip().lower() if hasattr(self, "legacy_find_var") else ""
        country_type = self._selected_account_type()
        custom_type = self._selected_custom_account_type()
        for instance_number in self.instances.active_instance_numbers():
            if country_type and not self.instances.instance_matches_account_type(instance_number, country_type):
                continue
            report = self.state.instance_reports.get(instance_number, {})
            if custom_type and str(report.get("custom_account_type") or "").strip().lower() != custom_type.lower():
                continue
            name = self.state.instance_names.get(instance_number) or self.state.profile_names.get(instance_number)
            local_label = self.instances._local_account_label(instance_number, report)
            label = f"{local_label} | Firefox {instance_number}"
            if name:
                label = f"{label} | {name}"
            row_type = str(report.get("account_type") or report.get("country") or "").strip()
            if row_type and row_type not in label:
                label = f"{label} | {row_type}"
            custom_row_type = str(report.get("custom_account_type") or "").strip()
            if custom_row_type:
                label = f"{label} | {custom_row_type}"
            if query and query not in label.lower():
                continue
            account_list.insert(tk.END, label)

    def _refresh_legacy_views(self) -> None:
        self.refresh_report_table()
        self._refresh_legacy_account_list()
        for platform in list(self.platform_tool_trees):
            self._refresh_platform_tool_accounts(platform)
        self._set_legacy_status("Updated")

    def _show_key_pro_status(self) -> None:
        self.messagebox.showinfo("Key Pro", "License/key management is not required for this local build.")
        self._set_legacy_status("Key Pro checked")

    def _platform_actions(self) -> list[tuple[str, str]]:
        platform = self.vars.platform_var.get()
        return self.ACTIONS_BY_PLATFORM.get(platform, self.ACTIONS_BY_PLATFORM["facebook"])

    def _render_action_buttons(self) -> None:
        if not self.action_section:
            return
        for child in self.action_section.winfo_children():
            child.destroy()
        self.action_buttons.clear()

        valid_actions = self._platform_actions()
        valid_values = {value for _label, value in valid_actions}
        if self.vars.action_var.get() not in valid_values:
            self.vars.action_var.set(valid_actions[0][1])

        for label, value in valid_actions:
            button = self.create_button(
                self.action_section,
                text=label,
                command=lambda value=value: self._select_action(value),
                kind="sidebar",
                compact=True,
                full_width=True,
            )
            button.pack(fill=X, pady=1)
            self.action_buttons[value] = button

    def _build_sidebar_section(self, title: str, buttons: list[tuple[str, object, str]], description: str = "") -> None:
        section = self._create_sidebar_section(title, description=description)
        for label, command, kind in buttons:
            button = self.create_button(
                section,
                text=label,
                command=command,
                kind=kind,
                compact=True,
                full_width=True,
            )
            button.pack(fill=X, pady=1)
            self.control_buttons[label] = button

    def _create_sidebar_section(self, title: str, description: str = "") -> Frame:
        section = Frame(self.sidebar, bg=SIDEBAR_PANEL_BG, highlightbackground=BORDER, highlightthickness=1, bd=0)
        section.pack(fill=X, padx=6, pady=(6, 0))
        Label(section, text=title, bg=SIDEBAR_PANEL_BG, fg=TEXT_ON_DARK, font=SECTION_FONT).pack(anchor="w", padx=8, pady=(6, 0))
        if description.strip():
            Label(
                section,
                text=description,
                bg=SIDEBAR_PANEL_BG,
                fg=TEXT_SUBTLE,
                font=SMALL_FONT,
                justify="left",
                wraplength=228,
            ).pack(anchor="w", padx=8, pady=(2, 4))
        inner = Frame(section, bg=SIDEBAR_PANEL_BG)
        inner.pack(fill=X, padx=6, pady=(2, 4))
        return inner

    def create_button(
        self,
        parent: Frame,
        text: str,
        command,
        kind: str = "secondary",
        compact: bool = False,
        full_width: bool = False,
        **overrides,
    ) -> Button:
        style = dict(BUTTON_STYLES[kind])
        style.update(
            {
                "text": text,
                "command": command,
                "relief": "flat",
                "bd": 0,
                "cursor": "hand2",
                "font": BUTTON_FONT if not compact else SMALL_FONT,
                "padx": 12 if not compact else 6,
                "pady": 6 if not compact else 2,
                "highlightthickness": 1 if (kind in {"secondary", "neutral", "sidebar"} and not compact) else 0,
                "highlightbackground": BORDER if kind in {"secondary", "neutral", "sidebar"} else style.get("bg"),
                "wraplength": 0,
            }
        )
        style.update(overrides)
        button = Button(parent, **style)
        button._theme_kind = kind
        self._attach_button_hover(button)
        return button

    def _attach_button_hover(self, button: Button) -> None:
        def on_enter(_event) -> None:
            if str(button.cget("state")) == "disabled":
                return
            button._normal_bg = button.cget("bg")
            button._normal_fg = button.cget("fg")
            button.config(
                bg=button.cget("activebackground"),
                fg=button.cget("activeforeground"),
            )

        def on_leave(_event) -> None:
            if str(button.cget("state")) == "disabled":
                return
            normal_bg = getattr(button, "_normal_bg", button.cget("bg"))
            normal_fg = getattr(button, "_normal_fg", button.cget("fg"))
            button.config(bg=normal_bg, fg=normal_fg)

        button.bind("<Enter>", on_enter, add="+")
        button.bind("<Leave>", on_leave, add="+")

    def _theme_palette(self) -> dict[str, str]:
        mode = self.theme_mode_var.get() if hasattr(self, "theme_mode_var") else "dark"
        return self.THEME_PALETTES.get(mode, self.THEME_PALETTES["dark"])

    def _toggle_theme(self) -> None:
        next_mode = "light" if self.theme_mode_var.get() == "dark" else "dark"
        self.theme_mode_var.set(next_mode)
        self._apply_runtime_theme()

    def _apply_runtime_theme(self, root_widget=None) -> None:
        palette = self._theme_palette()
        root_widget = root_widget or self.root
        if root_widget == self.root:
            self.root.configure(bg=palette["app"])
        self._configure_ttk_theme()
        self._theme_widget_tree(root_widget, palette)
        if self.theme_toggle_button:
            self.theme_toggle_button.config(text="Dark Theme" if self.theme_mode_var.get() == "light" else "White Theme")

    def _configure_ttk_theme(self) -> None:
        palette = self._theme_palette()
        style = ttk.Style(self.root)
        style.configure(
            "Report.Treeview",
            background=palette["surface"],
            fieldbackground=palette["surface"],
            foreground=palette["text"],
            bordercolor=palette["border"],
            rowheight=24,
            relief="flat",
        )
        style.configure(
            "Report.Treeview.Heading",
            background=palette["button_bg"],
            foreground=palette["text"],
            bordercolor=palette["border"],
            relief="flat",
            font=SECTION_FONT,
        )
        style.map(
            "Report.Treeview",
            background=[("selected", "#05CBE5")],
            foreground=[("selected", "#010C03")],
        )
        style.configure(
            "TCombobox",
            fieldbackground=palette["input_bg"],
            background=palette["input_bg"],
            foreground=palette["input_fg"],
            arrowcolor=palette["text"],
        )

    def _theme_widget_tree(self, widget, palette: dict[str, str]) -> None:
        self._theme_single_widget(widget, palette)
        for child in widget.winfo_children():
            self._theme_widget_tree(child, palette)

    def _theme_single_widget(self, widget, palette: dict[str, str]) -> None:
        colored_backgrounds = {ACCENT, SUCCESS, DANGER}
        try:
            widget_class = widget.winfo_class()
        except Exception:
            return

        if widget_class in {"Frame", "Toplevel"}:
            bg = palette["app"] if widget in {self.root, getattr(self, "main_frame", None)} else palette["surface"]
            if widget in {getattr(self, "table_panel", None), getattr(self, "profiles_panel", None), getattr(self, "monitor_panel", None)}:
                bg = palette["alt"]
            widget.configure(bg=bg, highlightbackground=palette["border"])
            return

        if widget_class == "Canvas":
            widget.configure(bg=palette["alt"], highlightbackground=palette["border"])
            return

        if widget_class == "Label":
            try:
                current_bg = str(widget.cget("bg"))
            except Exception:
                current_bg = ""
            if current_bg in colored_backgrounds:
                widget.configure(fg=TEXT_ON_DARK)
                return
            parent_bg = palette["surface"]
            try:
                parent_bg = widget.master.cget("bg")
            except Exception:
                pass
            fg = palette["muted"] if str(widget.cget("fg")) in {TEXT_MUTED, TEXT_SUBTLE, palette["muted"], palette["subtle"]} else palette["text"]
            widget.configure(bg=parent_bg, fg=fg, highlightbackground=palette["border"])
            return

        if widget_class == "Button":
            self._theme_button(widget, palette)
            return

        if widget_class == "Entry":
            widget.configure(
                bg=palette["input_bg"],
                fg=palette["input_fg"],
                insertbackground=palette["input_fg"],
                highlightbackground=palette["border"],
            )
            return

        if widget_class == "Listbox":
            widget.configure(
                bg=palette["input_bg"],
                fg=palette["input_fg"],
                selectbackground=ACCENT,
                selectforeground=TEXT_ON_DARK,
                highlightbackground=palette["border"],
            )
            return

        if widget_class == "Text":
            widget.configure(
                bg=palette["input_bg"],
                fg=palette["input_fg"],
                insertbackground=palette["input_fg"],
                highlightbackground=palette["border"],
            )

    def _theme_button(self, button: Button, palette: dict[str, str]) -> None:
        kind = getattr(button, "_theme_kind", "secondary")
        if kind == "primary":
            bg, fg, hover = ACCENT, TEXT_ON_DARK, ACCENT_HOVER
        elif kind == "success":
            bg, fg, hover = SUCCESS, TEXT_ON_DARK, "#58791c"
        elif kind == "danger":
            bg, fg, hover = DANGER, TEXT_ON_DARK, "#d93f1a"
        elif kind == "warning":
            bg, fg, hover = "#e0a51b", TEXT_ON_DARK, "#bd8a15"
        else:
            bg, fg, hover = palette["button_bg"], palette["text"], palette["button_hover"]
        button.configure(
            bg=bg,
            fg=fg,
            activebackground=hover,
            activeforeground=fg,
            highlightbackground=palette["border"],
        )

    def style_entry(self, entry: Entry, width: int | None = None) -> Entry:
        palette = self._theme_palette()
        entry.configure(
            relief="flat",
            bd=0,
            bg=palette["input_bg"],
            fg=palette["input_fg"],
            insertbackground=palette["input_fg"],
            highlightthickness=1,
            highlightbackground=palette["border"],
            highlightcolor=ACCENT,
            font=BODY_FONT,
        )
        if width is not None:
            entry.configure(width=width)
        return entry

    def create_modal(self, title: str, geometry: str = "620x420", modal: bool = True) -> Toplevel:
        window = Toplevel(self.root)
        window.title(title)
        window.configure(bg=APP_BG)
        window.transient(self.root)
        window.resizable(False, False)
        self._center_modal(window, geometry)
        window.focus_set()
        if modal:
            window.grab_set()
        window.after(20, lambda window=window: self._apply_runtime_theme(window))
        return window

    def _center_modal(self, window: Toplevel, geometry: str) -> None:
        try:
            width_str, height_str = geometry.split("x", maxsplit=1)
            width = int(width_str)
            height = int(height_str)
        except Exception:
            window.geometry(geometry)
            return

        self.root.update_idletasks()
        x = self.root.winfo_rootx() + max(20, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(20, (self.root.winfo_height() - height) // 2)
        window.geometry(f"{width}x{height}+{x}+{y}")

    def create_modal_card(self, window: Toplevel, title: str, subtitle: str) -> Frame:
        card = Frame(window, bg=SURFACE_BG, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill=BOTH, expand=True, padx=18, pady=18)
        Label(card, text=title, bg=SURFACE_BG, fg=TEXT_PRIMARY, font=TITLE_FONT).pack(anchor="w", padx=18, pady=(18, 0))
        Label(card, text=subtitle, bg=SURFACE_BG, fg=TEXT_MUTED, font=BODY_FONT).pack(anchor="w", padx=18, pady=(4, 16))
        body = Frame(card, bg=SURFACE_BG)
        body.pack(fill=BOTH, expand=True, padx=18, pady=(0, 18))
        return body

    def refresh_dashboard(self) -> None:
        selected_type = self._selected_account_type() if hasattr(self, "_selected_account_type") else ""
        selected_custom_type = self._selected_custom_account_type() if hasattr(self, "_selected_custom_account_type") else ""
        if selected_type and hasattr(self, "instances"):
            active_count = len(self.instances.active_instance_numbers_for_type(selected_type))
        else:
            active_count = sum(1 for _button, frame in self.state.firefox_buttons if frame is not None)
        deleted_count = len(self.state.deleted_instances)
        action_value = self.vars.action_var.get().replace("_", " ").title()
        report_rows = self.instances.get_report_rows() if hasattr(self, "instances") else []
        if selected_type and hasattr(self, "instances"):
            report_rows = [row for row in report_rows if self.instances.report_matches_account_type(row, selected_type)]
        if selected_custom_type:
            report_rows = [
                row
                for row in report_rows
                if str(row.get("account_type") or "").strip().lower() == selected_custom_type.lower()
            ]
            active_count = len(report_rows)
        total_count = len(report_rows)
        live_count = 0
        die_count = 0
        no_login_count = 0
        processing_count = 0
        for row in report_rows:
            status = str(row.get("status", "")).strip().lower()
            reason = str(row.get("reason", "")).strip().lower()
            status_reason = f"{status} {reason}"
            if status in {"done", "ready", "success", "cache cleared", "live"} or "running" in status:
                live_count += 1
            elif any(
                marker in status_reason
                for marker in (
                    "login required",
                    "login request",
                    "login cookie was not found",
                    "session cookie was not found",
                    "no saved cookies",
                    "no cookie",
                    "returned a login page",
                    "logged out",
                    "not logged in",
                    "not signed in",
                )
            ):
                no_login_count += 1
            elif (
                "checkpoint" in status
                or "challenge" in status
                or "verify" in status
                or "disabled" in status
                or "suspended" in status
                or "locked" in status
                or "die" in status
                or "dead" in status
            ):
                die_count += 1
            elif any(marker in status for marker in ("queue", "launch", "wait", "process")):
                processing_count += 1

        if self.total_count_label:
            self.total_count_label.config(text=str(total_count))
        if self.live_count_label:
            self.live_count_label.config(text=str(live_count))
        if self.die_count_label:
            self.die_count_label.config(text=str(die_count))
        if getattr(self, "no_login_count_label", None):
            self.no_login_count_label.config(text=str(no_login_count))
        if self.processing_count_label:
            self.processing_count_label.config(text=str(processing_count))
        if self.active_count_label:
            self.active_count_label.config(text=str(active_count))
        if self.deleted_count_label:
            self.deleted_count_label.config(text=str(deleted_count))
        if self.current_action_label:
            self.current_action_label.config(text=f"{self._platform_label().upper()} | {action_value.upper()}")
        self._refresh_workspace_header()
        self._refresh_image_toggle_button()
        self._refresh_workspace_tab_buttons()
        self._refresh_browser_mode_buttons()
        if hasattr(self, "instances"):
            self.instances.refresh_platform_cards()
        self.refresh_report_table()
        if hasattr(self, "_refresh_legacy_account_list"):
            self._refresh_legacy_account_list()

        self._refresh_action_buttons()
        self._refresh_platform_buttons()

    def _platform_label(self) -> str:
        current = self.vars.platform_var.get()
        return platform_label(current)

    def _select_platform(self, value: str) -> None:
        known_values = {platform_value for _label, platform_value in self.PLATFORMS}
        clean_value = value if value in known_values else "facebook"
        if hasattr(self, "instances"):
            self.instances.switch_platform(clean_value)
        else:
            self.vars.platform_var.set(clean_value)
        valid_actions = self.ACTIONS_BY_PLATFORM.get(clean_value, self.ACTIONS_BY_PLATFORM["facebook"])
        valid_action_values = {action_value for _label, action_value in valid_actions}
        if self.vars.action_var.get() not in valid_action_values:
            self.vars.action_var.set(valid_actions[0][1])
        self._render_action_buttons()
        self._sync_legacy_account_types_from_reports()
        if hasattr(self, "instances"):
            self.instances.refresh_platform_cards()
        self.refresh_dashboard()
        if hasattr(self, "_schedule_auto_live_check"):
            self._schedule_auto_live_check(initial=True)

    def set_platform(self, platform_name: str) -> None:
        self._select_platform(platform_name)

    def _open_platform_tool_popup(self, value: str | None = None) -> None:
        if value:
            self._select_platform(value)
        self._open_platform_publish_window()

    def _refresh_platform_buttons(self) -> None:
        current = self.vars.platform_var.get()
        for value, button in self.platform_buttons.items():
            if value == current:
                button.config(bg=ACCENT, fg=TEXT_ON_DARK, activebackground=ACCENT_HOVER, activeforeground=TEXT_ON_DARK)
            else:
                button.config(
                    bg=SIDEBAR_PANEL_BG,
                    fg=TEXT_PRIMARY,
                    activebackground=NEUTRAL_HOVER,
                    activeforeground=TEXT_PRIMARY,
                )
        photo_cover_button = self.control_buttons.get("Photo/Cover Setup")
        if photo_cover_button:
            if current == "facebook":
                photo_cover_button.config(text="Photo/Cover Setup", state="normal")
            else:
                photo_cover_button.config(text="FB Photo/Cover Only", state="disabled")

    def _set_browser_mode(self, mode: str) -> None:
        clean_mode = "phone" if mode == "phone" else "pc"
        self.vars.browser_mode_var.set(clean_mode)
        if hasattr(self, "instances"):
            self.instances.save_instance_data()
        self._refresh_browser_mode_buttons()

    def _refresh_browser_mode_buttons(self) -> None:
        current = self.vars.browser_mode_var.get()
        for mode, button in (("pc", self.pc_mode_button), ("phone", self.phone_mode_button)):
            if not button:
                continue
            if current == mode:
                button.config(bg=ACCENT, fg=TEXT_ON_DARK, activebackground=ACCENT_HOVER, activeforeground=TEXT_ON_DARK)
            else:
                button.config(
                    bg=SIDEBAR_PANEL_BG,
                    fg=TEXT_PRIMARY,
                    activebackground=SECONDARY,
                    activeforeground=TEXT_PRIMARY,
                )

    def toggle_media_previews(self) -> None:
        self.state.show_media_previews = not self.state.show_media_previews
        self._refresh_image_toggle_button()
        self.instances.reload_all_media()

    def _refresh_image_toggle_button(self) -> None:
        if not self.image_toggle_button:
            return
        if self.vars.platform_var.get() != "facebook":
            self.image_toggle_button.config(text="FB Images Only", state="disabled")
            return
        self.image_toggle_button.config(state="normal")
        if self.state.show_media_previews:
            self.image_toggle_button.config(text="Hide Images")
        else:
            self.image_toggle_button.config(text="Show Images")

    def _refresh_workspace_header(self) -> None:
        if not self.workspace_title_label or not self.workspace_subtitle_label:
            return
        platform_label = self._platform_label()
        platform = self.vars.platform_var.get()
        config = self.PLATFORM_CONFIG.get(platform, self.PLATFORM_CONFIG["facebook"])
        workspace_title = str(config.get("title") or f"{platform_label} Workspace")
        action_value = self.vars.action_var.get().replace("_", " ").title()
        if self.workspace_tab == "table":
            self.workspace_title_label.config(text=workspace_title)
            self.workspace_subtitle_label.config(
                text=f"Review {platform_label} runs, outcomes, and last action details.",
            )
        elif self.workspace_tab == "monitor":
            self.workspace_title_label.config(text="Backend Monitor")
            self.workspace_subtitle_label.config(
                text="Watch backend profile health, run checker jobs, and control the queue.",
            )
        else:
            self.workspace_title_label.config(text=f"{workspace_title} | {action_value}")
            if platform == "facebook":
                subtitle = "Launch, rename, delete, and review Facebook profile sessions below."
            else:
                subtitle = f"Launch Firefox profiles directly into {platform_label} pages without Facebook media previews."
            self.workspace_subtitle_label.config(text=subtitle)
        if self.account_workspace_label:
            self.account_workspace_label.config(text=workspace_title)
        if self.account_workspace_hint_label:
            if platform == "facebook":
                hint = "Each card shows Facebook account media preview and quick operator actions."
            else:
                hint = f"Cards use {platform_label} actions; Facebook avatar and cover fields are hidden."
            self.account_workspace_hint_label.config(text=hint)
        if self.import_format_label:
            self.import_format_label.config(text=f"Format Login: {config.get('import_format', '')}")

    def _schedule_backend_refresh(self) -> None:
        if self._backend_refresh_after_id:
            try:
                self.root.after_cancel(self._backend_refresh_after_id)
            except Exception:
                pass
        self._backend_refresh_after_id = self.root.after(5000, self._backend_refresh_tick)

    def _backend_refresh_tick(self) -> None:
        self.refresh_backend_monitor_async()
        self._schedule_backend_refresh()

    def _schedule_auto_backup(self) -> None:
        if self._backup_after_id:
            try:
                self.root.after_cancel(self._backup_after_id)
            except Exception:
                pass
        self._backup_after_id = self.root.after(600000, self._auto_backup_tick)

    def _auto_backup_tick(self) -> None:
        if hasattr(self, "instances"):
            try:
                self.instances.backup_instance_data()
            except Exception:
                pass
        self._schedule_auto_backup()

    def refresh_backend_monitor_async(self) -> None:
        thread = threading.Thread(target=self._load_backend_monitor_data, daemon=True)
        thread.start()

    def _load_backend_monitor_data(self) -> None:
        try:
            health = self._backend_request_json("/api/health")
            profiles = self._backend_request_json("/api/profiles")
            jobs = self._backend_request_json("/api/jobs")
            self.root.after(
                0,
                lambda: self._apply_backend_monitor_data(health, profiles, jobs),
            )
        except Exception as error:
            self.root.after(0, lambda: self._set_backend_status(f"Backend error: {error}", kind="error"))

    def _backend_request_json(self, path: str, method: str = "GET", payload: dict | None = None):
        base_url = self.backend_base_url_var.get().strip().rstrip("/")
        if not base_url:
            raise RuntimeError("Backend URL is empty.")
        request_data = None
        headers: dict[str, str] = {"Accept": "application/json"}
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
            body = error.read().decode("utf-8", errors="ignore")
            raise RuntimeError(body or f"HTTP {error.code}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(str(error.reason)) from error
        return json.loads(body) if body else {}

    def _apply_backend_monitor_data(self, health: dict, profiles: list[dict], jobs: list[dict]) -> None:
        self._set_backend_status(
            f"{health.get('app', 'Backend')} online | env={health.get('environment', 'unknown')}",
            kind="ok",
        )
        self._refresh_backend_tree(profiles)
        if self.monitor_profile_count_label:
            self.monitor_profile_count_label.config(text=str(len(profiles)))
        if self.monitor_live_count_label:
            self.monitor_live_count_label.config(text=str(sum(1 for profile in profiles if profile.get("health_status") == "live")))
        if self.monitor_review_count_label:
            self.monitor_review_count_label.config(text=str(sum(1 for profile in profiles if profile.get("health_status") == "review")))
        if self.monitor_failed_count_label:
            self.monitor_failed_count_label.config(text=str(sum(1 for profile in profiles if profile.get("health_status") == "failed")))

    def _refresh_backend_tree(self, profiles: list[dict]) -> None:
        if not self.monitor_tree:
            return
        for item in self.monitor_tree.get_children():
            self.monitor_tree.delete(item)
        for profile in profiles:
            health_status = str(profile.get("health_status") or "unknown")
            values = (
                profile.get("profile_name") or "",
                profile.get("session_label") or "",
                health_status,
                profile.get("last_status") or "",
                profile.get("last_checked_at") or "",
                profile.get("health_reason") or "",
            )
            self.monitor_tree.insert(
                "",
                "end",
                iid=str(profile.get("id")),
                values=values,
                tags=(health_status,),
            )

    def _set_backend_status(self, text: str, kind: str = "neutral") -> None:
        if not self.backend_status_label:
            return
        if kind == "ok":
            color = "#15803d"
        elif kind == "error":
            color = "#be123c"
        else:
            color = TEXT_MUTED
        self.backend_status_label.config(text=text, fg=color)

    def _get_selected_backend_profile_id(self) -> str | None:
        if not self.monitor_tree:
            return None
        selected = self.monitor_tree.selection()
        return selected[0] if selected else None

    def _validate_checker_target(self) -> str:
        target_url = self.backend_target_url_var.get().strip()
        if not target_url:
            raise ValueError("Target URL is required.")

        parsed = urlparse(target_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Target URL must start with http:// or https://")
        if parsed.hostname and parsed.hostname.lower() == "example.com":
            raise ValueError("Replace example.com with a real target URL before running the checker.")
        return target_url

    def _build_checker_payload(self, profile_ids: list[str] | None = None) -> dict:
        return {
            "target_url": self._validate_checker_target(),
            "review_keywords": [
                item.strip()
                for item in self.backend_review_keywords_var.get().split(",")
                if item.strip()
            ],
            "failure_keywords": [
                item.strip()
                for item in self.backend_failure_keywords_var.get().split(",")
                if item.strip()
            ],
            "profile_ids": profile_ids or [],
        }

    def run_backend_checker_for_selected(self) -> None:
        profile_id = self._get_selected_backend_profile_id()
        if not profile_id:
            self.messagebox.showinfo("Backend Monitor", "Select one backend profile first.")
            return
        try:
            checker_payload = self._build_checker_payload()
        except ValueError as error:
            self._set_backend_status(str(error), kind="error")
            return

        def worker() -> None:
            try:
                self._backend_request_json(
                    "/api/jobs",
                    method="POST",
                    payload={
                        "job_type": "checker",
                        "profile_id": profile_id,
                        "payload": {
                            "target_url": checker_payload["target_url"],
                            "live_status_codes": [200],
                            "review_status_codes": [401, 403],
                            "failed_status_codes": [404, 500, 503],
                            "review_keywords": checker_payload["review_keywords"],
                            "failure_keywords": checker_payload["failure_keywords"],
                        },
                    },
                )
                self.root.after(0, lambda: self._set_backend_status("Checker job submitted.", kind="ok"))
                self.refresh_backend_monitor_async()
            except Exception as error:
                self.root.after(0, lambda: self._set_backend_status(f"Checker submit failed: {error}", kind="error"))

        threading.Thread(target=worker, daemon=True).start()

    def start_all_backend_checkers(self) -> None:
        try:
            checker_payload = self._build_checker_payload()
        except ValueError as error:
            self._set_backend_status(str(error), kind="error")
            return

        def worker() -> None:
            try:
                result = self._backend_request_json(
                    "/api/jobs/start-all",
                    method="POST",
                    payload=checker_payload,
                )
                self.root.after(
                    0,
                    lambda: self._set_backend_status(
                        f"{result.get('affected_jobs', 0)} checker job(s) submitted.",
                        kind="ok",
                    ),
                )
                self.refresh_backend_monitor_async()
            except Exception as error:
                self.root.after(0, lambda: self._set_backend_status(f"Start all failed: {error}", kind="error"))

        threading.Thread(target=worker, daemon=True).start()

    def reset_backend_health(self) -> None:
        selected_profile_id = self._get_selected_backend_profile_id()

        def worker() -> None:
            try:
                profile_ids: list[str]
                if selected_profile_id:
                    profile_ids = [selected_profile_id]
                else:
                    profiles = self._backend_request_json("/api/profiles")
                    profile_ids = [str(profile.get("id")) for profile in profiles if profile.get("id")]

                for profile_id in profile_ids:
                    self._backend_request_json(
                        f"/api/profiles/{profile_id}",
                        method="PUT",
                        payload={
                            "health_status": "unknown",
                            "health_reason": "",
                        },
                    )

                count = len(profile_ids)
                self.root.after(
                    0,
                    lambda: self._set_backend_status(
                        f"Reset health for {count} profile(s).",
                        kind="ok",
                    ),
                )
                self.refresh_backend_monitor_async()
            except Exception as error:
                self.root.after(0, lambda: self._set_backend_status(f"Reset health failed: {error}", kind="error"))

        threading.Thread(target=worker, daemon=True).start()

    def stop_all_backend_jobs(self) -> None:
        def worker() -> None:
            try:
                result = self._backend_request_json("/api/jobs/stop-all", method="POST", payload={})
                self.root.after(
                    0,
                    lambda: self._set_backend_status(
                        f"{result.get('affected_jobs', 0)} pending job(s) cancelled.",
                        kind="ok",
                    ),
                )
                self.refresh_backend_monitor_async()
            except Exception as error:
                self.root.after(0, lambda: self._set_backend_status(f"Stop all failed: {error}", kind="error"))

        threading.Thread(target=worker, daemon=True).start()

    def _select_action(self, value: str) -> None:
        self.vars.action_var.set(value)
        self.set_action()

    def _refresh_action_buttons(self) -> None:
        current = self.vars.action_var.get()
        for value, button in self.action_buttons.items():
            if value == current:
                button.config(bg=ACCENT, fg=TEXT_ON_DARK, activebackground=ACCENT_HOVER, activeforeground=TEXT_ON_DARK)
            else:
                button.config(
                    bg=SIDEBAR_PANEL_BG,
                    fg=TEXT_PRIMARY,
                    activebackground=NEUTRAL_HOVER,
                    activeforeground=TEXT_PRIMARY,
                )

    def enter_credentials(self) -> None:
        self.connect_account()

    def connect_account(self) -> None:
        platform = self.vars.platform_var.get()
        selected = self._selected_report_instance_numbers()
        if not selected:
            selected = self.instances.active_instance_numbers()[:1]
        if not selected:
            self.messagebox.showwarning("Connect Account", "Select or create an account row first.")
            return
        instance_number = selected[0]
        title, help_text = self._connect_copy(platform)
        connect_window = self.create_modal(title, "760x520")
        body = self.create_modal_card(connect_window, title, help_text)

        Label(
            body,
            text=f"Selected: Firefox {instance_number}",
            bg=SURFACE_BG,
            fg=TEXT_PRIMARY,
            font=SECTION_FONT,
        ).pack(anchor="w", pady=(0, 10))

        fields: dict[str, Entry | tk.Text] = {}

        def add_entry(key: str, label: str, value: str = "", show: str | None = None) -> None:
            Label(body, text=label, bg=SURFACE_BG, fg=TEXT_MUTED, font=SMALL_FONT).pack(anchor="w", pady=(6, 2))
            entry = Entry(body, show=show or "")
            self.style_entry(entry)
            entry.insert(0, value)
            entry.pack(fill=X)
            fields[key] = entry

        report = self.instances.state.instance_reports.get(instance_number, {})
        if platform == "wordpress":
            add_entry("site_url", "WordPress Site URL", str(report.get("wordpress_site_url") or ""))
            add_entry("username", "WordPress Username", str(report.get("wordpress_username") or ""))
            add_entry("application_password", "Application Password / API Token", show="*")
        else:
            add_entry("access_token", "OAuth Access Token")
            add_entry("refresh_token", "OAuth Refresh Token (when issued)")
            add_entry("expires_at", "Expires At Unix Time (optional)")

        footer = Frame(body, bg=SURFACE_BG)
        footer.pack(fill=X, pady=(18, 0))

        def save_auth() -> None:
            auth: dict[str, str] = {}
            for key, widget in fields.items():
                value = widget.get().strip() if isinstance(widget, Entry) else widget.get("1.0", tk.END).strip()
                if value:
                    auth[key] = value
            if not auth:
                self.messagebox.showwarning("Connect Account", "No authorization data entered.")
                return
            self.instances.save_auth_for_instance(platform, instance_number, auth)
            self.messagebox.showinfo("Connect Account", "Encrypted authorization saved.")
            connect_window.destroy()

        self.create_button(footer, "Save Encrypted", save_auth, kind="primary").pack(side=LEFT)
        self.create_button(
            footer,
            "Open Platform Home",
            lambda: self.instances.open_platform_action(instance_number, "open_home", platform),
            kind="secondary",
        ).pack(side=LEFT, padx=8)

    def _connect_copy(self, platform: str) -> tuple[str, str]:
        if platform == "facebook":
            return (
                "Connect Facebook",
                "Connect with official Meta Login or open Facebook in this Firefox profile. The app does not store your Facebook password.",
            )
        if platform == "tiktok":
            return (
                "Connect TikTok",
                "Connect with TikTok Login Kit/OAuth. The app stores only encrypted tokens, not your TikTok password.",
            )
        if platform == "youtube":
            return (
                "Connect YouTube / Gmail",
                "Connect with Google OAuth. The app stores encrypted refresh token, not Gmail password.",
            )
        if platform == "instagram":
            return (
                "Connect Instagram",
                "Connect with official Meta/Instagram authorization. The app does not store Instagram password.",
            )
        return (
            "Connect WordPress",
            "Use WordPress Site URL, username, and Application Password/API token. Store encrypted.",
        )

    def refresh_login_selected(self) -> None:
        selected = self._selected_report_instance_numbers()
        if not selected:
            selected = self.instances.active_instance_numbers()
        self.instances.refresh_login_for_instances(selected, self.vars.platform_var.get())

    def clear_selected_auth_tokens(self) -> None:
        selected = self._selected_report_instance_numbers()
        if not selected:
            self.messagebox.showwarning("Clear Token", "Select at least one account row first.")
            return
        platform = self.vars.platform_var.get()
        for instance_number in selected:
            self.instances.clear_auth_for_instance(platform, instance_number)
        self.messagebox.showinfo("Clear Token", f"Cleared encrypted token for {len(selected)} account(s).")

    def show_reconnect_required(self) -> None:
        self.legacy_find_var.set("Need Reconnect")
        self.refresh_report_table()

    def save_credentials(self) -> None:
        self.messagebox.showinfo("Disabled", "Plaintext password storage is disabled. Use Connect Account.")

    def open_input_window(self) -> None:
        self.messagebox.showinfo("Disabled", "Bulk credential paste is disabled. Use Import Accounts without passwords.")

    def export_credentials_to_excel(self) -> None:
        self.messagebox.showinfo("Disabled", "Credential export is disabled for passwords, 2FA, cookies, and tokens.")

    def _open_photo_cover_setup_window(self) -> None:
        setup_window = self.create_modal("Photo/Cover Setup", "980x620")
        body = self.create_modal_card(
            setup_window,
            "Upload Photo + Cover",
            "Set profile photo, cover, and optional profile description per Firefox.",
        )

        canvas = Canvas(body, bg=SURFACE_BG, bd=0, highlightthickness=0)
        scroll_y = Scrollbar(body, orient="vertical", command=canvas.yview)
        rows_frame = Frame(canvas, bg=SURFACE_BG)
        row_vars: dict[int, tuple[tk.StringVar, tk.StringVar, tk.StringVar]] = {}

        active_instances = [
            i + 1
            for i, (_button, frame) in enumerate(self.state.firefox_buttons)
            if frame is not None and (i + 1) not in self.state.deleted_instances
        ]
        for instance_number in active_instances:
            row = Frame(rows_frame, bg=SURFACE_ALT, highlightbackground=BORDER, highlightthickness=1)
            row.pack(fill=X, pady=5)

            Label(
                row,
                text=f"Firefox {instance_number}",
                bg=SURFACE_ALT,
                fg=TEXT_PRIMARY,
                font=SECTION_FONT,
                width=11,
                anchor="w",
            ).grid(row=0, column=0, rowspan=3, sticky="w", padx=(10, 8), pady=8)

            photo_var = tk.StringVar(value=self.state.photo_upload_paths.get(instance_number, ""))
            cover_var = tk.StringVar(value=self.state.cover_upload_paths.get(instance_number, ""))
            description_var = tk.StringVar(value=self.state.photo_upload_descriptions.get(instance_number, ""))
            row_vars[instance_number] = (photo_var, cover_var, description_var)

            Label(row, text="Profile", bg=SURFACE_ALT, fg=TEXT_MUTED, font=SMALL_FONT).grid(
                row=0, column=1, sticky="w", padx=(2, 6), pady=(8, 4)
            )
            photo_entry = Entry(row, textvariable=photo_var)
            self.style_entry(photo_entry, width=50)
            photo_entry.grid(row=0, column=2, sticky="we", padx=(0, 6), pady=(8, 4))
            self.create_button(
                row,
                "Open",
                lambda v=photo_var: self._pick_image_path(v),
                kind="secondary",
                compact=True,
            ).grid(row=0, column=3, padx=(0, 4), pady=(8, 4))
            self.create_button(
                row,
                "Clear",
                lambda v=photo_var: v.set(""),
                kind="neutral",
                compact=True,
            ).grid(row=0, column=4, padx=(0, 8), pady=(8, 4))

            Label(row, text="Cover", bg=SURFACE_ALT, fg=TEXT_MUTED, font=SMALL_FONT).grid(
                row=1, column=1, sticky="w", padx=(2, 6), pady=(0, 8)
            )
            cover_entry = Entry(row, textvariable=cover_var)
            self.style_entry(cover_entry, width=50)
            cover_entry.grid(row=1, column=2, sticky="we", padx=(0, 6), pady=(0, 8))
            self.create_button(
                row,
                "Open",
                lambda v=cover_var: self._pick_image_path(v),
                kind="secondary",
                compact=True,
            ).grid(row=1, column=3, padx=(0, 4), pady=(0, 8))
            self.create_button(
                row,
                "Clear",
                lambda v=cover_var: v.set(""),
                kind="neutral",
                compact=True,
            ).grid(row=1, column=4, padx=(0, 8), pady=(0, 8))

            Label(row, text="Description", bg=SURFACE_ALT, fg=TEXT_MUTED, font=SMALL_FONT).grid(
                row=2, column=1, sticky="w", padx=(2, 6), pady=(0, 8)
            )
            description_entry = Entry(row, textvariable=description_var)
            self.style_entry(description_entry, width=50)
            description_entry.grid(row=2, column=2, sticky="we", padx=(0, 6), pady=(0, 8))
            self.create_button(
                row,
                "Clear",
                lambda v=description_var: v.set(""),
                kind="neutral",
                compact=True,
            ).grid(row=2, column=4, padx=(0, 8), pady=(0, 8))

            row.grid_columnconfigure(2, weight=1)

        if not active_instances:
            Label(
                rows_frame,
                text="No active Firefox profiles. Generate instances first.",
                bg=SURFACE_BG,
                fg=TEXT_MUTED,
                font=BODY_FONT,
            ).pack(anchor="w", padx=6, pady=6)

        rows_frame.update_idletasks()
        canvas.create_window(0, 0, anchor="nw", window=rows_frame)
        canvas.update_idletasks()
        canvas.config(scrollregion=canvas.bbox("all"), yscrollcommand=scroll_y.set)
        canvas.pack(fill=BOTH, expand=True, side=LEFT)
        scroll_y.pack(fill=Y, side=RIGHT, padx=(8, 0))

        def save_assignments(close_after: bool = False) -> None:
            for instance_number, (photo_var, cover_var, description_var) in row_vars.items():
                photo_path = photo_var.get().strip()
                cover_path = cover_var.get().strip()
                description_text = description_var.get().strip()

                if photo_path:
                    if not os.path.isfile(photo_path):
                        messagebox.showerror("Invalid file", f"Firefox {instance_number} profile photo file not found.")
                        return
                    self.state.photo_upload_paths[instance_number] = photo_path
                else:
                    self.state.photo_upload_paths.pop(instance_number, None)

                if cover_path:
                    if not os.path.isfile(cover_path):
                        messagebox.showerror("Invalid file", f"Firefox {instance_number} cover file not found.")
                        return
                    self.state.cover_upload_paths[instance_number] = cover_path
                else:
                    self.state.cover_upload_paths.pop(instance_number, None)

                if description_text:
                    self.state.photo_upload_descriptions[instance_number] = description_text
                else:
                    self.state.photo_upload_descriptions.pop(instance_number, None)

            self.instances.save_instance_data()
            if close_after:
                setup_window.destroy()
                return
            messagebox.showinfo("Saved", "Photo/Cover settings saved.")

        footer = Frame(body, bg=SURFACE_BG)
        footer.pack(fill=X, pady=(12, 0))
        self.create_button(footer, "Save", lambda: save_assignments(False), kind="primary").pack(side=LEFT)
        self.create_button(footer, "Save & Close", lambda: save_assignments(True), kind="success").pack(
            side=LEFT, padx=(8, 0)
        )
        self.create_button(footer, "Close", setup_window.destroy, kind="neutral").pack(side=LEFT, padx=(8, 0))

    def _pick_image_path(self, target_var) -> None:
        selected_path = self.filedialog.askopenfilename(filetypes=[("Image Files", "*.png;*.jpg;*.jpeg;*.webp")])
        if selected_path:
            target_var.set(selected_path)

    def run_firefox_dialog(self) -> None:
        dialog = self.create_modal("Run Firefox", "460x390")
        body = self.create_modal_card(
            dialog,
            "Batch Runner",
            "Set the range and how many instances should run at once.",
        )

        self._prime_run_fields()
        form = Frame(body, bg=SURFACE_BG)
        form.pack(fill=X)

        self._modal_field(form, "Start Instance", self.vars.start_instance_var, 0)
        self._modal_field(form, "End Instance", self.vars.end_instance_var, 1)
        self._modal_field(form, "Max On Screen", self.vars.max_instances_var, 2)

        self._normalize_run_mode_selection()

        options = Frame(body, bg=SURFACE_BG)
        options.pack(fill=X, pady=(10, 0))
        self._styled_checkbutton(
            options,
            "Auto Run",
            self.vars.auto_run_var,
            command=lambda: self._select_run_mode("auto"),
        ).pack(anchor="w")
        self._styled_checkbutton(
            options,
            "Click Run",
            self.vars.click_run_var,
            command=lambda: self._select_run_mode("click"),
        ).pack(anchor="w", pady=4)
        self._styled_checkbutton(
            options,
            "Time Run",
            self.vars.time_run_var,
            command=lambda: self._select_run_mode("time"),
        ).pack(anchor="w")

        footer = Frame(body, bg=SURFACE_BG)
        footer.pack(fill=X, pady=(16, 0))
        self.create_button(footer, "Run", self.run_multiple_firefox_auto, kind="success").pack(side=LEFT)
        self.create_button(footer, "Stop", self.actions.request_stop_batch, kind="warning").pack(side=LEFT, padx=(8, 0))
        self.create_button(footer, "Close", dialog.destroy, kind="neutral").pack(side=LEFT, padx=(8, 0))

    def _modal_field(self, parent: Frame, label_text: str, variable, row: int) -> None:
        Label(parent, text=label_text, bg=SURFACE_BG, fg=TEXT_MUTED, font=BODY_FONT).grid(row=row, column=0, sticky="w", pady=6)
        entry = Entry(parent, textvariable=variable)
        self.style_entry(entry, width=24)
        entry.grid(row=row, column=1, sticky="w", padx=(12, 0), pady=6)

    def _styled_checkbutton(self, parent: Frame, text: str, variable, command=None) -> Checkbutton:
        return Checkbutton(
            parent,
            text=text,
            variable=variable,
            command=command,
            bg=SURFACE_BG,
            fg=TEXT_PRIMARY,
            selectcolor=SURFACE_BG,
            activebackground=SURFACE_BG,
            activeforeground=TEXT_PRIMARY,
            font=BODY_FONT,
            highlightthickness=0,
        )

    def _normalize_run_mode_selection(self) -> None:
        selected_modes = [
            self.vars.auto_run_var.get(),
            self.vars.click_run_var.get(),
            self.vars.time_run_var.get(),
        ]
        if sum(1 for selected in selected_modes if selected) == 1:
            return
        self._select_run_mode("auto")

    def _select_run_mode(self, mode: str) -> None:
        self.vars.auto_run_var.set(mode == "auto")
        self.vars.click_run_var.set(mode == "click")
        self.vars.time_run_var.set(mode == "time")

    def _prime_run_fields(self) -> None:
        active_instances = [
            index + 1
            for index, (_button, frame) in enumerate(self.state.firefox_buttons)
            if frame is not None and (index + 1) not in self.state.deleted_instances
        ]
        default_start = min(active_instances) if active_instances else 1
        default_end = max(active_instances) if active_instances else max(default_start, 1)

        if self.vars.start_instance_var.get() <= 0:
            self.vars.start_instance_var.set(default_start)
        if self.vars.end_instance_var.get() <= 0:
            self.vars.end_instance_var.set(default_end)
        if self.vars.start_instance_var.get() > self.vars.end_instance_var.get():
            self.vars.end_instance_var.set(self.vars.start_instance_var.get())
        if self.vars.max_instances_var.get() <= 0:
            span = self.vars.end_instance_var.get() - self.vars.start_instance_var.get() + 1
            self.vars.max_instances_var.set(max(1, min(6, span)))

    def run_multiple_firefox_auto(self) -> None:
        if self.vars.auto_run_var.get():
            self.actions.run_multiple_firefox()
        elif self.vars.click_run_var.get():
            self.actions.run_one_firefox_batch()
        elif self.vars.time_run_var.get():
            self.actions.run_multiple_firefox_with_time()
        else:
            self.actions.run_multiple_firefox()

    def show_summary(self) -> None:
        success_count = sum(1 for summary in self.state.run_summary if "Success" in summary)
        error_count = sum(1 for summary in self.state.run_summary if "Error" in summary)
        summary_message = (
            f"Total instances: {len(self.state.run_summary)}\n"
            f"Success: {success_count}\n"
            f"Errors: {error_count}\n\nDetails:\n"
            + "\n".join(self.state.run_summary)
        )
        messagebox.showinfo("Summary", summary_message)

    def set_action(self) -> None:
        self.refresh_dashboard()
        selected_action = self.vars.action_var.get()
        if self.vars.platform_var.get() != "facebook":
            if selected_action in {"publish_tool", "upload_video", "create_post"}:
                self._open_platform_publish_window()
            return
        if selected_action == "care":
            self._open_care_window()
        elif selected_action == "join_group":
            self._open_join_group_window()
        elif selected_action == "share_to_groups":
            self._open_share_groups_window()
        elif selected_action == "upload_reel":
            self._open_upload_reel_window()
        elif selected_action == "upload_photo_cover":
            self._open_photo_cover_setup_window()

    def _open_platform_publish_window(self) -> None:
        platform_label = self._platform_label()
        platform = self.vars.platform_var.get()
        existing_window = self.platform_tool_windows.get(platform)
        if existing_window and existing_window.winfo_exists():
            existing_window.lift()
            self._refresh_platform_tool_accounts(platform)
            return

        publish_window = self.create_modal(f"Auto Post {platform_label}", "1320x740", modal=False)
        publish_window.resizable(True, True)
        publish_window.minsize(1120, 650)
        self.platform_tool_windows[platform] = publish_window
        self.platform_tool_stat_labels[platform] = {}
        publish_window.protocol("WM_DELETE_WINDOW", lambda: self._close_platform_tool(platform))

        shell = Frame(publish_window, bg=APP_BG)
        shell.pack(fill=BOTH, expand=True, padx=14, pady=14)

        top = Frame(shell, bg=SURFACE_BG, highlightbackground=BORDER, highlightthickness=1, bd=0)
        top.pack(fill=X)
        controls = Frame(top, bg=SURFACE_BG)
        controls.pack(side=LEFT, fill=X, expand=True, padx=12, pady=10)
        stats = Frame(top, bg=SURFACE_BG)
        stats.pack(side=RIGHT, padx=12, pady=10)

        Label(controls, text="New Country Type", bg=SURFACE_BG, fg=TEXT_MUTED, font=SMALL_FONT).grid(row=0, column=0, sticky="w")
        store_entry = self.style_entry(Entry(controls, textvariable=self.legacy_store_name_var), width=22)
        store_entry.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(2, 8))
        Label(controls, text="Country Type", bg=SURFACE_BG, fg=TEXT_MUTED, font=SMALL_FONT).grid(row=0, column=1, sticky="w")
        store_menu = ttk.Combobox(
            controls,
            textvariable=self.legacy_store_var,
            values=tuple(self.legacy_stores),
            state="readonly",
            width=20,
        )
        store_menu.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(2, 8))
        store_menu.bind("<<ComboboxSelected>>", lambda _event: self._select_account_type())
        self.platform_tool_country_type_menus[platform] = store_menu
        self.create_button(
            controls,
            "Add",
            self._create_legacy_store,
            kind="secondary",
            compact=True,
        ).grid(row=1, column=2, sticky="ew", padx=(0, 8), pady=(2, 8))
        self.create_button(
            controls,
            "Remove",
            self._remove_legacy_store,
            kind="neutral",
            compact=True,
        ).grid(row=1, column=3, sticky="ew", pady=(2, 8))

        Label(controls, text="New Account Type", bg=SURFACE_BG, fg=TEXT_MUTED, font=SMALL_FONT).grid(row=2, column=0, sticky="w")
        account_type_entry = self.style_entry(Entry(controls, textvariable=self.account_group_name_var), width=22)
        account_type_entry.grid(row=3, column=0, sticky="ew", padx=(0, 8), pady=(2, 8))
        Label(controls, text="Account Type", bg=SURFACE_BG, fg=TEXT_MUTED, font=SMALL_FONT).grid(row=2, column=1, sticky="w")
        account_type_menu = ttk.Combobox(
            controls,
            textvariable=self.account_group_var,
            values=tuple(self.account_groups),
            state="readonly",
            width=20,
        )
        account_type_menu.grid(row=3, column=1, sticky="ew", padx=(0, 8), pady=(2, 8))
        account_type_menu.bind("<<ComboboxSelected>>", lambda _event: self._select_custom_account_type())
        self.platform_tool_account_type_menus[platform] = account_type_menu
        self.create_button(
            controls,
            "Add",
            self._create_custom_account_type,
            kind="secondary",
            compact=True,
        ).grid(row=3, column=2, sticky="ew", padx=(0, 8), pady=(2, 8))
        self.create_button(
            controls,
            "Remove",
            self._remove_custom_account_type,
            kind="neutral",
            compact=True,
        ).grid(row=3, column=3, sticky="ew", pady=(2, 8))

        Label(
            controls,
            text=f"Auto Post {platform_label}",
            bg=SURFACE_BG,
            fg=TEXT_PRIMARY,
            font=TITLE_FONT,
        ).grid(row=4, column=0, sticky="w", padx=(0, 8), pady=(0, 8))
        Label(controls, text="Function", bg=SURFACE_BG, fg=TEXT_MUTED, font=SMALL_FONT).grid(
            row=5,
            column=0,
            sticky="w",
        )
        function_var = tk.StringVar(master=publish_window, value=self._platform_default_publish_action(platform))
        function_menu = ttk.Combobox(
            controls,
            textvariable=function_var,
            values=self._platform_tool_function_labels(platform),
            state="readonly",
            width=22,
        )
        function_menu.grid(row=6, column=0, sticky="ew", padx=(0, 8))

        for column in range(4):
            controls.grid_columnconfigure(column, weight=1)

        self._platform_tool_stat(platform, stats, "Total Post", "0", SUCCESS)
        self._platform_tool_stat(platform, stats, "No Login", "0", "#6b7280")
        self._platform_tool_stat(platform, stats, "Failed", "0", DANGER)
        self._platform_tool_stat(platform, stats, "Success", "0", ACCENT)

        body = Frame(shell, bg=SURFACE_ALT, highlightbackground=BORDER, highlightthickness=1, bd=0)
        body.pack(fill=BOTH, expand=True, pady=(10, 0))

        right = Frame(body, bg=SURFACE_ALT, width=560)
        right.pack(side=RIGHT, fill=Y, padx=(0, 12), pady=12)
        right.pack_propagate(False)
        publish_window._right_panel = right
        left = Frame(body, bg=SURFACE_ALT)
        left.pack(side=LEFT, fill=BOTH, expand=True, padx=12, pady=12)

        run_row = Frame(left, bg=SURFACE_ALT)
        run_row.pack(fill=X, pady=(0, 8))
        self.create_button(
            run_row,
            "Start Post",
            lambda: self._run_platform_tool_selected(platform, function_var.get(), run_all=False),
            kind="success",
            compact=True,
        ).pack(side=LEFT, padx=(0, 6))
        self.create_button(
            run_row,
            "Stop",
            self.instances.stop_all_instances,
            kind="warning",
            compact=True,
        ).pack(side=LEFT, padx=(0, 6))
        self.create_button(
            run_row,
            "Setup Account",
            self.enter_credentials,
            kind="secondary",
            compact=True,
        ).pack(side=LEFT, padx=(0, 6))
        self.create_button(
            run_row,
            "Clear Data",
            lambda: self._clear_platform_tool_selected(platform),
            kind="neutral",
            compact=True,
        ).pack(side=LEFT, padx=(0, 6))
        self.create_button(run_row, "Close", lambda: self._close_platform_tool(platform), kind="neutral", compact=True).pack(
            side=LEFT
        )

        option_row = Frame(left, bg=SURFACE_ALT)
        option_row.pack(fill=X, pady=(0, 8))
        Label(option_row, text="Thread", bg=SURFACE_ALT, fg=TEXT_MUTED, font=SMALL_FONT).pack(side=LEFT)
        thread_entry = self.style_entry(Entry(option_row, textvariable=self.vars.thread_count_var), width=5)
        thread_entry.pack(side=LEFT, padx=(6, 14))
        Label(option_row, text="Delay Post", bg=SURFACE_ALT, fg=TEXT_MUTED, font=SMALL_FONT).pack(side=LEFT)
        delay_post_var = tk.StringVar(master=publish_window, value="5")
        self.style_entry(Entry(option_row, textvariable=delay_post_var), width=5).pack(side=LEFT, padx=(6, 14))
        Label(option_row, text="Delay Cmd", bg=SURFACE_ALT, fg=TEXT_MUTED, font=SMALL_FONT).pack(side=LEFT)
        delay_cmd_var = tk.StringVar(master=publish_window, value="6")
        self.style_entry(Entry(option_row, textvariable=delay_cmd_var), width=5).pack(side=LEFT, padx=(6, 14))
        move_var = tk.BooleanVar(master=publish_window, value=True)
        self._styled_checkbutton(option_row, "Move File After Upload", move_var).pack(side=LEFT)

        choose_row = Frame(left, bg=SURFACE_ALT)
        choose_row.pack(fill=X, pady=(0, 8))
        check_all_var = tk.BooleanVar(master=publish_window, value=False)
        self._styled_checkbutton(
            choose_row,
            "Check All",
            check_all_var,
            command=lambda: self._platform_tool_toggle_all(platform, check_all_var.get()),
        ).pack(side=LEFT)
        self.create_button(
            choose_row,
            "Choose Account",
            lambda: self._platform_tool_set_status(platform, "Select rows in the account table, then Start Post."),
            kind="secondary",
            compact=True,
        ).pack(side=LEFT, padx=(8, 0))
        self.create_button(
            choose_row,
            "Open Selected",
            lambda: self._run_platform_tool_selected(platform, function_var.get(), run_all=False),
            kind="primary",
            compact=True,
        ).pack(side=LEFT, padx=(8, 0))

        table_frame = Frame(left, bg=SURFACE_BG, highlightbackground=BORDER, highlightthickness=1, bd=0)
        table_frame.pack(fill=BOTH, expand=True)
        platform_columns_for_tool = self._report_columns()
        columns = ("selected", *(key for key, _title, _width in platform_columns_for_tool))
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", style="Report.Treeview", selectmode="extended")
        headings = {"selected": ("Use", 54)}
        headings.update({key: (title, width) for key, title, width in platform_columns_for_tool})
        for key, (title, width) in headings.items():
            tree.heading(key, text=title)
            tree.column(key, width=width, minwidth=width, anchor="w", stretch=False)
        tree.tag_configure("live", background="#04e51f", foreground="#07320f")
        tree.tag_configure("review", background="#f59e0b", foreground="#ffffff")
        tree.tag_configure("login_required", background="#d1d5db", foreground="#111827")
        tree.tag_configure("failed", background="#ff3b1f", foreground="#ffffff")
        tree.tag_configure("ip_mismatch", background="#1f6feb", foreground="#ffffff")
        tree.tag_configure("working", background="#1f6feb", foreground="#ffffff")
        tree.tag_configure("select", background="#05CBE5", foreground="#010C03")
        table_scroll_y = Scrollbar(table_frame, orient="vertical", command=tree.yview)
        table_scroll_x = Scrollbar(table_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=table_scroll_y.set, xscrollcommand=table_scroll_x.set)
        table_scroll_y.pack(side=RIGHT, fill=Y)
        table_scroll_x.pack(side="bottom", fill=X)
        tree.pack(side=LEFT, fill=BOTH, expand=True)
        self.platform_tool_trees[platform] = tree
        tree.bind("<Button-1>", lambda event, p=platform: self._platform_tool_tree_click(event, p))

        self._build_platform_tool_right_panel(right, publish_window, platform, platform_label, function_var)
        function_menu.bind("<<ComboboxSelected>>", lambda _event: self._refresh_platform_tool_input_panel(platform))

        status_label = Label(shell, text="Ready.", bg=APP_BG, fg=TEXT_MUTED, font=SMALL_FONT)
        status_label.pack(anchor="w", pady=(8, 0))
        self.platform_tool_status_labels[platform] = status_label
        self._refresh_platform_tool_accounts(platform)
        self._apply_runtime_theme(publish_window)

    def _build_platform_tool_right_panel(
        self,
        parent: Frame,
        window: Toplevel,
        platform: str,
        platform_label: str,
        function_var: tk.StringVar,
    ) -> None:
        parent._function_var = function_var
        parent._platform_label = platform_label
        self._render_platform_tool_input_panel(parent, window, platform)

    def _refresh_platform_tool_input_panel(self, platform: str) -> None:
        window = self.platform_tool_windows.get(platform)
        if not window or not window.winfo_exists():
            return
        right_panel = getattr(window, "_right_panel", None)
        if right_panel:
            self._render_platform_tool_input_panel(right_panel, window, platform)

    def _render_platform_tool_input_panel(self, parent: Frame, window: Toplevel, platform: str) -> None:
        for child in parent.winfo_children():
            child.destroy()

        function_var = getattr(parent, "_function_var", tk.StringVar(master=window, value=self._platform_default_publish_action(platform)))
        platform_label = getattr(parent, "_platform_label", self._platform_label())
        function_label = function_var.get()
        if platform == "facebook":
            self._render_facebook_function_panel(parent, window, platform, function_label)
            return
        post_types = self._platform_post_types_for_function(platform, function_label)
        post_type_var = tk.StringVar(master=window, value=post_types[0])
        limit_var = self.vars.share_group_count_var
        if not limit_var.get().strip():
            limit_var.set("1")
        command_var = tk.StringVar(master=window, value="Default")
        system_var = tk.StringVar(master=window, value=platform_label)
        random_count_var = tk.StringVar(master=window, value="3")
        caption_from_file_var = tk.BooleanVar(master=window, value=False)
        random_file_var = tk.BooleanVar(master=window, value=True)
        cmd_post_var = tk.BooleanVar(master=window, value=False)
        random_emoji_letters_var = tk.BooleanVar(master=window, value=False)
        random_emoji_var = tk.BooleanVar(master=window, value=False)

        Label(parent, text="Post Setup", bg=SURFACE_ALT, fg=TEXT_PRIMARY, font=SECTION_FONT).pack(anchor="w")

        auto_row = Frame(parent, bg=SURFACE_ALT)
        auto_row.pack(fill=X, pady=(8, 0))
        self._styled_checkbutton(auto_row, "Remove Auto Number", tk.BooleanVar(master=window, value=True)).pack(side=LEFT)

        type_row = Frame(parent, bg=SURFACE_ALT)
        type_row.pack(fill=X, pady=(8, 0))
        Label(type_row, text="Post Type", bg=SURFACE_ALT, fg=TEXT_MUTED, font=SMALL_FONT).pack(side=LEFT)
        ttk.Combobox(
            type_row,
            textvariable=post_type_var,
            values=post_types,
            state="readonly",
            width=18,
        ).pack(side=LEFT, padx=(8, 0))
        Label(type_row, text="Limited Post", bg=SURFACE_ALT, fg=TEXT_MUTED, font=SMALL_FONT).pack(side=LEFT, padx=(10, 0))
        self.style_entry(Entry(type_row, textvariable=limit_var), width=5).pack(side=LEFT, padx=(6, 0))

        option_row = Frame(parent, bg=SURFACE_ALT)
        option_row.pack(fill=X, pady=(8, 0))
        self._styled_checkbutton(option_row, "Caption from file", caption_from_file_var).pack(side=LEFT)
        self._styled_checkbutton(option_row, "Random file", random_file_var).pack(side=LEFT, padx=(8, 0))
        self._styled_checkbutton(option_row, "Cmd Post", cmd_post_var).pack(side=LEFT, padx=(8, 0))
        ttk.Combobox(
            option_row,
            textvariable=command_var,
            values=("Default", "No Comment", "Custom"),
            state="readonly",
            width=12,
        ).pack(side=LEFT, padx=(6, 0))

        editor_row = Frame(parent, bg=SURFACE_ALT)
        editor_row.pack(fill=X, pady=(8, 0))
        caption_box = self._platform_tool_textbox(editor_row, height=7)
        caption_box.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 8))
        caption_box.insert("1.0", self.vars.description_var.get())
        caption_box.bind("<KeyRelease>", lambda _event: self.vars.description_var.set(caption_box.get("1.0", "end").strip()))
        command_box = self._platform_tool_textbox(editor_row, height=7)
        command_box.pack(side=LEFT, fill=BOTH, expand=True)

        Label(parent, text="Path Video", bg=SURFACE_ALT, fg=SUCCESS, font=SMALL_FONT).pack(anchor="w", pady=(8, 2))
        path_box = self._platform_tool_textbox(parent, height=4)
        path_box.pack(fill=X)
        path_box.insert("1.0", self.vars.reel_folder_or_file_var.get())
        path_box.bind("<KeyRelease>", lambda _event: self.vars.reel_folder_or_file_var.set(path_box.get("1.0", "end").strip()))

        random_row = Frame(parent, bg=SURFACE_ALT)
        random_row.pack(fill=X, pady=(8, 0))
        self._styled_checkbutton(random_row, "Random Emoji+Letters", random_emoji_letters_var).pack(side=LEFT)
        spin = tk.Spinbox(
            random_row,
            from_=1,
            to=99,
            textvariable=random_count_var,
            width=4,
            bg=INPUT_BG,
            fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            font=BODY_FONT,
        )
        spin.pack(side=LEFT, padx=(8, 0))

        emoji_row = Frame(parent, bg=SURFACE_ALT)
        emoji_row.pack(fill=X, pady=(6, 0))
        self._styled_checkbutton(emoji_row, "Random Emoji", random_emoji_var).pack(side=LEFT)

        Label(parent, text="System Type", bg=SURFACE_ALT, fg=TEXT_MUTED, font=SMALL_FONT).pack(anchor="w", pady=(10, 2))
        ttk.Combobox(
            parent,
            textvariable=system_var,
            values=tuple(label for label, _platform in self.PLATFORMS),
            state="readonly",
            width=24,
        ).pack(anchor="w")

        footer = Frame(parent, bg=SURFACE_ALT)
        footer.pack(fill=X, pady=(14, 0))
        self.create_button(
            footer,
            "Add Video",
            self.browse_files,
            kind="warning",
            compact=True,
        ).pack(side=LEFT, padx=(0, 8))
        self.create_button(
            footer,
            "Save Setting",
            lambda: self._save_platform_tool_settings(platform),
            kind="success",
            compact=True,
        ).pack(side=LEFT, padx=(0, 8))
        self.create_button(
            footer,
            "Open Selected",
            lambda: self._run_platform_tool_selected(platform, function_label, run_all=False),
            kind="primary",
            compact=True,
        ).pack(side=LEFT)
        self.platform_tool_input_refs[platform] = {
            "function_var": function_var,
            "post_type_var": post_type_var,
            "limit_var": limit_var,
            "caption_box": caption_box,
            "command_box": command_box,
            "path_box": path_box,
            "caption_from_file_var": caption_from_file_var,
            "random_file_var": random_file_var,
            "cmd_post_var": cmd_post_var,
            "command_var": command_var,
            "random_count_var": random_count_var,
            "random_emoji_letters_var": random_emoji_letters_var,
            "random_emoji_var": random_emoji_var,
            "system_var": system_var,
        }
        self._apply_runtime_theme(parent)

    def _render_facebook_function_panel(self, parent: Frame, window: Toplevel, platform: str, function_label: str) -> None:
        action_value = self._platform_tool_action_value(platform, function_label)
        normalized = action_value.lower()
        refs: dict[str, object] = {}

        Label(parent, text=function_label, bg=SURFACE_ALT, fg=TEXT_PRIMARY, font=SECTION_FONT).pack(anchor="w")
        Label(
            parent,
            text=f"Code folder: Facebook\\{function_label}",
            bg=SURFACE_ALT,
            fg=TEXT_MUTED,
            font=SMALL_FONT,
        ).pack(anchor="w", pady=(2, 8))

        def field(label: str, variable, width: int = 30) -> Entry:
            row = Frame(parent, bg=SURFACE_ALT)
            row.pack(fill=X, pady=5)
            Label(row, text=label, bg=SURFACE_ALT, fg=TEXT_MUTED, font=SMALL_FONT, width=18, anchor="w").pack(side=LEFT)
            entry = Entry(row, textvariable=variable)
            self.style_entry(entry, width=width)
            entry.pack(side=LEFT, fill=X, expand=True, padx=(8, 0))
            return entry

        if normalized == "care":
            field("Video Links", self.vars.video_link_var, 42)
            field("Watch Count", self.vars.watch_count_var, 8)
            self._hms_duration_row(parent, "Watch Duration", self.vars.watch_duration_var, window)
            self._hms_duration_row(parent, "Scroll Duration", self.vars.scroll_duration_var, window)
            field("Comment Text", self.vars.comment_text_var, 42)
            field("Share Title", self.vars.share_title_var, 42)
            checks = Frame(parent, bg=SURFACE_ALT)
            checks.pack(fill=X, pady=(8, 0))
            self._styled_checkbutton(checks, "Like", self.vars.like_video_var).pack(side=LEFT)
            self._styled_checkbutton(checks, "Comment", self.vars.comment_video_var).pack(side=LEFT, padx=(8, 0))
            self._styled_checkbutton(checks, "Share", self.vars.share_video_var).pack(side=LEFT, padx=(8, 0))
            self._styled_checkbutton(checks, "Scroll", self.vars.scroll_var).pack(side=LEFT, padx=(8, 0))

        elif normalized == "join_group":
            field("Group URLs", self.vars.group_urls_var, 46)

        elif normalized == "share_to_groups":
            field("Video Link", self.vars.video_link_var, 46)
            field("Group URLs", self.vars.group_urls_var, 46)
            field("Share Count", self.vars.share_group_count_var, 8)
            Label(parent, text="Post Text", bg=SURFACE_ALT, fg=TEXT_MUTED, font=SMALL_FONT).pack(anchor="w", pady=(8, 2))
            post_box = self._platform_tool_textbox(parent, 7)
            post_box.pack(fill=BOTH, expand=True)
            post_box.insert("1.0", self.vars.post_text_var.get())
            refs["post_box"] = post_box

        elif normalized == "upload_reel":
            row = Frame(parent, bg=SURFACE_ALT)
            row.pack(fill=X, pady=(0, 8))
            self._styled_checkbutton(row, "Reel", self.vars.switch_reel_var).pack(side=LEFT)
            self._styled_checkbutton(row, "Video/Picture", self.vars.switch_video_var).pack(side=LEFT, padx=(8, 0))
            self._styled_checkbutton(row, "Share", self.vars.switch_share_var).pack(side=LEFT, padx=(8, 0))
            field("Page Link", self.vars.page_link_var, 46)
            field("Share Count", self.vars.share_group_count_var, 8)
            Label(parent, text="Reel / Video Files", bg=SURFACE_ALT, fg=TEXT_MUTED, font=SMALL_FONT).pack(anchor="w", pady=(8, 2))
            path_box = self._platform_tool_textbox(parent, 4)
            path_box.pack(fill=X)
            path_box.insert("1.0", self.vars.reel_folder_or_file_var.get())
            refs["path_box"] = path_box
            self.create_button(parent, "Browse Video", self.browse_files, kind="secondary", compact=True).pack(anchor="w", pady=(6, 0))
            Label(parent, text="Description", bg=SURFACE_ALT, fg=TEXT_MUTED, font=SMALL_FONT).pack(anchor="w", pady=(8, 2))
            desc_box = self._platform_tool_textbox(parent, 5)
            desc_box.pack(fill=X)
            desc_box.insert("1.0", self.vars.description_var.get())
            refs["caption_box"] = desc_box
            self._styled_checkbutton(parent, "Include Description", self.vars.description_check_var).pack(anchor="w", pady=(6, 0))

        elif normalized == "upload_photo_cover":
            self.create_button(
                parent,
                "Open Photo/Cover Setup",
                self._open_photo_cover_setup_window,
                kind="secondary",
                compact=True,
            ).pack(anchor="w", pady=(0, 8))
            Label(
                parent,
                text="Set photo, cover, and profile description per account before running.",
                bg=SURFACE_ALT,
                fg=TEXT_MUTED,
                font=SMALL_FONT,
                wraplength=500,
                justify=LEFT,
            ).pack(anchor="w")

        elif normalized in {"login", "clear_data", "get_id", "get_gmail", "get_date"}:
            target = {
                "login": "Open Facebook login/profile session.",
                "clear_data": "Clear cached browser data for selected profiles.",
                "get_id": "Open profile About > Contact and basic info.",
                "get_gmail": "Open Meta Accounts Center personal info.",
                "get_date": "Open Facebook personal information page.",
            }.get(normalized, "Run selected action.")
            Label(parent, text=target, bg=SURFACE_ALT, fg=TEXT_PRIMARY, font=BODY_FONT, wraplength=500, justify=LEFT).pack(anchor="w")

        else:
            Label(parent, text="Select a Facebook function to show its settings.", bg=SURFACE_ALT, fg=TEXT_MUTED, font=BODY_FONT).pack(anchor="w")

        footer = Frame(parent, bg=SURFACE_ALT)
        footer.pack(fill=X, pady=(14, 0))
        self.create_button(
            footer,
            "Save Setting",
            lambda: self._save_platform_tool_settings(platform),
            kind="success",
            compact=True,
        ).pack(side=LEFT, padx=(0, 8))
        self.create_button(
            footer,
            "Open Selected",
            lambda: self._run_platform_tool_selected(platform, function_label, run_all=False),
            kind="primary",
            compact=True,
        ).pack(side=LEFT)
        refs["function_label"] = function_label
        self.platform_tool_input_refs[platform] = refs
        self._apply_runtime_theme(parent)

    def _platform_tool_textbox(self, parent: Frame, height: int) -> tk.Text:
        return tk.Text(
            parent,
            height=height,
            bg=INPUT_BG,
            fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            font=BODY_FONT,
            wrap="word",
        )

    def _apply_platform_tool_panel_inputs(self, platform: str, function_label: str) -> str:
        refs = self.platform_tool_input_refs.get(platform, {})
        action_value = self._platform_tool_action_value(platform, function_label)
        self.vars.action_var.set(action_value)

        caption_box = refs.get("caption_box")
        if isinstance(caption_box, tk.Text):
            caption = caption_box.get("1.0", "end").strip()
            self.vars.description_var.set(caption)
            self.vars.description_check_var.set(bool(caption))

        path_box = refs.get("path_box")
        if isinstance(path_box, tk.Text):
            self.vars.reel_folder_or_file_var.set(path_box.get("1.0", "end").strip())

        command_box = refs.get("command_box")
        command_text = command_box.get("1.0", "end").strip() if isinstance(command_box, tk.Text) else ""
        post_box = refs.get("post_box")
        if isinstance(post_box, tk.Text):
            command_text = post_box.get("1.0", "end").strip()
        if command_text:
            self.vars.post_text_var.set(command_text)
            if "group" in action_value:
                self.vars.group_urls_var.set(command_text)

        limit_var = refs.get("limit_var")
        if hasattr(limit_var, "get"):
            value = str(limit_var.get() or "").strip()
            if value:
                self.vars.share_group_count_var.set(value)

        post_type_var = refs.get("post_type_var")
        post_type = str(post_type_var.get() if hasattr(post_type_var, "get") else "").strip().lower()
        target_text = f"{function_label} {post_type} {action_value}".lower()
        self.vars.switch_reel_var.set("reel" in target_text)
        self.vars.switch_video_var.set("video" in target_text or "upload" in target_text)
        self.vars.switch_picture_var.set("photo" in target_text or "picture" in target_text or "cover" in target_text)
        self.vars.switch_share_var.set("share" in target_text or "group" in target_text)
        return action_value

    def _platform_tool_stat(self, platform: str, parent: Frame, label: str, value: str, color: str) -> None:
        card = Frame(parent, bg=color, width=96, height=58)
        card.pack(side=LEFT, padx=(6, 0))
        card.pack_propagate(False)
        Label(card, text=label, bg=color, fg=TEXT_ON_DARK, font=SMALL_FONT).pack(anchor="w", padx=10, pady=(7, 0))
        value_label = Label(card, text=value, bg=color, fg=TEXT_ON_DARK, font=("Bahnschrift SemiBold", 15))
        value_label.pack(
            anchor="w",
            padx=10,
        )
        self.platform_tool_stat_labels.setdefault(platform, {})[label] = value_label

    def _is_no_login_row(self, row: dict) -> bool:
        status = str(row.get("status", "")).strip().lower()
        reason = str(row.get("reason", "")).strip().lower()
        status_reason = f"{status} {reason}"
        return any(
            marker in status_reason
            for marker in (
                "login required",
                "login request",
                "login cookie was not found",
                "session cookie was not found",
                "no saved cookies",
                "no cookie",
                "returned a login page",
                "logged out",
                "not logged in",
                "not signed in",
            )
        )

    def _platform_default_publish_action(self, platform: str) -> str:
        if platform == "facebook":
            return "Login"
        if platform == "wordpress":
            return "Post Article"
        if platform == "instagram":
            return "Create Post"
        return "Upload Video"

    def _platform_tool_function_labels(self, platform: str) -> tuple[str, ...]:
        return tuple(label for label, _value in self.ACTIONS_BY_PLATFORM.get(platform, self.ACTIONS_BY_PLATFORM["facebook"]))

    def _platform_tool_action_value(self, platform: str, label: str) -> str:
        normalized = label.strip().lower()
        for action_label, action_value in self.ACTIONS_BY_PLATFORM.get(platform, []):
            if action_label.strip().lower() == normalized:
                return action_value
        if platform == "instagram":
            return "create_post"
        if platform == "wordpress":
            return "post_article"
        return "upload_video"

    def _platform_post_types_for_function(self, platform: str, function_label: str) -> tuple[str, ...]:
        normalized = str(function_label or "").strip().lower()
        if platform == "facebook":
            if "reel" in normalized:
                return ("Upload Reel", "Set New Path", "Post Video")
            if "photo" in normalized or "cover" in normalized:
                return ("Photo+Cover", "Set New Path", "Photo Mode")
            if "share" in normalized or "group" in normalized:
                return ("Share To Groups", "Post Text/Image/Video", "Set New Path")
            if "login" in normalized or "profile" in normalized or "home" in normalized:
                return ("Open Browser", "Set New Path")
            return ("Set New Path", "Post Text/Image/Video", "Upload Reel", "Photo+Cover", "Share To Groups")
        if platform == "youtube":
            if "short" in normalized:
                return ("Short", "Set New Path", "Video")
            return ("Video", "Short", "Set New Path", "Community Post")
        if platform == "instagram":
            if "reel" in normalized:
                return ("Reel", "Set New Path", "Post")
            if "story" in normalized:
                return ("Story", "Set New Path", "Post")
            return ("Post", "Reel", "Story", "Set New Path")
        if platform == "wordpress":
            return ("Article", "Draft", "Scheduled", "Page")
        return ("Set New Path", "Post Video", "Photo Mode")

    def _platform_post_types(self, platform: str) -> tuple[str, ...]:
        if platform == "facebook":
            return ("Post Text/Image/Video", "Upload Reel", "Photo+Cover")
        if platform == "youtube":
            return ("Video", "Short", "Community Post")
        if platform == "instagram":
            return ("Post", "Reel", "Story")
        if platform == "wordpress":
            return ("Article", "Draft", "Scheduled", "Page")
        return ("Set New Path", "Post Video", "Photo Mode")

    def _platform_default_post_type(self, platform: str) -> str:
        if platform == "facebook":
            return "Post Text/Image/Video"
        if platform == "youtube":
            return "Video"
        if platform == "instagram":
            return "Post"
        if platform == "wordpress":
            return "Article"
        return "Set New Path"

    def _refresh_platform_tool_accounts(self, platform: str) -> None:
        tree = self.platform_tool_trees.get(platform)
        if not tree:
            return
        selected_instances = {
            int(str(item))
            for item in tree.get_children()
            if str(tree.item(item, "values")[0]).strip() == "x"
            and str(item).isdigit()
        }
        for item in tree.get_children():
            tree.delete(item)
        account_type = self._selected_account_type()
        custom_type = self._selected_custom_account_type()
        total_count = 0
        success_count = 0
        failed_count = 0
        no_login_count = 0
        rows_by_instance: dict[int, dict] = {}
        for row in self.instances.get_report_rows():
            try:
                rows_by_instance[int(str(row.get("instance_id") or "0"))] = row
            except Exception:
                continue
        platform_column_keys = [key for key, _title, _width in platform_columns(platform)]
        for instance_number in self.instances.active_instance_numbers():
            report = self.state.instance_reports.get(instance_number, {})
            row = rows_by_instance.get(instance_number)
            if row is None:
                continue
            if account_type and not self.instances.instance_matches_account_type(instance_number, account_type):
                continue
            if custom_type and str(report.get("custom_account_type") or "").strip().lower() != custom_type.lower():
                continue
            account_status = self.instances.report_account_status(report)
            account_reason = str(report.get("account_reason") or report.get("last_note") or "")
            row_for_status = {"status": account_status, "reason": account_reason}
            total_count += 1
            normalized_status = account_status.strip().lower()
            if self._is_no_login_row(row_for_status):
                no_login_count += 1
            elif normalized_status in {"live", "done", "ready", "success", "cache cleared"}:
                success_count += 1
            elif any(
                marker in normalized_status
                for marker in ("checkpoint", "challenge", "verify", "disabled", "suspended", "locked", "die", "dead")
            ):
                failed_count += 1
            checked = "x" if instance_number in selected_instances else ""
            row_tags = self._report_row_tags(
                {
                    "status": account_status,
                    "reason": account_reason,
                    "country_type": report.get("account_type") or report.get("country") or "",
                    "account_type": report.get("custom_account_type") or "",
                },
                tree,
            )
            if checked:
                row_tags = tuple(tag for tag in row_tags if tag != "select") + ("select",)
            tree.insert(
                "",
                "end",
                iid=str(instance_number),
                values=(checked, *(self._report_value(row, key) for key in platform_column_keys)),
                tags=row_tags,
            )
        self._refresh_platform_tool_stats(platform, total_count, no_login_count, failed_count, success_count)

    def _refresh_platform_tool_stats(
        self,
        platform: str,
        total_count: int,
        no_login_count: int,
        failed_count: int,
        success_count: int,
    ) -> None:
        labels = self.platform_tool_stat_labels.get(platform, {})
        values = {
            "Total Post": total_count,
            "No Login": no_login_count,
            "Failed": failed_count,
            "Success": success_count,
        }
        for label, value in values.items():
            value_label = labels.get(label)
            if value_label:
                value_label.config(text=str(value))

    def _platform_tool_tree_click(self, event, platform: str) -> None:
        tree = self.platform_tool_trees.get(platform)
        if not tree:
            return None
        if tree.identify_region(event.x, event.y) == "heading":
            return None
        row_id = tree.identify_row(event.y)
        if not row_id:
            return None
        values = list(tree.item(row_id, "values"))
        selected = str(values[0]).strip() != "x"
        values[0] = "x" if selected else ""
        tree.item(row_id, values=values)
        tags = tuple(tag for tag in tree.item(row_id, "tags") if tag != "select")
        if selected:
            tags = tags + ("select",)
        tree.item(row_id, tags=tags)
        tree.selection_remove(tree.selection())
        return "break"

    def _platform_tool_toggle_all(self, platform: str, checked: bool) -> None:
        tree = self.platform_tool_trees.get(platform)
        if not tree:
            return
        for item in tree.get_children():
            values = list(tree.item(item, "values"))
            values[0] = "x" if checked else ""
            tags = tuple(tag for tag in tree.item(item, "tags") if tag != "select")
            if checked:
                tags = tags + ("select",)
            tree.item(item, values=values, tags=tags)

    def _platform_tool_selected_instances(self, platform: str, run_all: bool) -> list[int]:
        tree = self.platform_tool_trees.get(platform)
        if not tree:
            return []
        checked_row_ids = [
            item for item in tree.get_children() if str(tree.item(item, "values")[0]).strip() == "x"
        ]
        if checked_row_ids:
            row_ids = checked_row_ids
        elif run_all:
            row_ids = tree.get_children()
        else:
            row_ids = tree.selection()
        numbers: list[int] = []
        for item in row_ids:
            try:
                number = int(str(item))
            except Exception:
                values = tree.item(item, "values")
                if len(values) < 2:
                    continue
                number = self._instance_number_from_label(str(values[1]))
            if number is not None:
                numbers.append(number)
        return numbers

    def _run_platform_tool_selected(self, platform: str, function_label: str, run_all: bool) -> None:
        action_value = self._apply_platform_tool_panel_inputs(platform, function_label)
        selected_instances = self._platform_tool_selected_instances(platform, run_all)
        if not selected_instances:
            self._platform_tool_set_status(platform, "No account rows selected.")
            return
        self.vars.platform_var.set(platform)
        self.vars.action_var.set(action_value)
        self._render_action_buttons()
        self.refresh_dashboard()
        self._platform_tool_set_status(platform, f"Starting {len(selected_instances)} {self._platform_label()} session(s).")
        if platform == "facebook" and self._run_facebook_folder_action(function_label, action_value, selected_instances):
            self.root.after(500, lambda: self._refresh_platform_tool_accounts(platform))
            return
        for instance_number in selected_instances:
            threading.Thread(target=self.instances.run_firefox_instance, args=(instance_number,), daemon=True).start()
        self.root.after(500, lambda: self._refresh_platform_tool_accounts(platform))

    def _run_facebook_folder_action(self, function_label: str, action_value: str, instance_numbers: list[int]) -> bool:
        action_path = PLATFORM_FOLDER_DIRS["facebook"] / function_label / "action.py"
        if not action_path.exists():
            return False

        def worker() -> None:
            action_name = function_label.strip() or action_value
            for instance_number in instance_numbers:
                self.instances._update_instance_report(
                    instance_number,
                    action=action_name,
                    status="Running",
                    increment_run=True,
                )
                self.instances.set_run_status(instance_number, "Running", WARNING, persist_report=False)
            try:
                spec = importlib.util.spec_from_file_location(
                    f"fbv1_facebook_action_{action_value}",
                    action_path,
                )
                if spec is None or spec.loader is None:
                    raise RuntimeError(f"Cannot load action file: {action_path}")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                run_action = getattr(module, "run", None)
                if not callable(run_action):
                    raise RuntimeError(f"{action_path} does not define run(app, instance_numbers).")
                run_action(self, instance_numbers)
                done_status = "Ready" if action_value == "login" else "Done"
                for instance_number in instance_numbers:
                    self.instances.set_run_status(instance_number, done_status, SUCCESS)
            except Exception as exc:
                for instance_number in instance_numbers:
                    self.instances.set_run_status(instance_number, "Failed", DANGER)
                    self.instances._update_instance_report(
                        instance_number,
                        action=action_name,
                        status="Failed",
                        note=str(exc),
                    )
                self.root.after(0, lambda text=f"{action_name} failed: {exc}": self._platform_tool_set_status("facebook", text))
            finally:
                self.root.after(0, lambda: self._refresh_platform_tool_accounts("facebook"))

        threading.Thread(target=worker, daemon=True).start()
        return True

    def _clear_platform_tool_selected(self, platform: str) -> None:
        selected_instances = self._platform_tool_selected_instances(platform, run_all=False)
        if not selected_instances:
            self._platform_tool_set_status(platform, "No account rows selected.")
            return
        self._platform_tool_set_status(platform, f"Clearing data for {len(selected_instances)} session(s).")

        def worker(instance_number: int) -> None:
            self.browser.open_firefox_instance(
                instance_number,
                login=False,
                clear_data_action=True,
                sync_preview=False,
            )

        for instance_number in selected_instances:
            threading.Thread(target=worker, args=(instance_number,), daemon=True).start()
        self.root.after(500, lambda: self._refresh_platform_tool_accounts(platform))

    def _save_platform_tool_settings(self, platform: str) -> None:
        self.instances.save_instance_data()
        self._platform_tool_set_status(platform, "Settings saved.")

    def _platform_tool_set_status(self, platform: str, text: str) -> None:
        status_label = self.platform_tool_status_labels.get(platform)
        if status_label:
            status_label.config(text=text)

    def _close_platform_tool(self, platform: str) -> None:
        window = self.platform_tool_windows.pop(platform, None)
        self.platform_tool_trees.pop(platform, None)
        self.platform_tool_status_labels.pop(platform, None)
        self.platform_tool_stat_labels.pop(platform, None)
        self.platform_tool_input_refs.pop(platform, None)
        self.platform_tool_country_type_menus.pop(platform, None)
        self.platform_tool_account_type_menus.pop(platform, None)
        if window and window.winfo_exists():
            window.destroy()

    def _open_care_window(self) -> None:
        care_window = self.create_modal("Care Options", "520x470", modal=False)
        body = self.create_modal_card(
            care_window,
            "Care Options",
            "Configure watch, link, comment, and scroll settings without locking the browser window.",
        )

        self._styled_checkbutton(body, "Watch Video", self.vars.watch_video_var).pack(anchor="w")
        self._entry_row(body, "Number of Videos", self.vars.watch_count_var)
        self._hms_duration_row(body, "Watch Duration", self.vars.watch_duration_var, care_window, surface_bg=SURFACE_BG)
        self._styled_checkbutton(body, "Link Video", self.vars.link_video_var).pack(anchor="w", pady=(8, 0))
        self._entry_row(body, "Video Link", self.vars.video_link_var)

        comment_video_check = self._styled_checkbutton(body, "Comment on Video", self.vars.comment_video_var)
        comment_video_check.pack(anchor="w", pady=(8, 0))
        self._entry_row(body, "Comment Text", self.vars.comment_text_var)
        self._styled_checkbutton(body, "Share Video", self.vars.share_video_var).pack(anchor="w", pady=(8, 0))
        self._entry_row(body, "Share Title", self.vars.share_title_var)
        self._styled_checkbutton(body, "Scroll between Videos", self.vars.scroll_var).pack(anchor="w", pady=(8, 0))
        self._hms_duration_row(body, "Scroll Duration", self.vars.scroll_duration_var, care_window, surface_bg=SURFACE_BG)

        def toggle_interactions(*_args) -> None:
            state = "normal" if self.vars.link_video_var.get() else "disabled"
            comment_video_check.config(state=state)

        self.vars.link_video_var.trace_add("write", toggle_interactions)
        toggle_interactions()

        footer = Frame(body, bg=SURFACE_BG)
        footer.pack(fill=X, pady=(16, 0))
        self.create_button(
            footer,
            "Apply",
            lambda: self._set_backend_status("Care options updated.", kind="ok"),
            kind="primary",
        ).pack(side=LEFT)
        self.create_button(
            footer,
            "Close",
            care_window.destroy,
            kind="neutral",
        ).pack(side=LEFT, padx=(8, 0))

    def _open_join_group_window(self) -> None:
        join_group_window = self.create_modal("Join Group Options", "520x260")
        body = self.create_modal_card(
            join_group_window,
            "Join Group",
            "Add comma-separated group URLs for the current action.",
        )
        self._entry_row(body, "Group URLs", self.vars.group_urls_var, width=48)
        self.create_button(body, "Save", self.instances.save_instance_data, kind="primary").pack(anchor="w", pady=(16, 0))

    def _open_share_groups_window(self) -> None:
        share_to_groups_window = self.create_modal("Share to Groups", "560x360")
        body = self.create_modal_card(
            share_to_groups_window,
            "Share to Groups",
            "Configure video, destination groups, share count, and post text.",
        )
        self._entry_row(body, "Video Link", self.vars.video_link_var, width=48)
        self._entry_row(body, "Group URLs", self.vars.group_urls_var, width=48)
        self._entry_row(body, "Number of Times to Share", self.vars.share_group_count_var)
        self._entry_row(body, "Post Text", self.vars.post_text_var, width=48)

    def _open_upload_reel_window(self) -> None:
        upload_reel_window = self.create_modal("Upload Reel", "700x460")
        body = self.create_modal_card(
            upload_reel_window,
            "Upload Reel",
            "Choose upload mode, file inputs, page switching, and optional share fields.",
        )

        reel_frame = Frame(body, bg=SURFACE_BG)
        reel_frame.pack(fill=X)
        Label(reel_frame, text="Reel Video Files", bg=SURFACE_BG, fg=TEXT_MUTED, font=BODY_FONT).pack(side=LEFT)

        reel_entry = Entry(reel_frame, textvariable=self.vars.reel_folder_or_file_var, state="readonly")
        self.style_entry(reel_entry, width=46)
        reel_browse_button = self.create_button(reel_frame, "Browse", self.browse_files, kind="secondary", compact=True)

        page_link_frame = Frame(body, bg=SURFACE_BG)
        description_frame = Frame(body, bg=SURFACE_BG)
        share_video_frame = Frame(body, bg=SURFACE_BG)
        share_count_frame = Frame(body, bg=SURFACE_BG)
        post_text_frame = Frame(body, bg=SURFACE_BG)

        page_link_label = Label(page_link_frame, text="Page Link or ID", bg=SURFACE_BG, fg=TEXT_MUTED, font=BODY_FONT)
        page_link_entry = Entry(page_link_frame, textvariable=self.vars.page_link_var)
        self.style_entry(page_link_entry, width=42)
        switch_page_checkbutton = self._styled_checkbutton(page_link_frame, "Switch Page", self.vars.switch_page_var)

        description_label = Label(description_frame, text="Reel Description", bg=SURFACE_BG, fg=TEXT_MUTED, font=BODY_FONT)
        description_entry = Entry(description_frame, textvariable=self.vars.description_var)
        self.style_entry(description_entry, width=42)
        description_checkbutton = self._styled_checkbutton(description_frame, "Include Description", self.vars.description_check_var)

        Label(share_video_frame, text="Video Link", bg=SURFACE_BG, fg=TEXT_MUTED, font=BODY_FONT).pack(side=LEFT)
        share_video_entry = Entry(share_video_frame, textvariable=self.vars.video_link_var)
        self.style_entry(share_video_entry, width=42)
        share_video_entry.pack(side=LEFT, padx=(12, 0))

        Label(share_count_frame, text="Number of Times to Share", bg=SURFACE_BG, fg=TEXT_MUTED, font=BODY_FONT).pack(side=LEFT)
        share_count_entry = Entry(share_count_frame, textvariable=self.vars.share_group_count_var)
        self.style_entry(share_count_entry, width=10)
        share_count_entry.pack(side=LEFT, padx=(12, 0))

        Label(post_text_frame, text="Text to Share with Video", bg=SURFACE_BG, fg=TEXT_MUTED, font=BODY_FONT).pack(side=LEFT)
        post_text_entry = Entry(post_text_frame, textvariable=self.vars.post_text_var)
        self.style_entry(post_text_entry, width=42)
        post_text_entry.pack(side=LEFT, padx=(12, 0))

        def toggle_browse_button() -> None:
            if self.vars.switch_reel_var.get():
                reel_entry.pack(side=LEFT, padx=(12, 0))
                reel_browse_button.pack(side=LEFT, padx=(8, 0))
            else:
                reel_entry.pack_forget()
                reel_browse_button.pack_forget()

            if self.vars.switch_share_var.get():
                page_link_frame.pack_forget()
                description_frame.pack_forget()
                share_video_frame.pack(fill=X, pady=8)
                share_count_frame.pack(fill=X, pady=8)
                post_text_frame.pack(fill=X, pady=8)
            else:
                share_video_frame.pack_forget()
                share_count_frame.pack_forget()
                post_text_frame.pack_forget()
                page_link_frame.pack(fill=X, pady=8)
                description_frame.pack(fill=X, pady=8)

            if self.vars.switch_video_var.get():
                page_link_label.pack_forget()
                page_link_entry.pack_forget()
                switch_page_checkbutton.pack_forget()
            else:
                if not page_link_label.winfo_ismapped():
                    page_link_label.pack(side=LEFT)
                if not page_link_entry.winfo_ismapped():
                    page_link_entry.pack(side=LEFT, padx=(12, 0))
                if not switch_page_checkbutton.winfo_ismapped():
                    switch_page_checkbutton.pack(side=LEFT, padx=(12, 0))

        self._styled_checkbutton(reel_frame, "Reel", self.vars.switch_reel_var).pack(side=LEFT, padx=(16, 0))
        self._styled_checkbutton(reel_frame, "Video/Picture", self.vars.switch_video_var).pack(side=LEFT, padx=(8, 0))
        self._styled_checkbutton(reel_frame, "Share", self.vars.switch_share_var).pack(side=LEFT, padx=(8, 0))

        page_link_label.pack(side=LEFT)
        page_link_entry.pack(side=LEFT, padx=(12, 0))
        switch_page_checkbutton.pack(side=LEFT, padx=(12, 0))

        description_label.pack(side=LEFT)
        description_entry.pack(side=LEFT, padx=(12, 0))
        description_checkbutton.pack(side=LEFT, padx=(12, 0))

        toggle_browse_button()

    def _entry_row(self, parent: Frame, label_text: str, variable, width: int = 28) -> Entry:
        row = Frame(parent, bg=SURFACE_BG)
        row.pack(fill=X, pady=8)
        Label(row, text=label_text, bg=SURFACE_BG, fg=TEXT_MUTED, font=BODY_FONT).pack(side=LEFT)
        entry = Entry(row, textvariable=variable)
        self.style_entry(entry, width=width)
        entry.pack(side=LEFT, padx=(12, 0))
        return entry

    def _hms_duration_row(self, parent: Frame, label_text: str, target_var, master, surface_bg: str = SURFACE_ALT) -> None:
        row = Frame(parent, bg=surface_bg)
        row.pack(fill=X, pady=5)
        Label(row, text=label_text, bg=surface_bg, fg=TEXT_MUTED, font=SMALL_FONT, width=18, anchor="w").pack(side=LEFT)

        hours, minutes, seconds = self._seconds_to_hms(target_var.get())
        hour_var = tk.StringVar(master=master, value=str(hours))
        minute_var = tk.StringVar(master=master, value=str(minutes))
        second_var = tk.StringVar(master=master, value=str(seconds))

        def sync_total_seconds(*_args) -> None:
            try:
                total = max(0, int(hour_var.get() or 0)) * 3600
                total += max(0, int(minute_var.get() or 0)) * 60
                total += max(0, int(second_var.get() or 0))
            except ValueError:
                return
            target_var.set(str(total))

        for text, var in (("H", hour_var), ("M", minute_var), ("S", second_var)):
            entry = Entry(row, textvariable=var)
            self.style_entry(entry, width=4)
            entry.pack(side=LEFT, padx=(8, 3))
            Label(row, text=text, bg=surface_bg, fg=TEXT_MUTED, font=SMALL_FONT).pack(side=LEFT)
            var.trace_add("write", sync_total_seconds)

        sync_total_seconds()

    def _seconds_to_hms(self, value: str) -> tuple[int, int, int]:
        try:
            total_seconds = max(0, int(float(str(value or "0").strip() or 0)))
        except ValueError:
            total_seconds = 0
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return hours, minutes, seconds

    def browse_files(self) -> None:
        file_paths = filedialog.askopenfilenames(
            filetypes=[("Video files", "*.mp4;*.mov"), ("Image files", "*.jpg;*.jpeg;*.png")]
        )
        if file_paths:
            self.vars.reel_folder_or_file_var.set(",".join(file_paths))
            print(f"Selected files: {file_paths}")

    def save_reel_upload_inputs(self) -> None:
        if not self.vars.switch_reel_var.get() and not self.vars.switch_video_var.get() and not self.vars.switch_picture_var.get():
            print("Error: No upload type selected.")
            return

        for video_path in self.vars.reel_folder_or_file_var.get().split(","):
            if video_path and not os.path.exists(video_path):
                print(f"Error: Path does not exist: {video_path}")
                return

        page_link = self.vars.page_link_var.get().strip()
        if self.vars.switch_page_var.get() and not page_link:
            print("Error: Page link or ID cannot be empty.")
            return

        print("Upload inputs saved successfully.")
