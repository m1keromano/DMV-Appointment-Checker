import datetime
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoAlertPresentException, StaleElementReferenceException
from webdriver_manager.chrome import ChromeDriverManager
import json
import os
import requests

# Configuration
DMV_URL = "https://skiptheline.ncdot.gov/Webapp/Appointment/Index/a7ade79b-996d-4971-8766-97feb75254de"
LAST_APPOINTMENTS_FILE = "last_appointments.json"

# Telegram Bot Configuration 
TELEGRAM_BOT_TOKEN = "7791462398:AAFRLYcVdhhrYefpUJwS7IDCV-2WKKJ_upY" 
TELEGRAM_CHAT_ID = "7368939375"

# Notification Function (for Telegram) 
def send_telegram_notification(subject, body, parse_mode=None):
    message_text = f"{subject}\n\n{body}"
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message_text}
    if parse_mode:
        payload['parse_mode'] = parse_mode
    try:
        response = requests.post(api_url, json=payload)
        response.raise_for_status()
        print(f"Telegram notification sent successfully to chat ID {TELEGRAM_CHAT_ID}!")
    except requests.exceptions.RequestException as e:
        print(f"Error sending Telegram notification: {e}")
        print("Please double-check your TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID values.")

# Scrape dates from an office's detail page 
def scrape_dates_from_office_detail_page(driver, office_name, end_date_filter):
    appointments_for_office = set()
    today = datetime.date.today()
    print(f"  Attempting to scrape dates for '{office_name}'...")
    try:
        calendar_table = WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CLASS_NAME, "ui-datepicker-calendar")))
        print(f"  Calendar for '{office_name}' loaded.")
        available_day_elements = calendar_table.find_elements(By.XPATH, ".//td[contains(@data-handler, 'selectDay') and not(contains(@class, 'ui-datepicker-unselectable')) and .//a]")
        print(f"  Found {len(available_day_elements)} selectable days in calendar for '{office_name}'.")
        days_to_process = [{'month': int(day_el.get_attribute("data-month")) + 1, 'year': int(day_el.get_attribute("data-year")), 'day': int(day_el.find_element(By.TAG_NAME, "a").text.strip())} for day_el in available_day_elements]
        if not days_to_process:
            print(f"  No available days to process for '{office_name}' in current calendar view.")
            return appointments_for_office
        for day_info in days_to_process:
            day_month, day_year, day_num = day_info['month'], day_info['year'], day_info['day']
            current_calendar_date = datetime.date(day_year, day_month, day_num)
            if not (today <= current_calendar_date <= end_date_filter):
                continue
            print(f"    Processing day: {current_calendar_date.strftime('%Y-%m-%d')} for '{office_name}'")
            try:
                calendar_table_rechecked = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.CLASS_NAME, "ui-datepicker-calendar")))
                day_xpath = f".//td[@data-handler='selectDay' and @data-month='{day_month-1}' and @data-year='{day_year}' and .//a[text()='{day_num}']]"
                clickable_day = WebDriverWait(calendar_table_rechecked, 5).until(EC.element_to_be_clickable((By.XPATH, day_xpath)))
                clickable_day.click()
                time.sleep(1)
                time_select_container = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.step-control-content.AppointmentTime.TimeSlotDataControl")))
                time_select_element = time_select_container.find_element(By.TAG_NAME, "select")
                WebDriverWait(time_select_element, 5).until(EC.presence_of_all_elements_located((By.XPATH, "./option[@data-datetime]")))
                time_options = time_select_element.find_elements(By.TAG_NAME, "option")
                for option_el in time_options:
                    datetime_str = option_el.get_attribute("data-datetime")
                    if datetime_str:
                        full_appointment_datetime = datetime.datetime.strptime(datetime_str, "%m/%d/%Y %I:%M:%S %p")
                        if today <= full_appointment_datetime.date() <= end_date_filter:
                            formatted_time = full_appointment_datetime.strftime('%Y-%m-%d %I:%M %p')
                            appointments_for_office.add(f"{office_name} - {formatted_time}")
                            print(f"      Found time slot: {office_name} - {formatted_time}")
            except Exception as e:
                print(f"    Error processing day {current_calendar_date.strftime('%Y-%m-%d')} for '{office_name}': {e}")
    except Exception as e:
        print(f"  General error scraping detail page for '{office_name}': {e}")
    return appointments_for_office

