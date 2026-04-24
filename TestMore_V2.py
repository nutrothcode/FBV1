import tkinter as tk
from tkinter import simpledialog, messagebox, Toplevel, Label, Entry, Button, filedialog, BooleanVar, Scrollbar, Canvas, Frame, StringVar, IntVar, Radiobutton
from selenium import webdriver
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import json
import os
import logging
from PIL import Image, ImageTk
import threading
import time
from tkinter import Checkbutton

# Setup logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Paths and configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'firefox_instances.json')
FIREFOX_USER_DATA_DIR = os.path.join(BASE_DIR, "Account Firefox", "firefox")
os.makedirs(FIREFOX_USER_DATA_DIR, exist_ok=True)
IMAGE_DIR = os.path.join(BASE_DIR, "images")
os.makedirs(IMAGE_DIR, exist_ok=True)
GECKODRIVER_PATH = os.path.join(BASE_DIR, "Account Firefox", "geckodriver.exe")  # Custom path to geckodriver
LOGO_PATH = os.path.join(BASE_DIR, "Account Firefox", "fb logo.png")  # Custom path to logo
ICON_PATH = os.path.join(BASE_DIR, "Account Firefox", "fb logo.png")  # Custom path to icon

# Create the main window
root = tk.Tk()
root.title("FbV2 By NutRoth")

# Set the logo as the icon for the app
if os.path.exists(ICON_PATH):
    icon_image = Image.open(ICON_PATH)
    icon_photo = ImageTk.PhotoImage(icon_image)
    root.iconphoto(False, icon_photo)
def display_logo_with_text():
    logo_frame = Frame(root)
    logo_frame.pack(pady=10)  # Add some padding to the top
    
    if os.path.exists(LOGO_PATH):
        logo_image = Image.open(LOGO_PATH)
        logo_image.thumbnail((40, 40))  # Resize the logo
        logo_photo = ImageTk.PhotoImage(logo_image)
        logo_label = Label(logo_frame, image=logo_photo)
        logo_label.image = logo_photo  # Keep a reference to avoid garbage collection
        logo_label.pack(side="left")
    
    text_label = Label(logo_frame, text="FACEBOOK TOOL V2 By NutRoth", font=("Arial", 15))
    text_label.pack(side="left", padx=10)  # Add some padding between the logo and the text

# Display the logo at the top of the main window
display_logo_with_text()

# Global variables
firefox_buttons = []
credential_entries = {}
credentials_dict = {}
drivers = {}
instance_names = {}
deleted_instances = set()
scrolling = False
image_labels = {}
run_summary = []

# StringVar and IntVar initialization
watch_video_var = IntVar()
like_video_var = IntVar()
comment_video_var = IntVar()
share_video_var = IntVar()
link_video_var = IntVar()
scroll_var = IntVar()
action_var = StringVar(value="login")
watch_count_var = StringVar()
watch_duration_var = StringVar()
scroll_duration_var = StringVar()
like_count_var = StringVar()
comment_text_var = StringVar()
video_link_var = StringVar()
group_urls_var = StringVar()
description_var = StringVar()
reel_folder_or_file_var = StringVar()
page_link_var = StringVar()
share_group_count_var = StringVar()
post_text_var = StringVar()
get_id_result_var = StringVar()
get_id_var = IntVar()
get_gmail = StringVar()
get_gmail_var = IntVar()
get_date = StringVar()
get_date_var = IntVar()
get_photo = StringVar()
get_photo_var = IntVar()
get_cover = StringVar()
get_cover_var = IntVar()
clear_data_var = IntVar()

# BooleanVars
switch_reel_var = BooleanVar()
switch_page_var = BooleanVar()
paste_back_fb_var = BooleanVar()
description_check_var = BooleanVar()
auto_run_var = BooleanVar()
click_run_var = BooleanVar()

# Create a Canvas for scrolling
canvas = Canvas(root)
scroll_y = Scrollbar(root, orient="vertical", command=canvas.yview)

# Create a Frame to hold the buttons
button_frame = Frame(canvas)
button_frame.bind(
    "<Configure>",
    lambda e: canvas.configure(
        scrollregion=canvas.bbox("all")
    )
)

canvas.create_window((0, 0), window=button_frame, anchor="nw")
canvas.configure(yscrollcommand=scroll_y.set)

canvas.pack(side="left", fill="both", expand=True)
scroll_y.pack(side="right", fill="y")

