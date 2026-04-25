from __future__ import annotations


def run(app, instance_numbers: list[int]) -> None:
    """Upload per-account profile photo and cover assignments."""
    if not any(app.state.photo_upload_paths.get(number) or app.state.cover_upload_paths.get(number) for number in instance_numbers):
        raise ValueError("No photo or cover assigned. Open Photo/Cover Setup first.")
    for instance_number in instance_numbers:
        app.browser.open_firefox_instance(instance_number, login=False, sync_preview=False)
        photo_path = app.state.photo_upload_paths.get(instance_number, "")
        cover_path = app.state.cover_upload_paths.get(instance_number, "")
        description = app.state.photo_upload_descriptions.get(instance_number, "")
        if not photo_path and not cover_path:
            app.instances.set_run_status(instance_number, "Skipped", "#64748b")
            continue
        uploaded = app.browser.upload_profile_media(
            instance_number,
            photo_path=photo_path,
            cover_path=cover_path,
            profile_description=description,
        )
        if not uploaded:
            raise RuntimeError(f"Photo/Cover upload failed for Firefox {instance_number}.")
