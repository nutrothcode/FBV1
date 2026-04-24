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

    def watch_facebook_videos(self, instance_numbers: list[int]) -> None:
        for instance_number in instance_numbers:
            driver = self.state.drivers.get(instance_number)
            if not driver:
                self.state.run_summary.append(f"Instance {instance_number}: Error - Firefox {instance_number} is not running.")
                continue

            try:
                video_count = int(self.vars.watch_count_var.get())
                duration_per_video = int(self.vars.watch_duration_var.get())
            except ValueError:
                self.state.run_summary.append(f"Instance {instance_number}: Error - Invalid watch count or duration.")
                continue

            video_links = [link.strip() for link in self.vars.video_link_var.get().strip().split(",") if link.strip()]
            if not video_links:
                video_links = ["https://www.facebook.com/watch"]

            for i in range(video_count):
                video_link = video_links[i % len(video_links)]
                driver.get(video_link)
                start_time = time.time()

                while time.time() - start_time < duration_per_video:
                    try:
                        video_element = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, "video"))
                        )
                        driver.execute_script("arguments[0].play();", video_element)

                        if self.vars.link_video_var.get():
                            if self.vars.like_video_var.get():
                                try:
                                    driver.find_element(
                                        By.XPATH,
                                        "//div[@class='x1ey2m1c xds687c x17qophe xg01cxk x47corl x10l6tqk x13vifvy x1ebt8du x19991ni x1dhq9h x1o1ewxj x3x9cwd x1e5q0jg x13rtm0m']",
                                    ).click()
                                except Exception as exc:
                                    self.state.run_summary.append(f"Instance {instance_number}: Error liking video: {exc}")

                            if self.vars.comment_video_var.get():
                                try:
                                    comment = self.vars.comment_text_var.get().strip()
                                    if comment:
                                        comment_box = WebDriverWait(driver, 10).until(
                                            EC.element_to_be_clickable(
                                                (By.XPATH, "//p[@class='xdj266r x11i5rnm xat24cr x1mh8g0r']")
                                            )
                                        )
                                        comment_box.click()
                                        comment_box = WebDriverWait(driver, 10).until(
                                            EC.presence_of_element_located(
                                                (By.XPATH, "//p[@class='xdj266r x11i5rnm xat24cr x1mh8g0r']/parent::div")
                                            )
                                        )
                                        self.type_text(comment_box, comment)
                                        WebDriverWait(driver, 10).until(
                                            EC.element_to_be_clickable(
                                                (By.XPATH, "//div[@aria-label='Comment' and @role='button']")
                                            )
                                        ).click()
                                except Exception as exc:
                                    self.state.run_summary.append(
                                        f"Instance {instance_number}: Error commenting on video: {exc}"
                                    )

                            if self.vars.share_video_var.get():
                                try:
                                    driver.find_element(
                                        By.XPATH,
                                        "//div[@class='x9f619 x1n2onr6 x1ja2u2z x78zum5 x1ey2m1c xds687c x17qophe xg01cxk x47corl x10l6tqk x13vifvy x1ebt8du x19991ni x1dhq9h x1o1ewxj x3x9cwd x1e5q0jg x13rtm0m']",
                                    ).click()
                                    WebDriverWait(driver, 10).until(
                                        EC.element_to_be_clickable((By.XPATH, "//i[@class='x1b0d499 xi3auck']"))
                                    ).click()
                                    WebDriverWait(driver, 10).until(
                                        EC.element_to_be_clickable(
                                            (By.XPATH, "//span[@class='x1lliihq x6ikm8r x10wlt62 x1n2onr6 xlyipyv xuxw1ft']")
                                        )
                                    ).click()
                                except Exception as exc:
                                    self.state.run_summary.append(f"Instance {instance_number}: Error sharing video: {exc}")

                        time.sleep(5)
                    except Exception as exc:
                        self.state.run_summary.append(f"Instance {instance_number}: Error during video watch: {exc}")
                        break

                if self.vars.scroll_var.get():
                    try:
                        scroll_duration = int(self.vars.scroll_duration_var.get())
                    except ValueError:
                        self.state.run_summary.append(f"Instance {instance_number}: Error - Invalid scroll duration.")
                        break

                    scroll_end_time = time.time() + scroll_duration
                    while time.time() < scroll_end_time:
                        driver.execute_script("window.scrollBy(0, 1);")
                        time.sleep(0.01)

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
