from __future__ import annotations


def run(app, instance_numbers: list[int]) -> None:
    """Join the group URLs configured in app.vars.group_urls_var."""
    group_urls = [url.strip() for url in app.vars.group_urls_var.get().split(",") if url.strip()]
    if not group_urls:
        raise ValueError("Group URLs required for Join Group.")
    for instance_number in instance_numbers:
        app.browser.open_firefox_instance(instance_number, login=False, sync_preview=False)
    app.actions.join_facebook_groups(instance_numbers)
