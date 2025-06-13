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

from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

# --- Configuration ---
DMV_URL = "https://skiptheline.ncdot.gov/Webapp/Appointment/Index/a7ade79b-996d-4971-8766-97feb75254de"
LAST_APPOINTMENTS_FILE = "last_appointments.json"

# --- Notification Function (Prints to Terminal in this debug mode) ---
def debug_print_notification(subject, body):
    """
    Prints the notification subject and body to the terminal for debugging purposes.
    """
    print("\n" + "="*50)
    print(f"DEBUG NOTIFICATION - SUBJECT: {subject}")
    print("-"*50)
    print(f"BODY:\n{body}")
    print("="*50 + "\n")

# --- Date Scraping Helper ---
def scrape_dates_from_office_detail_page(driver, office_name, end_date_filter):
    
    appointments_for_office = set()
    today = datetime.date.today()

    print(f"  Attempting to scrape dates for '{office_name}'...")
    try:
        # 1. Wait for the calendar table to load 
        calendar_table = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CLASS_NAME, "ui-datepicker-calendar"))
        )
        print(f"  Calendar for '{office_name}' loaded.")

        # 2. Find all selectable days in the current calendar view
        available_day_elements = calendar_table.find_elements(By.XPATH, ".//td[contains(@data-handler, 'selectDay') and not(contains(@class, 'ui-datepicker-unselectable')) and .//a]")
        print(f"  Found {len(available_day_elements)} selectable days in calendar for '{office_name}'.")

        # Collect day details before clicking to avoid StaleElementReferenceException
        days_to_process = []
        for day_el in available_day_elements:
            try:
                data_month = day_el.get_attribute("data-month") 
                data_year = day_el.get_attribute("data-year")
                day_num = day_el.find_element(By.TAG_NAME, "a").text.strip()
                days_to_process.append({'month': int(data_month) + 1, 'year': int(data_year), 'day': int(day_num)}) 
            except Exception as e:
                print(f"    Error collecting day info: {e}. Element HTML: {day_el.get_attribute('outerHTML')}")
                continue

        if not days_to_process:
            print(f"  No available days to process for '{office_name}' in current calendar view.")
            return appointments_for_office

        for day_info in days_to_process:
            day_month = day_info['month']
            day_year = day_info['year']
            day_num = day_info['day']

            current_calendar_date = datetime.date(day_year, day_month, day_num)

            # Filter days by "next month" criteria 
            if not (today <= current_calendar_date <= end_date_filter):
                print(f"    Day {current_calendar_date.strftime('%Y-%m-%d')} for '{office_name}' is outside filter. Skipping.")
                continue

            print(f"    Processing day: {current_calendar_date.strftime('%Y-%m-%d')} for '{office_name}'")
            try:
                day_xpath = f".//td[@data-handler='selectDay' and @data-month='{day_month-1}' and @data-year='{day_year}' and .//a[text()='{day_num}']]"
                
                # Need to re-find the calendar table if it was refreshed then find day
                calendar_table_rechecked = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "ui-datepicker-calendar"))
                )
                
                clickable_day = WebDriverWait(calendar_table_rechecked, 5).until( # Search within the rechecked table
                    EC.element_to_be_clickable((By.XPATH, day_xpath))
                )
                
                clickable_day.click()
                print(f"    Clicked day {day_num} for '{office_name}'.")
                time.sleep(1) # Small pause for time slots to load

                # --- Scrape time slots from the dropdown ---
                # Find the select element using its unique parent container classes.
                time_select_container = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.step-control-content.AppointmentTime.TimeSlotDataControl"))
                )
                time_select_element = time_select_container.find_element(By.TAG_NAME, "select")

                # Get all options
                WebDriverWait(time_select_element, 5).until(
                    EC.presence_of_all_elements_located((By.XPATH, "./option[@data-datetime]"))
                )
                time_options = time_select_element.find_elements(By.TAG_NAME, "option")
                
                found_times_for_day = False
                for option_el in time_options:
                    datetime_str = option_el.get_attribute("data-datetime")
                    if datetime_str: 
                        try:
                            # Parse the 'M/D/YYYY HH:MM:SS AM/PM' format
                            full_appointment_datetime = datetime.datetime.strptime(datetime_str, "%m/%d/%Y %I:%M:%S %p")
                            
                            # Final check: Filter by time period criteria 
                            if today <= full_appointment_datetime.date() <= end_date_filter:
                                formatted_time = full_appointment_datetime.strftime('%Y-%m-%d %I:%M %p')
                                appointments_for_office.add(f"{office_name} - {formatted_time}")
                                print(f"      Found time slot: {office_name} - {formatted_time}")
                                found_times_for_day = True
                        except ValueError:
                            print(f"      Could not parse datetime string '{datetime_str}' from option.")
                            continue
                
                if not found_times_for_day:
                    print(f"    No specific time slots found for {current_calendar_date.strftime('%Y-%m-%d')} at '{office_name}'.")


            except TimeoutException:
                print(f"    Timeout waiting for day or time slots for {current_calendar_date.strftime('%Y-%m-%d')} at '{office_name}'.")
            except Exception as e:
                print(f"    Error processing day {current_calendar_date.strftime('%Y-%m-%d')} for '{office_name}': {e}")

    except TimeoutException:
        print(f"  Timeout waiting for calendar/time selector elements for '{office_name}'.")
    except Exception as e:
        print(f"  General error scraping detail page for '{office_name}': {e}")
    return appointments_for_office