def open_firefox_instances(instance_count, start_index=1, button_width=15, button_height=1, padding=5):
    global firefox_buttons
    for i in range(start_index, start_index + instance_count):
        if i in deleted_instances:
            continue
        instance_folder = os.path.join(FIREFOX_USER_DATA_DIR, f"Firefox_{i}")
        os.makedirs(instance_folder, exist_ok=True)
        
        instance_frame = Frame(button_frame, bg="#f0f0f0")  # Set background color
        instance_frame.pack(pady=padding)
        
        button = Button(instance_frame, text=instance_names.get(i, f"Firefox {i}"), 
                        command=lambda i=i: threading.Thread(target=run_firefox_instance, args=(i,)).start(), 
                        width=button_width, height=button_height, bg="#ffebe6")  # Set background color
        button.pack(side="left", padx=5)
        
        rename_button = Button(instance_frame, text="Rename", command=lambda i=i: rename_instance(i), 
                               width=button_width//2, height=button_height, bg="#e6e6ff")  # Set background color
        rename_button.pack(side="left", padx=(padding, 0))
        
        delete_button = Button(instance_frame, text="Delete", command=lambda i=i: delete_instance(i), 
                               width=button_width//2, height=button_height, bg="#d9d9d9")  # Set background color
        delete_button.pack(side="left", padx=(padding, 0))
        
        picture_button = Button(instance_frame, text="Picture", command=lambda i=i: upload_picture(i), 
                                width=button_width//2, height=button_height, bg="#ccffff")  # Set background color
        picture_button.pack(side="left", padx=(padding, 0))

        image_label = Label(instance_frame, bg="#f0f0f0")  # Set background color
        image_label.pack(side="left", padx=(padding, 0))
        image_labels[i] = image_label
        
        while len(firefox_buttons) < i:
            firefox_buttons.append((None, None))
        firefox_buttons[i - 1] = (button, instance_frame)

def upload_picture(instance_number):
    file_path = filedialog.askopenfilename(filetypes=[("Image Files", "*.png;*.jpg;*.jpeg")])
    if file_path:
        image = Image.open(file_path)
        image.thumbnail((50, 50))
        image_tk = ImageTk.PhotoImage(image)
        image_labels[instance_number].config(image=image_tk)
        image_labels[instance_number].image = image_tk
        dest_path = os.path.join(IMAGE_DIR, f"image_{instance_number}.png")
        with open(file_path, 'rb') as src_file, open(dest_path, 'wb') as dest_file:
            dest_file.write(src_file.read())
        logging.info(f"Image for Firefox {instance_number} uploaded successfully.")

def run_firefox_instance(instance_number):
    action = action_var.get()
    if action == "login":
        open_firefox_instance(instance_number)
    elif action == "care":
        open_firefox_instance(instance_number, login=False)
        watch_facebook_videos([instance_number])
    elif action == "clear_data":
        open_firefox_instance(instance_number, login=False, clear_data_action=True)
    elif action == "join_group":
        open_firefox_instance(instance_number, login=False)
        join_facebook_groups([instance_number])
    elif action == "upload_reel":
        open_firefox_instance(instance_number, login=False)
        upload_facebook_reel([instance_number])
    elif action == "share_to_groups":
        open_firefox_instance(instance_number, login=False)
        share_to_facebook_groups([instance_number])
    elif action == "get_id":
        open_firefox_instance(instance_number, login=False)
        get_id(instance_number)
    elif action == "get_gmail":
        open_firefox_instance(instance_number, login=False)
        get_gmail(instance_number)
    elif action == "get_date":
        open_firefox_instance(instance_number, login=False)
        get_date(instance_number)
    elif action == "get_photo":
        open_firefox_instance(instance_number, login=False)
        get_photo(instance_number)
    elif action == "get_cover":
        open_firefox_instance(instance_number, login=False)
        get_cover(instance_number)

def open_firefox_instance(instance_number, login=True, clear_data_action=False):
    try:
        firefox_options = FirefoxOptions()
        # Add arguments for custom window size if needed
        firefox_options.add_argument("--width=120")
        firefox_options.add_argument("--height=300")
        user_data_dir = os.path.join(FIREFOX_USER_DATA_DIR, f"Firefox_{instance_number}")
        firefox_options.add_argument("-profile")
        firefox_options.add_argument(user_data_dir)

        # Retain cookies and other data
        firefox_options.set_preference("browser.privatebrowsing.autostart", False)
        firefox_options.set_preference("privacy.clearOnShutdown.cookies", False)
        firefox_options.set_preference("privacy.clearOnShutdown.cache", False)
        firefox_options.set_preference("privacy.clearOnShutdown.sessions", False)
        firefox_options.set_preference("privacy.clearOnShutdown.offlineApps", False)
        firefox_options.set_preference("privacy.clearOnShutdown.siteSettings", False)
        firefox_options.set_preference("privacy.clearOnShutdown.formData", False)
        firefox_options.set_preference("privacy.clearOnShutdown.downloads", False)

        logging.debug(f"Attempting to launch Firefox instance {instance_number} with user data dir: {user_data_dir}")

        # Use the custom path for geckodriver
        service = FirefoxService(executable_path=GECKODRIVER_PATH)
        driver = webdriver.Firefox(service=service, options=firefox_options)
        drivers[instance_number] = driver

        if clear_data_action:
            clear_data(driver)
        elif login:
            load_cookies(driver, instance_number)
            prepare_login(instance_number)
        else:
            driver.get("https://www.facebook.com")
            logging.info(f"Firefox {instance_number} is ready for action.")
    except Exception as e:
        logging.error(f"Failed to open Firefox instance {instance_number}: {e}")
        run_summary.append(f"Firefox {instance_number}: Error")

def prepare_login(instance_number):
    driver = drivers.get(instance_number)
    if not driver:
        logging.error(f"Firefox {instance_number} is not running.")
        run_summary.append(f"Firefox {instance_number}: Error")
        return

    credentials = credentials_dict.get(instance_number)
    if not credentials:
        logging.info(f"No credentials saved for Firefox {instance_number}. Please log in manually if needed.")
        driver.get("https://www.facebook.com")
        return

    try:
        email, password, two_fa = credentials.split('|')
    except ValueError:
        logging.error("Credentials format should be 'email|password|2fa'")
        run_summary.append(f"Firefox {instance_number}: Error")
        return

    try:
        driver.get("https://www.facebook.com")

        if "checkpoint" in driver.current_url:
            logging.info("Please resolve the checkpoint manually.")
            run_summary.append(f"Firefox {instance_number}: Error")
            return

        email_field = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "email")))
        password_field = driver.find_element(By.ID, "pass")
        email_field.send_keys(email)
        password_field.send_keys(password)

        login_button = driver.find_element(By.NAME, "login")
        login_button.click()

        if two_fa:
            two_fa_code = get_2fa_code(two_fa, driver)
            if two_fa_code:
                try:
                    two_fa_field = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "input[autocomplete='off'][type='text']"))
                    )
                    two_fa_field.send_keys(two_fa_code)

                    submit_code_button = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.ID, "checkpointSubmitButton"))
                    )
                    submit_code_button.click()

                    try:
                        continue_button = WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable((By.ID, "checkpointSubmitButton"))
                        )
                        continue_button.click()
                    except:
                        logging.info("Please complete any additional steps manually.")
                except Exception as e:
                    logging.error(f"2FA code entry failed: {e}")
                    run_summary.append(f"Firefox {instance_number}: Error")
            else:
                logging.error("Please copy code 2fa and continue login Facebook.")
                run_summary.append(f"Firefox {instance_number}: Error")
        else:
            save_cookies(driver, instance_number)
            logging.info(f"Please complete the login process manually for Firefox {instance_number}.")
    except Exception as e:
        logging.error(f"Failed during login preparation: {e}")
        run_summary.append(f"Firefox {instance_number}: Error")

