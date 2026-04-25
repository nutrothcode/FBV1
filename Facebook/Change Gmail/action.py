from __future__ import annotations


def run(app, instance_numbers: list[int]) -> None:
    """Open Meta Accounts Center personal info for selected accounts."""
    for instance_number in instance_numbers:
        app.browser.open_firefox_instance(
            instance_number,
            login=False,
            start_url="https://accountscenter.facebook.com/personal_info",
            sync_preview=False,
        )
