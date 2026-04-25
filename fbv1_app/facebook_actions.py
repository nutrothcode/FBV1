from __future__ import annotations

import logging
import os
import threading
import time
from typing import TYPE_CHECKING

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .theme import DANGER, SUCCESS, WARNING

if TYPE_CHECKING:
    from .ui import FacebookToolApp


class FacebookActions:
    def __init__(self, app: "FacebookToolApp") -> None:
        self.app = app

    @property
    def state(self):
        return self.app.state

    @property
    def vars(self):
        return self.app.vars

    def run_multiple_firefox(self) -> None:
        args = self._validate_run_inputs()
        if not args:
            return
        start_instance, end_instance, max_instances = args

        if self.state.batch_running:
            self.app.messagebox.showwarning("Batch Runner", "A run is already in progress.")
            return

        self.state.batch_running = True
        self.state.batch_stop_requested = False
        self.state.run_summary.clear()

        def worker() -> None:
            next_instance = start_instance
            try:
                while next_instance <= end_instance and not self.state.batch_stop_requested:
                    while (
                        not self.state.batch_stop_requested
                        and self._count_running_instances(start_instance, end_instance) >= max_instances
                    ):
                        time.sleep(0.5)

                    if self.state.batch_stop_requested:
                        break

                    threading.Thread(
                        target=self.app.instances.run_firefox_instance,
                        args=(next_instance,),
                        daemon=True,
                    ).start()
                    self.state.run_summary.append(f"Firefox {next_instance}: Started")
                    self.app.instances.set_run_status(next_instance, "Launching", WARNING)
                    next_instance += 1
                    time.sleep(0.2)
            finally:
                if self.state.batch_stop_requested:
                    self.state.run_summary.append("Batch stopped by user.")
                self.state.batch_running = False
                self.state.batch_stop_requested = False

        threading.Thread(target=worker, daemon=True).start()

    def run_one_firefox_batch(self) -> None:
        args = self._validate_run_inputs()
        if not args:
            return
        start_instance, end_instance, max_instances = args

        batch_end = min(start_instance + max_instances - 1, end_instance)
        for instance_number in range(start_instance, batch_end + 1):
            threading.Thread(
                target=self.app.instances.run_firefox_instance,
                args=(instance_number,),
                daemon=True,
            ).start()
            self.app.instances.set_run_status(instance_number, "Launching", WARNING)
            time.sleep(0.2)

        if batch_end < end_instance:
            self.vars.start_instance_var.set(batch_end + 1)

    def run_multiple_firefox_with_limits(self) -> None:
        self.run_multiple_firefox()

    def run_multiple_firefox_with_time(self) -> None:
        args = self._validate_run_inputs()
        if not args:
            return
        start_instance, end_instance, max_instances = args

        if self.state.batch_running:
            self.app.messagebox.showwarning("Batch Runner", "A run is already in progress.")
            return

        self.state.batch_running = True
        self.state.batch_stop_requested = False
        self.state.run_summary.clear()
        running_instances: set[int] = set()
        running_lock = threading.Lock()

        def run_and_wait(instance_number: int) -> None:
            try:
                self.app.instances.run_firefox_instance(instance_number)
                time.sleep(5)
                self.watch_facebook_videos([instance_number])
                driver = self.state.drivers.get(instance_number)
                if driver:
                    driver.quit()
                    self.state.drivers.pop(instance_number, None)
                    logging.info("Firefox %s has been closed.", instance_number)
                    self.state.run_summary.append(f"Firefox {instance_number}: Success")
                    self.app.instances.set_run_status(instance_number, "Done", SUCCESS)
                else:
                    self.state.run_summary.append(f"Firefox {instance_number}: Error or Login failed")
                    self.app.instances.set_run_status(instance_number, "Failed", DANGER)
            finally:
                with running_lock:
                    running_instances.discard(instance_number)

        def worker() -> None:
            next_instance = start_instance
            try:
                while next_instance <= end_instance and not self.state.batch_stop_requested:
                    with running_lock:
                        current_running = len(running_instances)
                    if current_running >= max_instances:
                        time.sleep(0.5)
                        continue

                    with running_lock:
                        running_instances.add(next_instance)
                    threading.Thread(target=run_and_wait, args=(next_instance,), daemon=True).start()
                    next_instance += 1
                    time.sleep(1.0)

                while True:
                    with running_lock:
                        if not running_instances:
                            break
                    time.sleep(0.5)
            finally:
                if self.state.batch_stop_requested:
                    self.state.run_summary.append("Timed batch stopped by user.")
                self.state.batch_running = False
                self.state.batch_stop_requested = False

        threading.Thread(target=worker, daemon=True).start()

    def request_stop_batch(self) -> None:
        self.state.batch_stop_requested = True
        for instance_number, state_text in list(self.state.run_states.items()):
            if state_text.lower() in {"queued", "launching"}:
                self.app.instances.set_run_status(instance_number, "Stopped", WARNING)

    def _validate_run_inputs(self) -> tuple[int, int, int] | None:
        start_instance = self.vars.start_instance_var.get()
        end_instance = self.vars.end_instance_var.get()
        max_instances = self.vars.max_instances_var.get()

        if start_instance <= 0 or end_instance <= 0 or max_instances <= 0:
            self.app.messagebox.showerror("Batch Runner", "Start, End, and Max On Screen must be greater than 0.")
            return None
        if start_instance > end_instance:
            self.app.messagebox.showerror("Batch Runner", "Start Instance must be less than or equal to End Instance.")
            return None
        return start_instance, end_instance, max_instances

    def _count_running_instances(self, start_instance: int, end_instance: int) -> int:
        return self.app.browser.count_active_instances(start_instance, end_instance)

    def _int_from_var(self, value, default: int = 0) -> int:
        try:
            return max(0, int(float(str(value.get()).strip() or default)))
        except (TypeError, ValueError):
            return default

    def _find_clickable(self, driver, locators: list[tuple[str, str]], timeout: float = 4):
        for by, selector in locators:
            try:
                return WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((by, selector)))
            except Exception:
                continue
        return None

    def _find_present(self, driver, locators: list[tuple[str, str]], timeout: float = 4):
        for by, selector in locators:
            try:
                return WebDriverWait(driver, timeout).until(EC.presence_of_element_located((by, selector)))
            except Exception:
                continue
        return None

    def _safe_click(self, driver, element) -> bool:
        if element is None:
            return False
        try:
            element.click()
            return True
        except Exception:
            try:
                driver.execute_script("arguments[0].click();", element)
                return True
            except Exception:
                return False

    def _click_by_locators(self, driver, locators: list[tuple[str, str]], timeout: float = 4) -> bool:
        return self._safe_click(driver, self._find_clickable(driver, locators, timeout))

    def _play_visible_facebook_videos(self, driver) -> None:
        for video in driver.find_elements(By.CSS_SELECTOR, "video"):
            try:
                driver.execute_script(
                    "arguments[0].muted = true; if (arguments[0].play) { arguments[0].play(); }",
                    video,
                )
            except Exception:
                continue

    def _click_facebook_like(self, driver) -> bool:
        return self._click_by_locators(
            driver,
            [
                (By.XPATH, "//*[@role='button' and (@aria-label='Like' or @aria-label='React')]"),
                (By.CSS_SELECTOR, "[role='button'][aria-label='Like']"),
                (By.CSS_SELECTOR, "[role='button'][aria-label='React']"),
            ],
            timeout=3,
        )

    def _comment_on_facebook_reel(self, driver, comment: str) -> bool:
        if not comment:
            return False

        self._click_by_locators(
            driver,
            [
                (By.XPATH, "//*[@role='button' and @aria-label='Comment']"),
                (By.CSS_SELECTOR, "[role='button'][aria-label='Comment']"),
            ],
            timeout=3,
        )
        time.sleep(0.5)

        comment_box = self._find_clickable(
            driver,
            [
                (By.CSS_SELECTOR, "div[role='textbox'][contenteditable='true']"),
                (By.XPATH, "//*[@contenteditable='true' and @role='textbox']"),
                (
                    By.XPATH,
                    "//*[contains(translate(@aria-label, 'COMMENT', 'comment'), 'comment') and @contenteditable='true']",
                ),
            ],
            timeout=5,
        )
        if comment_box is None:
            comment_box = self._find_present(
                driver,
                [(By.CSS_SELECTOR, "div[contenteditable='true'], p[contenteditable='true']")],
                timeout=2,
            )
        if comment_box is None:
            return False

        self._safe_click(driver, comment_box)
        self.type_text(comment_box, comment)
        time.sleep(0.5)
        try:
            comment_box.send_keys(Keys.ENTER)
        except Exception:
            try:
                comment_box.send_keys(Keys.CONTROL, Keys.ENTER)
            except Exception:
                return False
        time.sleep(4)
        return True

    def _share_facebook_reel(self, driver) -> bool:
        if not self._click_by_locators(
            driver,
            [
                (By.XPATH, "//*[@role='button' and @aria-label='Share']"),
                (By.CSS_SELECTOR, "[role='button'][aria-label='Share']"),
            ],
            timeout=4,
        ):
            return False
        time.sleep(1)

        share_title = self.vars.share_title_var.get().strip() if hasattr(self.vars, "share_title_var") else ""
        if self._complete_facebook_share_dialog(driver, share_title):
            return True

        share_options = [
            "Share to Feed",
            "Share now (Public)",
            "Share to your story",
            "Share now",
        ]
        for option in share_options:
            option_xpath = (
                "//*[@role='menuitem' or @role='button' or self::span or self::div]"
                f"[.//*[normalize-space()={option!r}] or normalize-space()={option!r}]"
            )
            if self._click_by_locators(driver, [(By.XPATH, option_xpath)], timeout=2):
                time.sleep(1)
                if option == "Share to Feed" or share_title:
                    return self._complete_facebook_share_dialog(driver, share_title)
                if "Public" in option:
                    return True
                if self._share_dialog_privacy_text(driver).lower() == "only me":
                    return False
                return True

        try:
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        except Exception:
            pass
        return False

    def _complete_facebook_share_dialog(self, driver, share_title: str = "") -> bool:
        dialog_ready = self._find_present(
            driver,
            [
                (By.XPATH, "//*[@role='dialog' and .//*[normalize-space()='Share']]"),
                (By.XPATH, "//*[normalize-space()='Say something about this...']/ancestor::*[@role='dialog'][1]"),
                (By.XPATH, "//*[@role='button' and @aria-label='Share now']/ancestor::*[@role='dialog'][1]"),
            ],
            timeout=4,
        )
        if dialog_ready is None:
            return False

        if not self._ensure_share_privacy_public(driver):
            return False

        if share_title:
            self._fill_facebook_share_title(driver, share_title)

        clicked = self._click_by_locators(
            driver,
            [
                (By.XPATH, "//*[@role='button' and @aria-label='Share now']"),
                (By.XPATH, "//*[@role='button' and .//*[normalize-space()='Share now']]"),
                (By.XPATH, "//*[normalize-space()='Share now']/ancestor::*[@role='button'][1]"),
            ],
            timeout=6,
        )
        if clicked:
            time.sleep(3)
        return clicked

    def _fill_facebook_share_title(self, driver, share_title: str) -> bool:
        textbox = self._find_clickable(
            driver,
            [
                (By.XPATH, "//*[@role='dialog']//*[@contenteditable='true' and @role='textbox']"),
                (By.XPATH, "//*[@role='dialog']//*[contains(@aria-placeholder,'Say something') and @contenteditable='true']"),
                (By.CSS_SELECTOR, "div[role='dialog'] div[role='textbox'][contenteditable='true']"),
            ],
            timeout=4,
        )
        if textbox is None:
            return False
        self._safe_click(driver, textbox)
        self.type_text(textbox, share_title)
        time.sleep(0.3)
        return True

    def _ensure_share_privacy_public(self, driver) -> bool:
        privacy_text = self._share_dialog_privacy_text(driver).lower()
        if "public" in privacy_text:
            return True

        privacy_button = self._find_clickable(
            driver,
            [
                (By.XPATH, "//*[@role='dialog']//*[@role='button' and contains(@aria-label,'Edit privacy')]"),
                (By.XPATH, "//*[@role='dialog']//*[@role='button' and contains(@aria-label,'Only me')]"),
                (By.XPATH, "//*[@role='dialog']//*[normalize-space()='Only me']/ancestor::*[@role='button'][1]"),
            ],
            timeout=4,
        )
        if privacy_button is None:
            return False
        if not self._safe_click(driver, privacy_button):
            return False
        time.sleep(0.8)

        public_clicked = self._click_by_locators(
            driver,
            [
                (By.XPATH, "//*[@role='radio' and (@aria-label='Public' or .//*[normalize-space()='Public'])]"),
                (By.XPATH, "//*[@role='button' and (@aria-label='Public' or .//*[normalize-space()='Public'])]"),
                (By.XPATH, "//*[normalize-space()='Public']/ancestor::*[@role='radio' or @role='button'][1]"),
                (By.XPATH, "//*[normalize-space()='Public']"),
            ],
            timeout=5,
        )
        if not public_clicked:
            return False
        time.sleep(0.5)

        self._click_by_locators(
            driver,
            [
                (By.XPATH, "//*[@role='button' and (@aria-label='Done' or .//*[normalize-space()='Done'])]"),
                (By.XPATH, "//*[@role='button' and (@aria-label='Save' or .//*[normalize-space()='Save'])]"),
            ],
            timeout=2,
        )
        time.sleep(0.5)
        privacy_text = self._share_dialog_privacy_text(driver).lower()
        if privacy_text:
            return "public" in privacy_text
        return public_clicked

    def _share_dialog_privacy_text(self, driver) -> str:
        try:
            elements = driver.find_elements(
                By.XPATH,
                "//*[@role='dialog']//*[@role='button' and (contains(@aria-label,'Sharing') or contains(@aria-label,'privacy') or contains(.,'Only me') or contains(.,'Public'))]",
            )
            for element in elements:
                label = str(element.get_attribute("aria-label") or "").strip()
                text = str(element.text or "").strip()
                combined = " ".join(part for part in (label, text) if part)
                if "Only me" in combined or "Public" in combined:
                    return combined
        except Exception:
            return ""
        return ""

    def _advance_facebook_reel(self, driver) -> bool:
        if self._click_by_locators(
            driver,
            [
                (By.XPATH, "//*[@role='button' and @aria-label='Next Card']"),
                (By.CSS_SELECTOR, "[role='button'][aria-label='Next Card']"),
                (
                    By.XPATH,
                    "//*[local-name()='path' and @d='m15.293 10.293-2.94 2.94a.5.5 0 0 1-.707 0l-2.939-2.94a1 1 0 0 0-1.414 1.414l2.94 2.94a2.5 2.5 0 0 0 3.535 0l2.94-2.94a1 1 0 0 0-1.415-1.414z']/ancestor::*[@role='button'][1]",
                ),
            ],
            timeout=1,
        ):
            return True
        try:
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_DOWN)
            return True
        except Exception:
            try:
                driver.execute_script("window.scrollBy(0, Math.max(500, window.innerHeight * 0.8));")
                return True
            except Exception:
                return False

    def watch_facebook_videos(self, instance_numbers: list[int]) -> None:
        for instance_number in instance_numbers:
            driver = self.state.drivers.get(instance_number)
            if not driver:
                self.state.run_summary.append(f"Instance {instance_number}: Error - Firefox {instance_number} is not running.")
                continue

            video_count = self._int_from_var(self.vars.watch_count_var, default=1)
            duration_per_video = self._int_from_var(self.vars.watch_duration_var, default=30)
            scroll_duration = self._int_from_var(self.vars.scroll_duration_var, default=0)
            if video_count <= 0:
                self.state.run_summary.append(f"Instance {instance_number}: Error - Watch count must be greater than 0.")
                continue

            video_links = [link.strip() for link in self.vars.video_link_var.get().strip().split(",") if link.strip()]
            if not video_links:
                video_links = ["https://www.facebook.com/reel/"]

            for i in range(video_count):
                video_link = video_links[i % len(video_links)]
                try:
                    driver.get(video_link)
                    WebDriverWait(driver, 12).until(lambda browser: browser.find_elements(By.CSS_SELECTOR, "video"))
                    watch_end_time = time.time() + duration_per_video
                    while time.time() < watch_end_time:
                        self._play_visible_facebook_videos(driver)
                        time.sleep(0.5)
                except Exception as exc:
                    self.state.run_summary.append(f"Instance {instance_number}: Error opening video {video_link}: {exc}")
                    continue

                if self.vars.like_video_var.get() and not self._click_facebook_like(driver):
                    self.state.run_summary.append(f"Instance {instance_number}: Warning - Like button not found.")

                if self.vars.comment_video_var.get():
                    comment = self.vars.comment_text_var.get().strip()
                    if comment and not self._comment_on_facebook_reel(driver, comment):
                        self.state.run_summary.append(f"Instance {instance_number}: Warning - Comment box not found.")

                if self.vars.share_video_var.get() and not self._share_facebook_reel(driver):
                    self.state.run_summary.append(f"Instance {instance_number}: Warning - Share option not found.")

                if self.vars.scroll_var.get():
                    scroll_end_time = time.time() + scroll_duration
                    while time.time() < scroll_end_time:
                        self._advance_facebook_reel(driver)
                        time.sleep(1)

            self.state.run_summary.append(f"Instance {instance_number}: Success - Watched {video_count} videos.")

    def upload_facebook_reel(self, instance_numbers: list[int]) -> None:
        for instance_number in instance_numbers:
            driver = self.state.drivers.get(instance_number)
            if not driver:
                print(f"Error: Firefox instance {instance_number} is not running.")
                continue

            file_paths = self.vars.reel_folder_or_file_var.get().split(",")
            page_link = self.vars.page_link_var.get().strip()
            description = self.vars.description_var.get().strip() if self.vars.description_check_var.get() else ""
            switch_reel = self.vars.switch_reel_var.get()
            switch_page = self.vars.switch_page_var.get()
            description_check = self.vars.description_check_var.get()
            switch_video = self.vars.switch_video_var.get()
            switch_share = self.vars.switch_share_var.get()

            try:
                if switch_page and page_link:
                    driver.get(page_link)
                    print(f"Navigating to page link: {page_link}")
                    WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, "//span[text()='Switch Now']/ancestor::div[@role='none']"))
                    ).click()
                    print("Clicked Switch Now button.")
                    time.sleep(5)

                if switch_reel:
                    driver.get("https://www.facebook.com/reels/create")
                    print("Navigated to the reels creation page.")
                    for file_path in file_paths:
                        if not os.path.exists(file_path):
                            print(f"Error: Reel video path does not exist: {file_path}")
                            continue

                        upload_button = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.XPATH, "//input[@type='file']"))
                        )
                        absolute_video_path = os.path.abspath(file_path)
                        upload_button.send_keys(absolute_video_path)
                        print(f"Uploaded video: {absolute_video_path}")
                        time.sleep(5)

                        self.click_next_buttons(driver)
                        if description_check:
                            self.add_description(driver, description)

                        WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable(
                                (By.XPATH, "//div[@aria-label='Publish' and @role='button' and @tabindex='0']")
                            )
                        ).click()
                        time.sleep(5)

                if switch_video:
                    driver.get("https://web.facebook.com/profile.php")
                    print("Navigated to the Facebook post creation page.")
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located(
                            (
                                By.XPATH,
                                "//span[contains(@class,'x1lliihq x6ikm8r x10wlt62 x1n2onr6') and text()=\"What's on your mind?\"]",
                            )
                        )
                    ).click()
                    print("Clicked 'What's on your mind' area.")

                    if description_check:
                        self.add_description_video(driver, description)

                    WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, "//div[@aria-label='Photo/Video' or @aria-label='Photo/video']"))
                    ).click()
                    print("Clicked Photo/video button.")
                    WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, "//span[text()='or drag and drop']"))
                    ).click()
                    print("Clicked 'or drag and drop' span.")

                if switch_share:
                    video_links = [link.strip() for link in self.vars.video_link_var.get().strip().split(",") if link.strip()]
                    post_text = self.vars.post_text_var.get().strip()
                    share_count = int(self.vars.share_group_count_var.get().strip())

                    for video_link in video_links:
                        for _ in range(share_count):
                            driver.get("https://web.facebook.com/profile.php")
                            print("Navigated to the Facebook post creation page.")
                            WebDriverWait(driver, 10).until(
                                EC.presence_of_element_located(
                                    (
                                        By.XPATH,
                                        "//span[contains(@class,'x1lliihq x6ikm8r x10wlt62 x1n2onr6') and text()=\"What's on your mind?\"]",
                                    )
                                )
                            ).click()
                            print("Clicked 'What's on your mind' area.")

                            post_box = WebDriverWait(driver, 10).until(
                                EC.presence_of_element_located(
                                    (
                                        By.XPATH,
                                        "//div[@aria-placeholder=\"What's on your mind?\" and @aria-label=\"What's on your mind?\" and @contenteditable='true' and @role='textbox']",
                                    )
                                )
                            )
                            self.type_text(post_box, video_link)
                            time.sleep(5)
                            post_box.send_keys(Keys.CONTROL + "a")
                            post_box.send_keys(Keys.BACKSPACE)
                            if post_text:
                                self.type_text(post_box, post_text)

                            WebDriverWait(driver, 10).until(
                                EC.element_to_be_clickable((By.XPATH, "//span[text()='Post']/ancestor::div[@role='none']"))
                            ).click()
                            print("Clicked 'Post' button.")
                            time.sleep(15)
            except Exception as exc:
                print(f"Error during upload for instance {instance_number}: {exc}")

    def click_next_buttons(self, driver) -> None:
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//div[@aria-label='Next' and @role='button' and @tabindex='0']"))
        ).click()
        time.sleep(5)
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//div[@aria-label='Next' and @role='button' and @tabindex='0']"))
        ).click()
        time.sleep(5)

    def type_text(self, element, text: str) -> None:
        for char in text:
            element.send_keys(char)
            time.sleep(0.1)

    def add_description_video(self, driver, description: str) -> None:
        paste_text_area = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//div[@class='x1ejq31n xd10rxx x1sy0etr x17r0tee x9f619 xzsf02u xmper1u xngnso2 xo1l8bm x5yr21d x1qb5hxa x1a2a7pz x1iorvi4 x4uap5 xwib8y2 xkhd6sd xh8yej3 xha3pab']//div[@aria-placeholder=\"What's on your mind?\" and @contenteditable='true']",
                )
            )
        )
        paste_text_area.click()
        for char in description:
            paste_text_area.send_keys(char)
            time.sleep(0.05)
        print(f"Pasted description character by character: {description}")
        time.sleep(5)

    def add_description(self, driver, description: str) -> None:
        paste_text_area = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//div[@aria-placeholder='Describe your reel...' and @contenteditable='true']"))
        )
        paste_text_area.click()
        for char in description:
            paste_text_area.send_keys(char)
            time.sleep(0.05)
        print(f"Pasted description character by character: {description}")
        time.sleep(5)

    def share_to_facebook_groups(self, instance_numbers: list[int]) -> None:
        group_urls = [url.strip() for url in self.vars.group_urls_var.get().strip().split(",") if url.strip()]
        video_link = self.vars.video_link_var.get().strip()
        post_text = self.vars.post_text_var.get().strip()
        try:
            share_count = int(self.vars.share_group_count_var.get())
        except ValueError:
            return

        for instance_number in instance_numbers:
            driver = self.state.drivers.get(instance_number)
            if not driver:
                continue

            for group_url in group_urls:
                for _ in range(share_count):
                    try:
                        driver.get(group_url)
                        WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.XPATH, "//span[contains(text(),'Write something...')]"))
                        ).click()
                        post_box = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.XPATH, "//div[@aria-label='Create a public post']"))
                        )
                        post_box.send_keys(video_link)
                        time.sleep(5)
                        post_box.send_keys(Keys.CONTROL + "a")
                        post_box.send_keys(Keys.BACKSPACE)
                        if post_text:
                            post_box.send_keys(post_text)

                        WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable((By.XPATH, "//span[text()='Post']"))
                        ).click()
                        time.sleep(15)
                    except Exception as exc:
                        print(f"Error sharing video to group {group_url} on Firefox {instance_number}: {exc}")

    def join_facebook_groups(self, instance_numbers: list[int]) -> None:
        group_urls = [url.strip() for url in self.vars.group_urls_var.get().strip().split(",") if url.strip()]
        for instance_number in instance_numbers:
            driver = self.state.drivers.get(instance_number)
            if not driver:
                continue

            for group_url in group_urls:
                try:
                    driver.get(group_url)
                    WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, "//div[@role='button'][@aria-label='Join group']"))
                    ).click()
                    time.sleep(2)
                except Exception:
                    continue