# --- Web Scraping Function ---
def get_available_appointments(driver):
    """
    Orchestrates the scraping process:
    1. Finds all available offices on the main list.
    2. Clicks into each available office.
    3. Calls helper to scrape dates from the office detail page.
    4. Navigates back to the main office list.

    Args:
        driver: The Selenium WebDriver instance.

    Returns:
        A set of strings, where each string represents a unique available
        appointment (e.g., "Office Name -YYYY-MM-DD") across all offices.
    """
    all_found_appointments = set()
    today = datetime.date.today()
    end_date_filter = today + datetime.timedelta(days=100) #Testing farther out for refinement CHANGE LATER

    try:
        print("Waiting for main office list container ('div.step-control-content.UnitIdList')...")
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.step-control-content.UnitIdList"))
        )
        print("Main office list loaded for iteration.")

        active_office_elements = driver.find_elements(By.XPATH, "//div[contains(@class, 'QflowObjectItem') and contains(@class, 'Active-Unit')]")
        print(f"Found {len(active_office_elements)} 'Active-Unit' (potentially available) office containers.")

        office_names_to_process = []
        for office_el in active_office_elements:
            try:
                office_name_div = office_el.find_element(By.XPATH, "./div/div[1]")
                office_name = office_name_div.text.strip()
                office_names_to_process.append(office_name)
            except Exception as e:
                print(f"Could not extract name from an active office element during initial scan: {e}. Element HTML: {office_el.get_attribute('outerHTML')}")
                continue

        if not office_names_to_process:
            print("No active offices found to process.")
            return all_found_appointments

        for office_name in office_names_to_process:
            try:
                office_xpath = f"//div[contains(@class, 'QflowObjectItem') and contains(@class, 'Active-Unit') and ./div/div[contains(text(), '{office_name}')]]"

                print(f"\n  Attempting to click on office: '{office_name}' using XPath: '{office_xpath}'...")
                clickable_office = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, office_xpath))
                )
                print(f"  Found clickable element for '{office_name}'. HTML: {clickable_office.get_attribute('outerHTML')}")

                clickable_office.click()
                print(f"  Clicked on '{office_name}' office.")
                time.sleep(3)

                current_office_appointments = scrape_dates_from_office_detail_page(driver, office_name, end_date_filter)
                all_found_appointments.update(current_office_appointments)

                print(f"  Navigating back from '{office_name}' detail page...")
                driver.back()
                
                # Wait for the main office list to become visible again after going back
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.step-control-content.UnitIdList"))
                )
                print(f"  Successfully navigated back to main office list.")
                time.sleep(2)

            except StaleElementReferenceException:
                print(f"  StaleElementReferenceException for '{office_name}'. Re-finding for next iteration if possible.")
            except TimeoutException:
                print(f"  Timeout processing '{office_name}'. Might have failed to load detail page or find elements.")
                try:
                    driver.back()
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.step-control-content.UnitIdList")))
                except:
                    print("    Could not recover to main list. WebDriver might need restart.")
                    raise
            except Exception as e:
                print(f"  An unhandled error occurred while processing office '{office_name}': {e}")
                try:
                    driver.back()
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.step-control-content.UnitIdList")))
                except:
                    print("    Could not recover to main list. WebDriver might need restart.")
                    raise

    except Exception as e:
        print(f"General error during web scraping in get_available_appointments (orchestrator): {e}")
    return all_found_appointments