def get_2fa_code(secret, driver):
    try:
        driver.execute_script("window.open('https://2fa.live/', '_blank');")
        driver.switch_to.window(driver.window_handles[1])
        
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "textarea#listToken.form-control")))
        input_field = driver.find_element(By.CSS_SELECTOR, "textarea#listToken.form-control")
        input_field.send_keys(secret)
        
        submit_button = driver.find_element(By.XPATH, "//a[@id='submit']")
        submit_button.click()
        
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//a[@id='copy_btn']")))
        copy_button = driver.find_element(By.XPATH, "//a[@id='copy_btn']")
        copy_button.click()

        output_field = driver.find_element(By.CSS_SELECTOR, "textarea#output.form-control")
        output_text = output_field.get_attribute("value")
        
        two_fa_code = output_text.split('|')[-1].strip()
        if not two_fa_code.isdigit() or len(two_fa_code) != 6:
            raise ValueError("Unexpected format of the 2FA output")
        
        driver.close()
        driver.switch_to.window(driver.window_handles[0])
        
        return two_fa_code
    except Exception as e:
        logging.error(f"Error fetching 2FA code: {e}")
        return None

def handle_remember_browser(driver):
    try:
        remember_button = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "checkpointSubmitButton")))
        remember_button.click()
    except Exception as e:
        logging.error(f"Error handling 'Remember Browser': {e}")

def get_id(instance_number):
    try:
        driver = drivers.get(instance_number)
        if not driver:
            messagebox.showerror("Error", f"Chrome {instance_number} is not running.")
            return

        profile_url = "https://www.facebook.com/profile.php?id"
        driver.get(profile_url)

        about_span = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//span[text()='About']"))
        )
        about_span.click()

        contact_info_span = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//span[text()='Contact and basic info']"))
        )
        contact_info_span.click()

    except Exception as e:
        messagebox.showerror("Error", f"Please Continue^.^: {e}")

def get_gmail(instance_number):
    try:
        driver = drivers.get(instance_number)
        if not driver:
            messagebox.showerror("Error", f"Chrome {instance_number} is not running.")
            return

        profile_url = "https://accountscenter.facebook.com/personal_info"
        driver.get(profile_url)

    except Exception as e:
        messagebox.showerror("Error", f"Please Continue^.^: {e}")

def get_date(instance_number):
    try:
        driver = drivers.get(instance_number)
        if not driver:
            messagebox.showerror("Error", f"Chrome {instance_number} is not running.")
            return

        profile_url = "https://www.facebook.com/your_information/?tab=your_information&tile=personal_info_grouping"
        driver.get(profile_url)

    except Exception as e:
        messagebox.showerror("Error", f"Please Continue^.^: {e}")

def get_cover(instance_number):
    try:
        driver = drivers.get(instance_number)
        if not driver:
            messagebox.showerror("Error", f"Chrome {instance_number} is not running.")
            return

        profile_url = "https://www.facebook.com/profile.php?id"
        driver.get(profile_url)

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'i[data-visualcompletion="css-img"].x1b0d499.xep6ejk'))
        )
        icon_element = driver.find_element(By.CSS_SELECTOR, 'i[data-visualcompletion="css-img"].x1b0d499.xep6ejk')
        icon_element.click()

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//span[contains(@class, 'x1lliihq') and text()='Upload photo']"))
        )
        upload_button = driver.find_element(By.XPATH, "//span[contains(@class, 'x1lliihq') and text()='Upload photo']")
        upload_button.click()

        file_input = driver.find_element(By.XPATH, "//input[@type='file']")
        file_path = "/path/to/photo.jpg"
        file_input.send_keys(file_path)

    except Exception as e:
        messagebox.showerror("Error", f"Please Continue^.^: {e}")

def get_photo(instance_number):
    try:
        driver = drivers.get(instance_number)
        if not driver:
            messagebox.showerror("Error", f"Chrome {instance_number} is not running.")
            return

        profile_url = "https://www.facebook.com/profile.php?id"
        driver.get(profile_url)
        
        time.sleep(5)
        
        update_profile_pic_button = driver.find_element(By.CSS_SELECTOR, 
            'div[aria-label="Update profile picture"].x1i10hfl.x1ejq31n.xd10rxx.x1sy0etr.x17r0tee.x1ypdohk.xe8uvvx.xdj266r.x11i5rnm.xat24cr.x1mh8g0r.x16tdsg8.x1hl2dhg.xggy1nq.x87ps6o.x1lku1pv.x1a2a7pz.x6s0dn4.xzolkzo.x12go9s9.x1rnf11y.xprq8jg.x972fbf.xcfux6l.x1qhh985.xm0m39n.x9f619.x78zum5.xl56j7k.xexx8yu.x4uap5.x18d9i69.xkhd6sd.x1n2onr6.xc9qbxq.x14qfxbe.x1qhmfi1')
        update_profile_pic_button.click()
        
        time.sleep(2)
        
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//span[contains(@class, 'x1lliihq') and text()='Upload photo']"))
        )
        upload_button = driver.find_element(By.XPATH, "//span[contains(@class, 'x1lliihq') and text()='Upload photo']")
        upload_button.click()

        file_input = driver.find_element(By.XPATH, "//input[@type='file']")
        file_path = "/path/to/photo.jpg"
        file_input.send_keys(file_path)

    except Exception as e:
        messagebox.showerror("Error", f"Please Continue^.^: {e}")

def generate_firefox_instances():
    start_index = simpledialog.askinteger("Input", "Enter the starting instance index:", minvalue=1)
    end_index = simpledialog.askinteger("Input", "Enter the ending instance index (put the same number if generate just one):", minvalue=start_index)
    if start_index is not None:
        if end_index is None:
            end_index = start_index
        for i in range(start_index, end_index + 1):
            deleted_instances.discard(i)
        instance_count = end_index - start_index + 1
        open_firefox_instances(instance_count, start_index=start_index)
        save_instance_data()

