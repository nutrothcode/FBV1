from __future__ import annotations


def run(app, instance_numbers: list[int]) -> None:
    """Clear browser data for selected Facebook profiles."""
    for instance_number in instance_numbers:
        app.browser.open_firefox_instance(instance_number, login=False, clear_data_action=True, sync_preview=False)
