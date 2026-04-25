from __future__ import annotations


def run(app, instance_numbers: list[int]) -> None:
    """Run the Facebook care/watch workflow from the legacy FBV2 tool."""
    if not app.vars.watch_count_var.get().strip():
        app.vars.watch_count_var.set("1")
    if not app.vars.watch_duration_var.get().strip():
        app.vars.watch_duration_var.set("30")
    if not app.vars.scroll_duration_var.get().strip():
        app.vars.scroll_duration_var.set("0")
    for instance_number in instance_numbers:
        app.browser.open_firefox_instance(instance_number, login=False, sync_preview=False)
    app.actions.watch_facebook_videos(instance_numbers)