def save_instance_data():
    data = {
        "credentials": credentials_dict,
        "instance_names": instance_names,
        "deleted_instances": list(deleted_instances),
        "active_instances": [i + 1 for i, (button, frame) in enumerate(firefox_buttons) if frame is not None],
    }
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f)

# Function to load instance data
def load_instance_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            return data.get("credentials", {}), data.get("instance_names", {}), set(data.get("deleted_instances", [])), data.get("active_instances", [])
    return {}, {}, set(), []

# Function to initialize the application
def initialize_app():
    global credentials_dict, instance_names, deleted_instances, firefox_buttons
    credentials_dict, instance_names, deleted_instances, active_instances = load_instance_data()
    for i in active_instances:
        open_firefox_instances(1, start_index=i)

def enter_credentials():
    credentials_window = Toplevel(root)
    credentials_window.title("Enter Credentials")

    canvas = Canvas(credentials_window)
    scroll_y = Scrollbar(credentials_window, orient="vertical", command=canvas.yview)

    frame = Frame(canvas)

    for instance_number in range(1, max((i for i in range(1, len(firefox_buttons) + 1) if i not in deleted_instances), default=0) + 1):
        if instance_number in deleted_instances:
            continue
        inner_frame = Frame(frame)
        inner_frame.pack()
        label = Label(inner_frame, text=f"Firefox {instance_number} (format: email|password|2fa):")
        label.pack(side="left")
        entry = Entry(inner_frame, width=50)
        entry.pack(side="left")
        entry.insert(0, credentials_dict.get(instance_number, ""))
        credential_entries[instance_number] = entry

    save_button = Button(frame, text="Save", command=save_credentials)
    save_button.pack()

    frame.update_idletasks()
    canvas.create_window(0, 0, anchor='nw', window=frame)
    canvas.update_idletasks()

    canvas.config(scrollregion=canvas.bbox("all"), yscrollcommand=scroll_y.set)

    canvas.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
    scroll_y.pack(fill=tk.Y, side=tk.RIGHT)

# Function to save credentials
def save_credentials():
    for instance_number, entry in credential_entries.items():
        credentials_dict[instance_number] = entry.get()
    save_instance_data()

# Function to rename an instance
def rename_instance(instance_number):
    new_name = simpledialog.askstring("Rename Instance", f"Enter a new name for Firefox {instance_number}:")
    if new_name:
        instance_names[instance_number] = new_name
        firefox_buttons[instance_number - 1][0].config(text=new_name)
        save_instance_data()

# Function to delete an instance
def delete_instance(instance_number, confirm=True):
    # Confirm deletion
    if confirm:
        if not messagebox.askyesno("Delete Instance", f"Are you sure you want to delete Firefox {instance_number}?"):
            return
    
    # Remove data from the global variables
    credentials_dict.pop(instance_number, None)
    instance_names.pop(instance_number, None)
    deleted_instances.add(instance_number)

    instance_folder = os.path.join(FIREFOX_USER_DATA_DIR, f"Firefox_{instance_number}")
    if os.path.exists(instance_folder):
        try:
            for root, dirs, files in os.walk(instance_folder, topdown=False):
                for name in files:
                    os.remove(os.path.join(root, name))
                for name in dirs:
                    os.rmdir(os.path.join(root, name))
            os.rmdir(instance_folder)
        except Exception as e:
            logging.error(f"Failed to delete folder {instance_folder}: {e}")

    # Destroy associated GUI elements
    button, frame = firefox_buttons[instance_number - 1]
    if frame:
        frame.destroy()
    firefox_buttons[instance_number - 1] = (None, None)

    save_instance_data()

# Function to delete multiple instances
def delete_multiple_instances():
    start_instance = simpledialog.askinteger("Delete Multiple Instances", "Enter the start instance number:")
    end_instance = simpledialog.askinteger("Delete Multiple Instances", "Enter the end instance number:")
    if start_instance and end_instance:
        if messagebox.askyesno("Delete Instances", f"Are you sure you want to delete Firefox {start_instance} to Firefox {end_instance}?"):
            for i in range(start_instance, end_instance + 1):
                delete_instance(i, confirm=False)

def clear_data(driver):
    try:
        driver.execute_script("window.open('');")
        driver.switch_to.window(driver.window_handles[-1])
        driver.get('about:preferences#privacy')
        
        # Wait for the page to load completely
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "historySection")))

        # Scroll down to the "Cookies and Site Data" section
        driver.execute_script("document.getElementById('historySection').scrollIntoView();")

        # Check only the "Cached Web Content" option
        driver.execute_script("""
            document.querySelector("button[data-l10n-id='clear-data-button']").click();
            document.querySelector("input[data-id='cache']").checked = true;
            document.querySelector("input[data-id='cookies']").checked = false;
        """)
        
        # Click the "Clear" button
        driver.execute_script("document.querySelector('dialog[open] button[data-l10n-id=\"clear-data-button\"]').click();")

        logging.info("Cleared temporary cached files and pages, kept cookies.")
    except Exception as e:
        logging.error(f"Error clearing data: {e}")

# Functions to save and load cookies
def save_cookies(driver, instance_number):
    cookies = driver.get_cookies()
    with open(os.path.join(f"cookies_{instance_number}.json"), 'w') as f:
        json.dump(cookies, f)
    logging.info(f"Cookies for Firefox {instance_number} saved successfully.")

def load_cookies(driver, instance_number):
    cookie_file = os.path.join(f"cookies_{instance_number}.json")
    if os.path.exists(cookie_file):
        with open(cookie_file, 'r') as f:
            cookies = json.load(f)
            for cookie in cookies:
                driver.add_cookie(cookie)
        logging.info(f"Cookies for Firefox {instance_number} loaded successfully.")
    else:
        logging.info(f"No cookies found for Firefox {instance_number}.")

