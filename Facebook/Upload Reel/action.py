from __future__ import annotations

import os


def run(app, instance_numbers: list[int]) -> None:
    """Upload reels/videos using app.vars.reel_folder_or_file_var and description settings."""
    if not app.vars.switch_reel_var.get() and not app.vars.switch_video_var.get() and not app.vars.switch_share_var.get():
        app.vars.switch_reel_var.set(True)
    file_paths = [path.strip() for path in app.vars.reel_folder_or_file_var.get().split(",") if path.strip()]
    if app.vars.switch_reel_var.get() or app.vars.switch_video_var.get():
        if not file_paths:
            raise ValueError("Video file path required for Upload Reel.")
        missing = [path for path in file_paths if not os.path.exists(path)]
        if missing:
            raise ValueError(f"Video file not found: {missing[0]}")
    if app.vars.description_var.get().strip():
        app.vars.description_check_var.set(True)
    for instance_number in instance_numbers:
        app.browser.open_firefox_instance(instance_number, login=False, sync_preview=False)
    app.actions.upload_facebook_reel(instance_numbers)
