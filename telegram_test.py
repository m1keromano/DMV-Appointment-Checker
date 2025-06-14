import requests
import json
import datetime 
import os

# --- Telegram Bot Configuration ---
TELEGRAM_BOT_TOKEN = "7791462398:AAFRLYcVdhhrYefpUJwS7IDCV-2WKKJ_upY"
TELEGRAM_CHAT_ID = "7368939375"

def send_telegram_message(message_text,  parse_mode=None): 
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message_text,
    }
    if parse_mode: 
        payload['parse_mode'] = parse_mode

    try:
        response = requests.post(api_url, json=payload)
        response.raise_for_status()
        print(f"Telegram API response: {json.dumps(response.json(), indent=2)}")
        if response.json().get("ok"):
            print("Successfully sent message to Telegram!")
        else:
            print(f"Failed to send message: {response.json().get('description', 'Unknown error')}")

    except requests.exceptions.RequestException as e:
        print(f"Error sending Telegram message: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"API Response Content: {e.response.text}") 
        print(f"Please double-check your TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID values.")
        print(f"Ensure your Telegram app is open and you have an active chat with the bot.")


if __name__ == "__main__":
    # Test Notification 
    test_subject = "Test Notification from DMV Monitor"
    test_body = (
        "This is a test message to confirm Telegram notifications are working.\n"
        "If you see this, your bot setup is correct!\n\n"
        "Current Time: " + datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S %p %Z')
    )

    full_message = f"{test_subject}\n\n{test_body}" 

    if TELEGRAM_CHAT_ID == "YOUR_CHAT_ID_GOES_HERE":
        print("\nERROR: TELEGRAM_CHAT_ID is not set in test_telegram_bot.py!")
        print("Please replace 'YOUR_CHAT_ID_GOES_HERE' with your actual chat ID.")
        print("You can get your chat ID by chatting with @userinfobot in Telegram.")
    else:
        print("Attempting to send test Telegram notification...")
        send_telegram_message(full_message)