def run_multiple_firefox():
    start_instance = start_instance_var.get()
    end_instance = end_instance_var.get()
    max_instances = max_instances_var.get()

    if start_instance is not None and end_instance is not None and max_instances is not None:
        for i in range(start_instance, end_instance + 1):
            threading.Thread(target=run_firefox_instance, args=(i,)).start()
            if (i - start_instance + 1) % max_instances == 0:
                threading.Thread(target=messagebox.showinfo, args=("Info", f"Finished running instances {start_instance} to {i}")).start()
                if i < end_instance:
                    simpledialog.askstring("Continue", f"Press OK to continue running instances {i+1} to {min(i+max_instances, end_instance)}")

    if start_instance is not None and end_instance is not None and max_instances is not None:
        run_summary.clear()
        for i in range(start_instance, end_instance + 1, max_instances):
            threads = []
            for j in range(i, min(i + max_instances, end_instance + 1)):
                thread = threading.Thread(target=run_firefox_instance, args=(j,))
                threads.append(thread)
                thread.start()
            for thread in threads:
                thread.join()
                time.sleep(8)
            for driver in drivers.values():
                driver.quit()
        messagebox.showinfo("Summary", "\n".join(run_summary))

# Create entries and checkboxes for the new "Run Firefox" dialog
start_instance_var = IntVar()
end_instance_var = IntVar()
max_instances_var = IntVar()
auto_run_var = BooleanVar()
click_run_var = BooleanVar()
time_run_var = BooleanVar()

# Initialize the GUI and set up the "Run Firefox" dialog
def run_firefox_dialog():
    dialog = Toplevel(root)
    dialog.title("Run Firefox")

    Label(dialog, text="Start Instance:").grid(row=0, column=0)
    Entry(dialog, textvariable=start_instance_var).grid(row=0, column=1)

    Label(dialog, text="End Instance:").grid(row=1, column=0)
    Entry(dialog, textvariable=end_instance_var).grid(row=1, column=1)

    Label(dialog, text="Max Instances on Screen:").grid(row=2, column=0)
    Entry(dialog, textvariable=max_instances_var).grid(row=2, column=1)

    Checkbutton(dialog, text="Auto Run", variable=auto_run_var).grid(row=3, column=0, columnspan=2)
    Checkbutton(dialog, text="Click Run", variable=click_run_var).grid(row=4, column=0, columnspan=2)
    Checkbutton(dialog, text="Time Run", variable=time_run_var).grid(row=5, column=0, columnspan=2)

    Button(dialog, text="Run", command=lambda: run_multiple_firefox_auto(dialog)).grid(row=6, column=0, columnspan=2)

# Function to run Firefox instances based on the dialog input
def run_multiple_firefox_auto(dialog):
    dialog.destroy()
    if auto_run_var.get():
        run_multiple_firefox_with_limits()
    elif click_run_var.get():
        for i in range(start_instance_var.get(), end_instance_var.get() + 1):
            threading.Thread(target=run_firefox_instance, args=(i,)).start()
    elif time_run_var.get():
        run_multiple_firefox_with_time()

def run_multiple_firefox_with_limits():
    start_instance = start_instance_var.get()
    end_instance = end_instance_var.get()
    max_instances = max_instances_var.get()

    if start_instance is not None and end_instance is not None and max_instances is not None:
        run_summary.clear()
        current_running_instances = []
        event = threading.Event()

        def run_and_wait(instance_number):
            run_firefox_instance(instance_number)
            time.sleep(5)  # wait 5 seconds before closing
            if instance_number in drivers:
                drivers[instance_number].quit()
                drivers.pop(instance_number, None)
                logging.info(f"Firefox {instance_number} has been closed.")
                run_summary.append(f"Firefox {instance_number}: Success")
            else:
                run_summary.append(f"Firefox {instance_number}: Error or Login failed")
            current_running_instances.remove(instance_number)
            event.set()  # Signal that an instance has finished

        def manage_instances():
            for i in range(start_instance, end_instance + 1):
                while len(current_running_instances) >= max_instances:
                    event.wait()  # Wait until an instance finishes
                    event.clear()
                current_running_instances.append(i)
                threading.Thread(target=run_and_wait, args=(i,)).start()

            while current_running_instances:
                event.wait()  # Wait for all remaining instances to complete
                event.clear()

            show_summary()

        threading.Thread(target=manage_instances).start()

def run_multiple_firefox_with_time():
    start_instance = start_instance_var.get()
    end_instance = end_instance_var.get()
    max_instances = max_instances_var.get()

    if start_instance is not None and end_instance is not None and max_instances is not None:
        run_summary.clear()

        for i in range(start_instance, end_instance + 1):
            threading.Thread(target=run_firefox_instance, args=(i,)).start()
            if (i - start_instance + 1) % max_instances == 0:
                messagebox.showinfo("Info", f"Finished running instances {start_instance} to {i}")
                if i < end_instance:
                    simpledialog.askstring("Continue", f"Press OK to continue running instances {i+1} to {min(i+max_instances, end_instance)}")

def show_summary():
    success_count = sum(1 for summary in run_summary if "Success" in summary)
    error_count = sum(1 for summary in run_summary if "Error" in summary)
    summary_message = f"Total instances: {len(run_summary)}\nSuccess: {success_count}\nErrors: {error_count}\n\nDetails:\n" + "\n".join(run_summary)
    messagebox.showinfo("Summary", summary_message)

