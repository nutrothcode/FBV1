from __future__ import annotations


def run(app, instance_numbers: list[int]) -> None:
    """Share configured video/text to the configured Facebook groups."""
    group_urls = [url.strip() for url in app.vars.group_urls_var.get().split(",") if url.strip()]
    if not group_urls:
        raise ValueError("Group URLs required for Share to Groups.")
    if not app.vars.video_link_var.get().strip() and not app.vars.post_text_var.get().strip():
        raise ValueError("Video Link or Post Text required for Share to Groups.")
    if not app.vars.share_group_count_var.get().strip():
        app.vars.share_group_count_var.set("1")
    for instance_number in instance_numbers:
        app.browser.open_firefox_instance(instance_number, login=False, sync_preview=False)
    app.actions.share_to_facebook_groups(instance_numbers)