# Web Scraping Function 
def get_available_appointments(driver):
    all_found_appointments = set()
    today = datetime.date.today()
    end_date_filter = today + datetime.timedelta(days=30)
    try:
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.step-control-content.UnitIdList")))
        print("Main office list loaded for iteration.")
        active_office_elements = driver.find_elements(By.XPATH, "//div[contains(@class, 'QflowObjectItem') and contains(@class, 'Active-Unit')]")
        print(f"Found {len(active_office_elements)} 'Active-Unit' (potentially available) office containers.")
        office_names_to_process = [office_el.find_element(By.XPATH, "./div/div[1]").text.strip() for office_el in active_office_elements]
        if not office_names_to_process:
            print("No active offices found to process.")
            return all_found_appointments
        for office_name in office_names_to_process:
            try:
                office_xpath = f"//div[contains(@class, 'QflowObjectItem') and contains(@class, 'Active-Unit') and ./div/div[contains(text(), '{office_name}')]]"
                clickable_office = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, office_xpath)))
                clickable_office.click()
                print(f"  Clicked on '{office_name}' office.")
                time.sleep(3)
                current_office_appointments = scrape_dates_from_office_detail_page(driver, office_name, end_date_filter)
                all_found_appointments.update(current_office_appointments)
                print(f"  Navigating back from '{office_name}' detail page...")
                driver.back()
                WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.step-control-content.UnitIdList")))
                print("  Successfully navigated back to main office list.")
                time.sleep(2)
            except Exception as e:
                print(f"  An unhandled error occurred while processing office '{office_name}': {e}")
                driver.back()
    except Exception as e:
        print(f"General error during web scraping in get_available_appointments: {e}")
    return all_found_appointments

# Main Logic
def run_monitor():
    last_known_appointments = set()
    if os.path.exists(LAST_APPOINTMENTS_FILE):
        try:
            with open(LAST_APPOINTMENTS_FILE, 'r') as f:
                last_known_appointments = set(json.load(f))
            print(f"Loaded {len(last_known_appointments)} last known appointments.")
        except json.JSONDecodeError:
            print(f"Error reading '{LAST_APPOINTMENTS_FILE}', starting fresh.")
    else:
        print(f"No previous appointments file found, starting fresh.")

    while True:
        print(f"\n--- Checking for appointments at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
        driver = None 
        try:
            options = webdriver.ChromeOptions()
            options.add_argument("--headless")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            prefs = {"profile.managed_default_content_settings.geolocation": 2}
            options.add_experimental_option("prefs", prefs)
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            
            driver.get(DMV_URL)
            
            make_appt_button = WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.ID, "cmdMakeAppt")))
            make_appt_button.click()
            print("Clicked 'Make an Appointment' button.")
            
            try:
                WebDriverWait(driver, 5).until(EC.alert_is_present())
                alert = driver.switch_to.alert
                print(f"Alert found with text: '{alert.text}'")
                alert.accept()
                print("Alert accepted.")
            except TimeoutException:
                print("No JavaScript alert found. Proceeding...")

            WebDriverWait(driver, 20).until(EC.invisibility_of_element_located((By.ID, "BlockLoader")))
            print("Page loader has disappeared.")
            
            service_type_div = WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, "//div[@class='form-control-child' and contains(text(), 'New driver over 18, new N.C. resident, REAL ID')]")))
            service_type_div.click()
            print("Selected 'New driver over 18, new N.C. resident, REAL ID'.")
            time.sleep(1)

            current_appointments = get_available_appointments(driver)
            
            # Compare and Notify
            new_appointments = current_appointments - last_known_appointments
            if new_appointments:
                subject = "NEW NC DMV Appointment Alert!"
                body = "New DMV appointments have become available:\n\n"
                for appt in sorted(list(new_appointments)):
                    body += f"- {appt}\n"
                body += f"\nReview details here: {DMV_URL}"
                send_telegram_notification(subject, body)
                last_known_appointments.update(new_appointments)
            else:
                print("No new appointments found since the last check.")
            
            # Save all currently found appointments for the next run
            with open(LAST_APPOINTMENTS_FILE, 'w') as f:
                json.dump(list(current_appointments), f)
            print(f"Current appointment state saved to '{LAST_APPOINTMENTS_FILE}'.")

        except Exception as e:
            print(f"!!! An error occurred during the check cycle: {e}")
        
        finally:
            # Quit the driver at the end of the cycle to ensure a fresh start
            if driver:
                print("Closing WebDriver for this cycle.")
                driver.quit()

        print("Waiting for 10 seconds before next check...")
        time.sleep(10)

if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or "YOUR_BOT_TOKEN" in TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or "YOUR_CHAT_ID" in TELEGRAM_CHAT_ID:
        print("!!! WARNING: Telegram credentials are not set. Notifications will not be sent.")
    print("Starting NC DMV appointment monitor.")
    run_monitor()