def watch_facebook_videos(instance_numbers):
    for instance_number in instance_numbers:
        driver = drivers.get(instance_number)
        if not driver:
            messagebox.showerror("Error", f"Firefox {instance_number} is not running.")
            continue

        try:
            video_count = int(watch_count_var.get())
            duration_per_video = int(watch_duration_var.get())
        except ValueError:
            messagebox.showerror("Error", "Please enter valid watch count and duration.")
            continue

        video_link = video_link_var.get().strip() or "https://www.facebook.com/watch"
        driver.get(video_link)

        for _ in range(video_count):
            start_time = time.time()

            while time.time() - start_time < duration_per_video:
                try:
                    video_element = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "video")))
                    driver.execute_script("arguments[0].play();", video_element)

                    if link_video_var.get():
                        if like_video_var.get():
                            try:
                                like_button = driver.find_element(By.XPATH, "//div[@class='x1ey2m1c xds687c x17qophe xg01cxk x47corl x10l6tqk x13vifvy x1ebt8du x19991ni x1dhq9h x1o1ewxj x3x9cwd x1e5q0jg x13rtm0m']")
                                like_button.click()
                            except Exception as e:
                                print(f"Error liking video: {e}")

                        if comment_video_var.get():
                            try:
                                comment = comment_text_var.get().strip()
                                if comment:
                                    comment_box = driver.find_element(By.XPATH, "//p[@class='xdj266r x11i5rnm xat24cr x1mh8g0r']")
                                    comment_box.send_keys(comment)
                                    comment_box.send_keys("\n")
                            except Exception as e:
                                print(f"Error commenting on video: {e}")

                        if share_video_var.get():
                            try:
                                share_button = driver.find_element(By.XPATH, "//div[@class='x9f619 x1n2onr6 x1ja2u2z x78zum5 x1ey2m1c xds687c x17qophe xg01cxk x47corl x10l6tqk x13vifvy x1ebt8du x19991ni x1dhq9h x1o1ewxj x3x9cwd x1e5q0jg x13rtm0m']")
                                share_button.click()
                                public_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, "//i[@class='x1b0d499 xi3auck']")))
                                public_button.click()
                                share_now_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, "//span[@class='x1lliihq x6ikm8r x10wlt62 x1n2onr6 xlyipyv xuxw1ft']")))
                                share_now_button.click()
                            except Exception as e:
                                print(f"Error sharing video: {e}")

                    time.sleep(5)
                except Exception as e:
                    print(f"Error during video watch: {e}")
                    break

            if scroll_var.get():
                try:
                    scroll_duration = int(scroll_duration_var.get())
                    scroll_end_time = time.time() + scroll_duration
                    while time.time() < scroll_end_time:
                        driver.execute_script("window.scrollBy(0, 1);")
                        time.sleep(0.01)
                except ValueError:
                    messagebox.showerror("Error", "Please enter a valid scroll duration.")
                    break

        messagebox.showinfo("Info", f"Finished watching {video_count} videos on Chrome {instance_number}.")

def set_action():
    selected_action = action_var.get()
    if selected_action == "care":
        care_window = Toplevel(root)
        care_window.title("Care Options")
        care_window.configure(bg="#e0f7fa")

        watch_video_check = Checkbutton(care_window, text="Watch Video", variable=watch_video_var, bg="#e0f7fa")
        watch_video_check.pack(pady=5)

        watch_frame = Frame(care_window, bg="#e0f7fa")
        watch_frame.pack(pady=5)
        watch_count_label = Label(watch_frame, text="Number of Videos:", bg="#e0f7fa")
        watch_count_label.pack(side="left")
        watch_count_entry = Entry(watch_frame, textvariable=watch_count_var)
        watch_count_entry.pack(side="left")

        duration_frame = Frame(care_window, bg="#e0f7fa")
        duration_frame.pack(pady=5)
        duration_label = Label(duration_frame, text="Duration per Video (seconds):", bg="#e0f7fa")
        duration_label.pack(side="left")
        duration_entry = Entry(duration_frame, textvariable=watch_duration_var)
        duration_entry.pack(side="left")

        link_video_check = Checkbutton(care_window, text="Link Video", variable=link_video_var, bg="#e0f7fa")
        link_video_check.pack(pady=5)

        link_frame = Frame(care_window, bg="#e0f7fa")
        link_frame.pack(pady=5)
        link_label = Label(link_frame, text="Video Link:", bg="#e0f7fa")
        link_label.pack(side="left")
        link_entry = Entry(link_frame, textvariable=video_link_var)
        link_entry.pack(side="left")

        def toggle_interactions(*args):
            state = "normal" if link_video_var.get() else "disabled"
            comment_video_check.config(state=state)

        link_video_var.trace_add("write", toggle_interactions)

        comment_video_check = Checkbutton(care_window, text="Comment on Video", variable=comment_video_var, state="disabled", bg="#e0f7fa")
        comment_video_check.pack(pady=5)

        comment_frame = Frame(care_window, bg="#e0f7fa")
        comment_frame.pack(pady=5)
        comment_label = Label(comment_frame, text="Comment Text:", bg="#e0f7fa")
        comment_label.pack(side="left")
        comment_entry = Entry(comment_frame, textvariable=comment_text_var)
        comment_entry.pack(side="left")

        scroll_check = Checkbutton(care_window, text="Scroll between Videos", variable=scroll_var, bg="#e0f7fa")
        scroll_check.pack(pady=5)

        scroll_frame = Frame(care_window, bg="#e0f7fa")
        scroll_frame.pack(pady=5)
        scroll_label = Label(scroll_frame, text="Scroll Duration (seconds):", bg="#e0f7fa")
        scroll_label.pack(side="left")
        scroll_entry = Entry(scroll_frame, textvariable=scroll_duration_var)
        scroll_entry.pack(side="left")

    elif selected_action == "join_group":
        join_group_window = Toplevel(root)
        join_group_window.title("Join Group Options")
        join_group_window.configure(bg="#ffeb3b")

        group_urls_frame = Frame(join_group_window, bg="#ffeb3b")
        group_urls_frame.pack(pady=5)
        group_urls_label = Label(group_urls_frame, text="Group URLs (comma separated):", bg="#ffeb3b")
        group_urls_label.pack(side="left")
        group_urls_entry = Entry(group_urls_frame, textvariable=group_urls_var, width=50)
        group_urls_entry.pack(side="left")

        save_button = Button(join_group_window, text="Save", command=save_instance_data, bg="#fbc02d")
        save_button.pack(pady=10)

    elif selected_action == "upload_reel":
        upload_reel_window = Toplevel(root)
        upload_reel_window.title("Upload Reel")
        upload_reel_window.configure(bg="#c8e6c9")

        reel_frame = Frame(upload_reel_window, bg="#c8e6c9")
        reel_frame.pack(padx=10, pady=5)
        reel_label = Label(reel_frame, text="Reel Video Files:", bg="#c8e6c9")
        reel_label.pack(side="left")

        reel_check = Checkbutton(reel_frame, text="Reel", variable=switch_reel_var, bg="#c8e6c9")
        reel_check.pack(side="left")

        reel_entry = Entry(reel_frame, textvariable=reel_folder_or_file_var, width=50, state='readonly')
        reel_entry.pack(side="left")
        reel_browse_button = Button(reel_frame, text="Browse", command=browse_files, bg="#81c784")
        reel_browse_button.pack(side="left")

        page_link_frame = Frame(upload_reel_window, bg="#c8e6c9")
        page_link_frame.pack(padx=10, pady=5)
        page_link_label = Label(page_link_frame, text="Page Link or ID:", bg="#c8e6c9")
        page_link_label.pack(side="left")
        page_link_entry = Entry(page_link_frame, textvariable=page_link_var, width=50)
        page_link_entry.pack(side="left")
        switch_page_checkbutton = Checkbutton(page_link_frame, text="Switch Page", variable=switch_page_var, bg="#c8e6c9")
        switch_page_checkbutton.pack(side="left")

        description_frame = Frame(upload_reel_window, bg="#c8e6c9")
        description_frame.pack(padx=10, pady=5)
        description_label = Label(description_frame, text="Reel Description:", bg="#c8e6c9")
        description_label.pack(side="left")
        description_entry = Entry(description_frame, textvariable=description_var, width=50)
        description_entry.pack(side="left")
        description_checkbutton = Checkbutton(description_frame, text="Include Description", variable=description_check_var, bg="#c8e6c9")
        description_checkbutton.pack(side="left")

        save_button = Button(upload_reel_window, text="Save", command=save_reel_upload_inputs, bg="#81c784")
        save_button.pack(pady=10)

    elif selected_action == "share_to_groups":
        share_to_groups_window = Toplevel(root)
        share_to_groups_window.title("Share to Groups")
        share_to_groups_window.configure(bg="#ffe0b2")

        share_video_frame = Frame(share_to_groups_window, bg="#ffe0b2")
        share_video_frame.pack(pady=5)
        share_video_label = Label(share_video_frame, text="Video Link:", bg="#ffe0b2")
        share_video_label.pack(side="left")
        share_video_entry = Entry(share_video_frame, textvariable=video_link_var, width=50)
        share_video_entry.pack(side="left")

        group_urls_frame = Frame(share_to_groups_window, bg="#ffe0b2")
        group_urls_frame.pack(pady=5)
        group_urls_label = Label(group_urls_frame, text="Group URLs (comma separated):", bg="#ffe0b2")
        group_urls_label.pack(side="left")
        group_urls_entry = Entry(group_urls_frame, textvariable=group_urls_var, width=50)
        group_urls_entry.pack(side="left")

        share_count_frame = Frame(share_to_groups_window, bg="#ffe0b2")
        share_count_frame.pack(pady=5)
        share_count_label = Label(share_count_frame, text="Number of Times to Share:", bg="#ffe0b2")
        share_count_label.pack(side="left")
        share_count_entry = Entry(share_count_frame, textvariable=share_group_count_var)
        share_count_entry.pack(side="left")

        post_text_frame = Frame(share_to_groups_window, bg="#ffe0b2")
        post_text_frame.pack(pady=5)
        post_text_label = Label(post_text_frame, text="Text to Share with Video:", bg="#ffe0b2")
        post_text_label.pack(side="left")
        post_text_entry = Entry(post_text_frame, textvariable=post_text_var, width=50)
        post_text_entry.pack(side="left")

