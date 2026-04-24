from __future__ import annotations

import os
import threading
import tkinter as tk
import tkinter.ttk as ttk
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
from .config import ICON_PATH, LOGO_PATH
from .facebook_actions import FacebookActions
from .instance_manager import InstanceManager
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
    HEADER_BG,
    INPUT_BG,
    NEUTRAL_HOVER,
    SECTION_FONT,
    SIDEBAR_BG,
    SIDEBAR_PANEL_BG,
    SMALL_FONT,
    SECONDARY,
    SURFACE_ALT,
    SURFACE_BG,
    TEXT_MUTED,
    TEXT_ON_DARK,
    TEXT_PRIMARY,
    TEXT_SUBTLE,
    TITLE_FONT,
)


class FacebookToolApp:
    ACTIONS = [
        ("Login", "login"),
        ("Care", "care"),
        ("Clear Data", "clear_data"),
        ("Join Group", "join_group"),
        ("Upload Reel", "upload_reel"),
        ("Share to Groups", "share_to_groups"),
        ("Get ID", "get_id"),
        ("Change Gmail", "get_gmail"),
        ("Date Create FB", "get_date"),
        ("Upload Photo+Cover", "upload_photo_cover"),
    ]

    def __init__(self) -> None:
        self.Frame = Frame
        self.Button = Button
        self.Label = Label
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.simpledialog = simpledialog

        self.root = tk.Tk()
        self.root.title("FBV2 Ops Console")
        self.root.geometry("1360x820")
        self.root.minsize(1140, 720)
        self.root.configure(bg=APP_BG)
        self._configure_default_fonts()

        self.state = AppState()
        self.vars = AppVars(self.root)
        self._icon_photo = None
        self.action_buttons: dict[str, Button] = {}
        self.active_count_label: Label | None = None
        self.deleted_count_label: Label | None = None
        self.current_action_label: Label | None = None
        self.workspace_title_label: Label | None = None
        self.image_toggle_button: Button | None = None
        self.profiles_tab_button: Button | None = None
        self.report_tab_button: Button | None = None
        self.workspace_tab: str = "profiles"
        self.report_tree = None

        self._apply_icon()
        self._build_layout()

        self.browser = BrowserManager(self)
        self.actions = FacebookActions(self)
        self.instances = InstanceManager(self)

        self._build_controls()
        self.instances.initialize_app()
        self.refresh_dashboard()

    def run(self) -> None:
        self.root.mainloop()

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
        self._build_header()

        self.main_frame = Frame(self.root, bg=APP_BG)
        self.main_frame.pack(fill=BOTH, expand=True, padx=12, pady=(0, 12))

        self.sidebar = Frame(
            self.main_frame,
            bg=SIDEBAR_BG,
            width=292,
            highlightbackground=BORDER,
            highlightthickness=1,
            bd=0,
        )
        self.sidebar.pack(side=LEFT, fill=Y)
        self.sidebar.pack_propagate(False)

        self.workspace = Frame(self.main_frame, bg=APP_BG)
        self.workspace.pack(side=RIGHT, fill=BOTH, expand=True, padx=(12, 0))

        self._build_workspace()

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

        Label(text_wrap, text="FBV2 OPS CONSOLE", bg=HEADER_BG, fg=TEXT_PRIMARY, font=TITLE_FONT).pack(anchor="w")
        Label(
            text_wrap,
            text="Run, monitor, and control profile sessions from one console.",
            bg=HEADER_BG,
            fg=TEXT_MUTED,
            font=BODY_FONT,
        ).pack(anchor="w", pady=(2, 0))

        self.current_action_label = Label(
            header,
            text="LOGIN",
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
        Label(
            header_left,
            text="Launch, rename, delete, and review Firefox profiles below.",
            bg=SURFACE_BG,
            fg=TEXT_MUTED,
            font=BODY_FONT,
        ).pack(anchor="w", pady=(2, 0))

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
        Label(toolbar, text="Firefox Profiles", bg=SURFACE_BG, fg=TEXT_PRIMARY, font=SECTION_FONT).pack(side=LEFT, padx=(0, 10))
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
        self.create_button(
            toolbar,
            text="Reset Table",
            command=self._reset_report_data,
            kind="danger",
            compact=True,
        ).pack(side=LEFT, padx=(6, 0))
        Label(
            toolbar,
            text="Each card shows account media preview and quick operator actions.",
            bg=SURFACE_BG,
            fg=TEXT_MUTED,
            font=SMALL_FONT,
        ).pack(side=RIGHT)

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

        columns = (
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
        )
        self.report_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", style="Report.Treeview")
        headings = {
            "instance": ("Firefox", 100),
            "profile": ("Account Name", 170),
            "account_id": ("Account ID", 140),
            "date_birth": ("Date Birth", 120),
            "gender": ("Gender", 90),
            "gmail": ("Gmail", 220),
            "action": ("Last Action", 130),
            "status": ("Status", 120),
            "runs": ("Runs", 70),
            "done": ("Done", 70),
            "failed": ("Failed", 70),
            "updated": ("Updated", 170),
        }
        for column, (title, width) in headings.items():
            self.report_tree.heading(column, text=title)
            self.report_tree.column(column, width=width, anchor="w")

        scroll_y = Scrollbar(tree_frame, orient="vertical", command=self.report_tree.yview)
        scroll_x = Scrollbar(tree_frame, orient="horizontal", command=self.report_tree.xview)
        self.report_tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self.report_tree.pack(side=LEFT, fill=BOTH, expand=True)
        scroll_y.pack(side=RIGHT, fill=Y)
        scroll_x.pack(side="bottom", fill=X)

    def switch_workspace_tab(self, tab_name: str) -> None:
        self.workspace_tab = tab_name
        if hasattr(self, "profiles_panel"):
            self.profiles_panel.pack_forget()
        if hasattr(self, "table_panel"):
            self.table_panel.pack_forget()

        if tab_name == "table":
            self.table_panel.pack(fill=BOTH, expand=True)
            self.refresh_report_table()
        else:
            self.profiles_panel.pack(fill=BOTH, expand=True)
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

    def refresh_report_table_async(self) -> None:
        try:
            self.root.after(0, self.refresh_report_table)
        except Exception:
            pass

    def refresh_report_table(self) -> None:
        if not self.report_tree:
            return
        for item in self.report_tree.get_children():
            self.report_tree.delete(item)
        for row in self.instances.get_report_rows():
            values = (
                row["instance"],
                row["profile"],
                row["account_id"],
                row["date_birth"],
                row["gender"],
                row["gmail"],
                row["action"],
                row["status"],
                row["runs"],
                row["done"],
                row["failed"],
                row["updated"],
            )
            self.report_tree.insert("", "end", values=values)

    def _reset_report_data(self) -> None:
        instances = getattr(self, "instances", None)
        if instances is None:
            return
        instances.reset_report_data()

    def _build_controls(self) -> None:
        self._build_sidebar_section(
            "Control Hub",
            [
                ("Generate Firefox Instances", self.instances.generate_firefox_instances, "primary"),
                ("Enter Credentials", self.enter_credentials, "secondary"),
                ("Photo/Cover Setup", self._open_photo_cover_setup_window, "secondary"),
                ("Open Folder", self.instances.open_data_folder, "neutral"),
                ("Run Firefox", self.run_firefox_dialog, "success"),
                ("Delete Account", self.instances.delete_multiple_instances, "danger"),
            ],
            description="Generate, import, execute, and manage Firefox profile sessions.",
        )

        action_section = self._create_sidebar_section(
            "Action Mode",
            description="Select a mode, then click a profile card to run.",
        )
        for label, value in self.ACTIONS:
            button = self.create_button(
                action_section,
                text=label,
                command=lambda value=value: self._select_action(value),
                kind="sidebar",
                compact=True,
                full_width=True,
            )
            button.pack(fill=X, pady=1)
            self.action_buttons[value] = button

        self._refresh_action_buttons()

    def _build_sidebar_section(self, title: str, buttons: list[tuple[str, object, str]], description: str = "") -> None:
        section = self._create_sidebar_section(title, description=description)
        for label, command, kind in buttons:
            self.create_button(
                section,
                text=label,
                command=command,
                kind=kind,
                compact=True,
                full_width=True,
            ).pack(fill=X, pady=1)

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

    def style_entry(self, entry: Entry, width: int | None = None) -> Entry:
        entry.configure(
            relief="flat",
            bd=0,
            bg=INPUT_BG,
            fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            font=BODY_FONT,
        )
        if width is not None:
            entry.configure(width=width)
        return entry

    def create_modal(self, title: str, geometry: str = "620x420") -> Toplevel:
        window = Toplevel(self.root)
        window.title(title)
        window.configure(bg=APP_BG)
        window.transient(self.root)
        window.resizable(False, False)
        self._center_modal(window, geometry)
        window.focus_set()
        window.grab_set()
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
        active_count = sum(1 for _button, frame in self.state.firefox_buttons if frame is not None)
        deleted_count = len(self.state.deleted_instances)
        action_value = self.vars.action_var.get().replace("_", " ").title()

        if self.active_count_label:
            self.active_count_label.config(text=str(active_count))
        if self.deleted_count_label:
            self.deleted_count_label.config(text=str(deleted_count))
        if self.current_action_label:
            self.current_action_label.config(text=action_value.upper())
        if self.workspace_title_label:
            self.workspace_title_label.config(text=f"Profiles Workspace | {action_value}")
        self._refresh_image_toggle_button()
        self._refresh_workspace_tab_buttons()
        self.refresh_report_table()

        self._refresh_action_buttons()

    def toggle_media_previews(self) -> None:
        self.state.show_media_previews = not self.state.show_media_previews
        self._refresh_image_toggle_button()
        self.instances.reload_all_media()

    def _refresh_image_toggle_button(self) -> None:
        if not self.image_toggle_button:
            return
        if self.state.show_media_previews:
            self.image_toggle_button.config(text="Hide Images")
        else:
            self.image_toggle_button.config(text="Show Images")

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
        credentials_window = self.create_modal("Enter Credentials", "760x560")
        body = self.create_modal_card(
            credentials_window,
            "Account Credentials",
            "Edit saved credentials in the format email|password|2fa.",
        )

        canvas = Canvas(body, bg=SURFACE_BG, bd=0, highlightthickness=0)
        scroll_y = Scrollbar(body, orient="vertical", command=canvas.yview)
        frame = Frame(canvas, bg=SURFACE_BG)
        self.state.credential_entries.clear()

        max_instance = max(
            (i for i in range(1, len(self.state.firefox_buttons) + 1) if i not in self.state.deleted_instances),
            default=0,
        )
        for instance_number in range(1, max_instance + 1):
            if instance_number in self.state.deleted_instances:
                continue

            row = Frame(frame, bg=SURFACE_ALT, highlightbackground=BORDER, highlightthickness=1)
            row.pack(fill=X, pady=6)
            Label(
                row,
                text=f"Firefox {instance_number}",
                bg=SURFACE_ALT,
                fg=TEXT_PRIMARY,
                font=SECTION_FONT,
                width=14,
                anchor="w",
            ).pack(side=LEFT, padx=(12, 8), pady=10)
            entry = Entry(row)
            self.style_entry(entry)
            entry.pack(side=LEFT, fill=X, expand=True, padx=(0, 12), pady=10)
            entry.insert(0, self.state.credentials_dict.get(instance_number, ""))
            self.state.credential_entries[instance_number] = entry

        frame.update_idletasks()
        canvas.create_window(0, 0, anchor="nw", window=frame)
        canvas.update_idletasks()
        canvas.config(scrollregion=canvas.bbox("all"), yscrollcommand=scroll_y.set)
        canvas.pack(fill=BOTH, expand=True, side=LEFT)
        scroll_y.pack(fill=Y, side=RIGHT, padx=(10, 0))

        footer = Frame(body, bg=SURFACE_BG)
        footer.pack(fill=X, pady=(16, 0))
        self.create_button(footer, "Save", self.save_credentials, kind="primary").pack(side=LEFT)
        self.create_button(footer, "Paste Input", self.open_input_window, kind="secondary").pack(side=LEFT, padx=8)
        self.create_button(footer, "Export Excel", self.export_credentials_to_excel, kind="neutral").pack(side=LEFT)

    def save_credentials(self) -> None:
        self.instances.save_credentials_from_entries()
        messagebox.showinfo("Success", "Credentials successfully saved!")

    def open_input_window(self) -> None:
        input_window = self.create_modal("Paste Accounts", "760x440")
        body = self.create_modal_card(
            input_window,
            "Bulk Account Import",
            "Paste one account per line with: instance_id<TAB>credential.",
        )

        input_text = tk.Text(
            body,
            width=100,
            height=18,
            bg=INPUT_BG,
            fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY,
            relief="flat",
            font=BODY_FONT,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        input_text.pack(fill=BOTH, expand=True)

        def save_input() -> None:
            pasted_text = input_text.get("1.0", tk.END).strip().split("\n")
            for line in pasted_text:
                parts = line.split("\t")
                if len(parts) != 2:
                    continue
                instance_number = int(parts[0])
                credential = parts[1]
                self.state.credentials_dict[instance_number] = credential
                if instance_number in self.state.credential_entries:
                    entry = self.state.credential_entries[instance_number]
                    entry.delete(0, tk.END)
                    entry.insert(0, credential)

            self.instances.save_instance_data()
            input_window.destroy()

        footer = Frame(body, bg=SURFACE_BG)
        footer.pack(fill=X, pady=(14, 0))
        self.create_button(footer, "Save Import", save_input, kind="primary").pack(side=LEFT)

    def export_credentials_to_excel(self) -> None:
        export_window = self.create_modal("Export Credentials", "420x220")
        body = self.create_modal_card(
            export_window,
            "Export to Excel",
            "Enter a range like 1-50 to export saved credentials.",
        )

        range_entry = Entry(body)
        self.style_entry(range_entry, width=28)
        range_entry.pack(anchor="w")

        def export() -> None:
            range_str = range_entry.get().strip()
            try:
                start, end = map(int, range_str.split("-"))
                data = {"ID": [], "Account": []}
                for i in range(start, end + 1):
                    if i in self.state.credentials_dict:
                        data["ID"].append(i)
                        data["Account"].append(self.state.credentials_dict[i])
                pd.DataFrame(data).to_excel("account.xlsx", index=False)
                messagebox.showinfo("Success", "Credentials exported successfully!")
            except Exception as exc:
                messagebox.showerror("Error", f"Failed to export credentials: {exc}")

        self.create_button(body, "Export", export, kind="primary").pack(anchor="w", pady=(14, 0))

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

    def _open_care_window(self) -> None:
        care_window = self.create_modal("Care Options", "520x430")
        body = self.create_modal_card(
            care_window,
            "Care Options",
            "Configure watch, link, comment, and scroll settings.",
        )

        self._styled_checkbutton(body, "Watch Video", self.vars.watch_video_var).pack(anchor="w")
        self._entry_row(body, "Number of Videos", self.vars.watch_count_var)
        self._entry_row(body, "Duration per Video (seconds)", self.vars.watch_duration_var)
        self._styled_checkbutton(body, "Link Video", self.vars.link_video_var).pack(anchor="w", pady=(8, 0))
        self._entry_row(body, "Video Link", self.vars.video_link_var)

        comment_video_check = self._styled_checkbutton(body, "Comment on Video", self.vars.comment_video_var)
        comment_video_check.pack(anchor="w", pady=(8, 0))
        self._entry_row(body, "Comment Text", self.vars.comment_text_var)
        self._styled_checkbutton(body, "Scroll between Videos", self.vars.scroll_var).pack(anchor="w", pady=(8, 0))
        self._entry_row(body, "Scroll Duration (seconds)", self.vars.scroll_duration_var)

        def toggle_interactions(*_args) -> None:
            state = "normal" if self.vars.link_video_var.get() else "disabled"
            comment_video_check.config(state=state)

        self.vars.link_video_var.trace_add("write", toggle_interactions)
        toggle_interactions()

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