# --- Main Logic ---
def run_monitor():
    driver = None
    try:
        options = webdriver.ChromeOptions()
        # options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

        prefs = {
            "profile.managed_default_content_settings.geolocation": 2,
            "profile.default_content_setting_values.notifications": 2,
            "profile.default_content_setting_values.popups": 2,
            "profile.default_content_setting_values.automatic_downloads": 2,
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
            "safeBrowse.enabled": True
        }
        options.add_experimental_option("prefs", prefs)

        options.add_argument("--disable-extensions")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--disable-setuid-sandbox")
        options.add_argument("--no-zygote")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-site-navigation-jingle")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--disable-sync")

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        print("Selenium WebDriver initialized.")

        last_known_appointments = set()
        if os.path.exists(LAST_APPOINTMENTS_FILE):
            try:
                with open(LAST_APPOINTMENTS_FILE, 'r') as f:
                    loaded_appointments = json.load(f)
                    last_known_appointments = set(loaded_appointments)
                print(f"Loaded {len(last_known_appointments)} last known appointments from '{LAST_APPOINTMENTS_FILE}'.")
            except json.JSONDecodeError:
                print(f"Error reading '{LAST_APPOINTMENTS_FILE}', starting fresh.")
                last_known_appointments = set()
        else:
            print(f"No previous appointments file ('{LAST_APPOINTMENTS_FILE}') found, starting fresh.")


        while True:
            print(f"\n--- Checking for appointments at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
            current_appointments = set()
            try:
                driver.get(DMV_URL)

                print("Waiting for 'Make an Appointment' button...")
                make_appt_button = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.ID, "cmdMakeAppt"))
                )
                make_appt_button.click()
                print("Clicked 'Make an Appointment' button.")
                time.sleep(2)


                print("Checking for 'share location' JavaScript alert...")
                try:
                    WebDriverWait(driver, 5).until(EC.alert_is_present())
                    alert = driver.switch_to.alert
                    alert_text = alert.text
                    print(f"Alert found with text: '{alert_text}'")
                    alert.accept()
                    print("Alert accepted.")
                    time.sleep(1)
                except TimeoutException:
                    print("No JavaScript alert found (or it timed out). Proceeding...")
                except NoAlertPresentException:
                    print("No JavaScript alert found (no alert present). Proceeding...")
                except Exception as alert_e:
                    print(f"Error handling alert: {alert_e}. Proceeding anyway.")
                    pass


                print("Waiting for service type selection: 'New driver over 18, new N.C. resident, REAL ID'...")
                service_type_div = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.XPATH, "//div[@class='form-control-child' and contains(text(), 'New driver over 18, new N.C. resident, REAL ID')]"))
                )
                service_type_div.click()
                print("Selected 'New driver over 18, new N.C. resident, REAL ID'.")
                time.sleep(3)


                # --- Call the main scraping orchestrator ---
                found_appointments = get_available_appointments(driver)
                current_appointments.update(found_appointments)

                new_appointments = current_appointments - last_known_appointments

                if new_appointments:
                    subject = "DEBUG: NEW NC DMV Appointment Alert!"
                    body = "New DMV appointments in the next month have become available:\n\n"
                    for appt in sorted(list(new_appointments)):
                        body += f"- {appt}\n"
                    body += "\nReview the details on the website: " + DMV_URL

                    debug_print_notification(subject, body)
                    last_known_appointments.update(new_appointments)
                else:
                    print("No new appointments found since the last check.")

                with open(LAST_APPOINTMENTS_FILE, 'w') as f:
                    json.dump(list(current_appointments), f)
                print(f"Current appointment state saved to '{LAST_APPOINTMENTS_FILE}'.")

            except Exception as e:
                print(f"!!! An error occurred during the check cycle: {e}")
                print("!!! Attempting to re-initialize WebDriver for next cycle.")
                if driver:
                    driver.quit()
                driver = None
                time.sleep(5)
                continue

            print(f"Waiting for 60 seconds before next check...")
            time.sleep(60)

    except KeyboardInterrupt:
        print("\nMonitor stopped by user (Ctrl+C).")
    except Exception as e:
        print(f"\nAn unexpected error occurred during setup or main loop: {e}")
    finally:
        if driver:
            print("Closing Selenium WebDriver.")
            driver.quit()

# --- Entry Point ---
if __name__ == "__main__":
    print("Starting NC DMV appointment monitor (Debug Mode - Terminal Output).")
    run_monitor()