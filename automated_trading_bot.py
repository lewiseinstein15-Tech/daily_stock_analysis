#!/usr/bin/env python3
"""
FORCE TEST MODE - Forces Buy and Sell to prove it works
"""

import os
import requests
import time
from datetime import datetime

# Configuration
API_KEY = os.environ.get('ALPACA_API_KEY')
SECRET_KEY = os.environ.get('ALPACA_SECRET_KEY')
BASE_URL = 'https://paper-api.alpaca.markets/v2'
NTFY_TOPIC = "my-stock-report-kenya"

def send_notification(title, message):
    """Send notification (ASCII only to prevent errors)"""
    try:
        response = requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode('ascii', 'ignore').decode('ascii'),
            headers={
                "Title": title.encode('ascii', 'ignore').decode('ascii'),
                "Priority": "1"
            }
        )
        print(f"Notification sent: {title}")
    except Exception as e:
        print(f"Notification failed: {e}")

print("STARTING FORCE TEST...")
send_notification("TEST STARTED", "Forcing Buy and Sell test now...")

headers = {
    'APCA-API-KEY-ID': API_KEY,
    'APCA-API-SECRET-KEY': SECRET_KEY
}

# STEP 1: FORCE BUY
print("STEP 1: Buying 1 share of AAPL...")
buy_data = {
    "symbol": "AAPL",
    "qty": 1,
    "side": "buy",
    "type": "market",
    "time_in_force": "day"
}

buy_response = requests.post(f"{BASE_URL}/orders", headers=headers, json=buy_data)

if buy_response.status_code == 200:
    print("SUCCESS: Bought AAPL")
    send_notification("BUY SUCCESS", "Successfully bought 1 share of AAPL!")
else:
    print(f"BUY FAILED: {buy_response.json()}")
    send_notification("BUY FAILED", f"Error: {buy_response.json()}")

# Wait 5 seconds so the order processes
print("Waiting 5 seconds...")
time.sleep(5)

# STEP 2: FORCE SELL
print("STEP 2: Selling 1 share of AAPL...")
sell_data = {
    "symbol": "AAPL",
    "qty": 1,
    "side": "sell",
    "type": "market",
    "time_in_force": "day"
}

sell_response = requests.post(f"{BASE_URL}/orders", headers=headers, json=sell_data)

if sell_response.status_code == 200:
    print("SUCCESS: Sold AAPL")
    send_notification("SELL SUCCESS", "Successfully sold 1 share of AAPL! Test Complete.")
else:
    print(f"SELL FAILED: {sell_response.json()}")
    send_notification("SELL FAILED", f"Error: {sell_response.json()}")

print("TEST COMPLETE")
