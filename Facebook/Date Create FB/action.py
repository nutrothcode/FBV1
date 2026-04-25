from __future__ import annotations


def run(app, instance_numbers: list[int]) -> None:
    """Open Facebook personal information page used by FBV2 date-created workflow."""
    for instance_number in instance_numbers:
        app.browser.open_firefox_instance(
            instance_number,
            login=False,
            start_url="https://www.facebook.com/your_information/?tab=your_information&tile=personal_info_grouping",
            sync_preview=False,
        )
