from __future__ import annotations


def run(app, instance_numbers: list[int]) -> None:
    """Open profile About/Contact screen and collect account ID when available."""
    for instance_number in instance_numbers:
        app.browser.open_firefox_instance(instance_number, login=False, sync_preview=False)
        app.browser.get_id(instance_number)