def browse_files():
    file_paths = filedialog.askopenfilenames(filetypes=[("Video files", "*.mp4;*.mov")])
    if file_paths:
        reel_folder_or_file_var.set(','.join(file_paths))

def save_reel_upload_inputs():
    if not switch_reel_var.get():
        messagebox.showinfo("Info", "Reel upload inputs not saved. Please check the 'Reel' checkbox to enable this functionality.")
        return

    video_paths = reel_folder_or_file_var.get().split(',')
    for video_path in video_paths:
        if not os.path.exists(video_path):
            messagebox.showerror("Error", f"Reel video path does not exist: {video_path}")
            return

    page_link = page_link_var.get().strip()
    if switch_page_var.get() and not page_link:
        messagebox.showerror("Error", "Page link or ID cannot be empty.")
        return

    description = description_var.get().strip() if description_check_var.get() else ''

    messagebox.showinfo("Info", "Reel upload inputs saved successfully.")

def upload_facebook_reel(instance_numbers):
    for instance_number in instance_numbers:
        driver = drivers.get(instance_number)
        if not driver:
            messagebox.showerror("Error", f"Firefox {instance_number} is not running.")
            continue

        video_paths = reel_folder_or_file_var.get().split(',')
        page_link = page_link_var.get().strip()
        description = description_var.get().strip()
        switch_reel = switch_reel_var.get()
        switch_page = switch_page_var.get()
        description_check = description_check_var.get()
        
        if switch_reel:
            for video_path in video_paths:
                if not os.path.exists(video_path):
                    messagebox.showerror("Error", f"Reel video path does not exist: {video_path}")
                    continue

                try:
                    if switch_page and page_link:
                        # Go to the Facebook group/page
                        driver.get(page_link)

                        # Wait for and click the "Switch Now" button
                        switch_now_button = WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable((By.XPATH, "//span[text()='Switch Now']/ancestor::div[@role='none']"))
                        )
                        switch_now_button.click()
                        time.sleep(5)  # Wait for the switch to complete

                    # Navigate to the reels creation page
                    driver.get("https://www.facebook.com/reels/create")

                    # Wait for the file input element and upload the video
                    upload_button = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, "//input[@type='file']"))
                    )
                    upload_button.send_keys(video_path)
                    time.sleep(5)  # Wait for the video to upload

                    # Click the first "Next" button
                    next_button_1 = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, "//div[@aria-label='Next' and @role='button' and @tabindex='0']"))
                    )
                    next_button_1.click()
                    time.sleep(5)  # Wait for the step to complete

                    # Click the second "Next" button
                    next_button_2 = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, "//div[@aria-label='Next' and @role='button' and @tabindex='0']"))
                    )
                    next_button_2.click()
                    time.sleep(5)  # Wait for the action to complete

                    if description_check:
                        # Paste text description
                        paste_text_area = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.XPATH, "//p[@class='xdj266r x11i5rnm xat24cr x1mh8g0r x16tdsg8']"))
                        )
                        paste_text_area.send_keys(description)
                        time.sleep(5)  # Wait for the step to complete

                    # Click the "Publish" button
                    publish_button = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, "//div[@aria-label='Publish' and @role='button' and @tabindex='0']"))
                    )
                    publish_button.click()
                    time.sleep(5)  # Wait for the step to complete


                except Exception as e:
                    messagebox.showerror("Error", str(e))

