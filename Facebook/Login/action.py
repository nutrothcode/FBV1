from __future__ import annotations


def run(app, instance_numbers: list[int]) -> None:
    """Open selected Facebook profiles and prepare login."""
    for instance_number in instance_numbers:
        app.browser.open_firefox_instance(instance_number, sync_preview=False)