def share_to_facebook_groups(instance_numbers):
    group_urls = group_urls_var.get().strip().split(',')
    video_link = video_link_var.get().strip()
    post_text = post_text_var.get().strip()
    try:
        share_count = int(share_group_count_var.get())
    except ValueError:
        messagebox.showerror("Error", "Please enter a valid number of times to share.")
        return

    for instance_number in instance_numbers:
        driver = drivers.get(instance_number)
        if not driver:
            messagebox.showerror("Error", f"Firefox {instance_number} is not running.")
            continue

        for group_url in group_urls:
            for _ in range(share_count):
                try:
                    driver.get(group_url)
                    write_something = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, "//span[contains(text(),'Write something...')]"))
                    )
                    write_something.click()

                    post_box = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, "//div[@aria-label='Create a public post…']"))
                    )
                    post_box.send_keys(video_link)
                    time.sleep(5)

                    # Select the entire video link text
                    post_box.send_keys(webdriver.common.keys.Keys.CONTROL + 'a')
                    
                    # Delete the selected text
                    post_box.send_keys(webdriver.common.keys.Keys.BACKSPACE)

                    if post_text:
                        post_box.send_keys(post_text)

                    post_button = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, "//span[text()='Post']"))
                    )
                    post_button.click()
                    time.sleep(15)
                except Exception as e:
                    print(f"Error sharing video to group {group_url} on Chrome {instance_number}: {e}")

        messagebox.showinfo("Info", f"Finished sharing video to groups on Chrome {instance_number}.")

def join_facebook_groups(instance_numbers):
    group_urls = group_urls_var.get().strip().split(',')
    for instance_number in instance_numbers:
        driver = drivers.get(instance_number)
        if not driver:
            messagebox.showerror("Error", f"Firefox {instance_number} is not running.")
            continue

        for group_url in group_urls:
            try:
                driver.get(group_url)
                join_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//div[@role='button'][@aria-label='Join group']"))
                )
                join_button.click()
                time.sleep(2)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to join group at {group_url} on Chrome {instance_number}: {e}")
                continue

        messagebox.showinfo("Info", f"Finished attempting to join groups on Chrome {instance_number}.")

def open_chrome_data_folder():
    folder_path = os.path.realpath(FIREFOX_USER_DATA_DIR)
    os.startfile(folder_path)

# Buttons for user interaction with different colors
generate_button = Button(root, text="Generate Firefox Instances", command=generate_firefox_instances, bg="#9999ff", fg="black")
generate_button.pack(pady=3)

credentials_button = Button(root, text="Enter Credentials", command=enter_credentials, bg="#ffff80", fg="black")
credentials_button.pack(pady=3)

open_folder_button = Button(root, text="Open Folder", command=open_chrome_data_folder, bg="#ffb3e6", fg="black")
open_folder_button.pack(pady=3)

# Add the button to open the "Run Firefox" dialog
open_run_firefox_dialog_button = Button(root, text="Run Firefox", command=run_firefox_dialog, bg="#4dff4d", fg="black")
open_run_firefox_dialog_button.pack(pady=3)

# Add the button to delete multiple instances
delete_account_button = Button(root, text="Delete Account", command=delete_multiple_instances, bg="#ff5c33", fg="black")
delete_account_button.pack(pady=3)

action_login_radio = Radiobutton(root, text="Login", variable=action_var, value="login", command=set_action)
action_login_radio.pack()

action_care_radio = Radiobutton(root, text="Care", variable=action_var, value="care", command=set_action)
action_care_radio.pack()

# Create radio buttons without command to avoid auto run
action_clear_data_radio = Radiobutton(root, text="Clear Data", variable=action_var, value="clear_data")
action_clear_data_radio.pack()

action_join_group_radio = Radiobutton(root, text="Join Group", variable=action_var, value="join_group", command=set_action)
action_join_group_radio.pack()

action_upload_reel_radio = Radiobutton(root, text="Upload Reel", variable=action_var, value="upload_reel", command=set_action)
action_upload_reel_radio.pack()

action_share_to_groups_radio = Radiobutton(root, text="Share to Groups", variable=action_var, value="share_to_groups", command=set_action)
action_share_to_groups_radio.pack()

action_get_id_radio = Radiobutton(root, text="Get ID", variable=action_var, value="get_id", command=set_action)
action_get_id_radio.pack()

action_get_gmail_radio = Radiobutton(root, text="Change Gmail", variable=action_var, value="get_gmail", command=set_action)
action_get_gmail_radio.pack()

action_get_date_radio = Radiobutton(root, text="Date Create FB", variable=action_var, value="get_date", command=set_action)
action_get_date_radio.pack()

action_get_photo_radio = Radiobutton(root, text="Get Photo", variable=action_var, value="get_photo", command=set_action)
action_get_photo_radio.pack()

action_get_cover_radio = Radiobutton(root, text="Get Cover", variable=action_var, value="get_cover", command=set_action)
action_get_cover_radio.pack()

# Initialize the application
initialize_app()

# Run the main loop
root.mainloop()
