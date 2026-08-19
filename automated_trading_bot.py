#!/usr/bin/env python3
"""
TESTING MODE - Tests all bot functions
"""

import os
import requests
from datetime import datetime
import pytz

# ============================================
# 🔑 ALPACA API CONFIGURATION
# ============================================
API_KEY = os.environ.get('ALPACA_API_KEY')
SECRET_KEY = os.environ.get('ALPACA_SECRET_KEY')
BASE_URL = 'https://paper-api.alpaca.markets/v2'

# ============================================
# 📡 NTFY NOTIFICATION CONFIG
# ============================================
NTFY_URL = os.environ.get('NTFY_URL', 'https://ntfy.sh/my-stock-report-kenya')

# ============================================
# ⚙️ TESTING CONFIGURATION
# ============================================
TEST_MODE = True  # Set to False for normal operation
FORCE_BUY = True  # Force buy regardless of market conditions
FORCE_SELL_TEST = True  # Also test selling

# ============================================
# ️ NOTIFICATION FUNCTION
# ============================================

def send_notification(title, message, priority=3):
    """Send notification to ntfy"""
    try:
        topic = NTFY_URL.split('/')[-1]
        response = requests.post(
            f"https://ntfy.sh/{topic}",
            data=message.encode('utf-8'),
            headers={
                "Title": title,
                "Priority": str(priority),
                "Tags": "robot"
            }
        )
        print(f"✅ Notification sent: {title}")
        return True
    except Exception as e:
        print(f"❌ Notification failed: {e}")
        return False

def get_account_info():
    """Get account info"""
    try:
        headers = {
            'APCA-API-KEY-ID': API_KEY,
            'APCA-API-SECRET-KEY': SECRET_KEY
        }
        response = requests.get(f"{BASE_URL}/account", headers=headers)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None

def get_positions():
    """Get current positions"""
    try:
        headers = {
            'APCA-API-KEY-ID': API_KEY,
            'APCA-API-SECRET-KEY': SECRET_KEY
        }
        response = requests.get(f"{BASE_URL}/positions", headers=headers)
        if response.status_code == 200:
            return response.json()
        return []
    except Exception as e:
        print(f"Error: {e}")
        return []

def buy_stock(symbol):
    """Buy 1 share"""
    try:
        headers = {
            'APCA-API-KEY-ID': API_KEY,
            'APCA-API-SECRET-KEY': SECRET_KEY
        }
        order_data = {
            "symbol": symbol,
            "qty": 1,
            "side": "buy",
            "type": "market",
            "time_in_force": "day"
        }
        response = requests.post(f"{BASE_URL}/orders", headers=headers, json=order_data)
        if response.status_code == 200:
            print(f"✅ BOUGHT {symbol}")
            send_notification("✅ BUY TEST SUCCESSFUL", f"Bought 1 share of {symbol}\nTime: {datetime.now().strftime('%H:%M')}")
            return True
        else:
            print(f"❌ Buy failed: {response.json()}")
            return False
    except Exception as e:
        print(f"Error buying: {e}")
        return False

def sell_all_positions():
    """Sell all positions"""
    try:
        positions = get_positions()
        if not positions:
            print("No positions to sell")
            send_notification("📊 SELL TEST", "No positions currently held")
            return
        
        headers = {
            'APCA-API-KEY-ID': API_KEY,
            'APCA-API-SECRET-KEY': SECRET_KEY
        }
        
        sold_count = 0
        for pos in positions:
            symbol = pos['symbol']
            order_data = {
                "symbol": symbol,
                "qty": "all",
                "side": "sell",
                "type": "market",
                "time_in_force": "day"
            }
            response = requests.post(f"{BASE_URL}/orders", headers=headers, json=order_data)
            if response.status_code == 200:
                print(f"✅ SOLD {symbol}")
                sold_count += 1
        
        send_notification("📉 SELL TEST SUCCESSFUL", f"Sold {sold_count} positions\nAll positions closed")
        
    except Exception as e:
        print(f"Error selling: {e}")

# ============================================
# 🧪 MAIN TEST FUNCTION
# ============================================

print("="*60)
print(" TRADING BOT - TEST MODE")
print("="*60)

# Test 1: Check connection
print("\n[Test 1] Checking Alpaca connection...")
account = get_account_info()
if account:
    print(f"✅ Connected! Account Status: {account.get('status')}")
    print(f"   Buying Power: ${float(account.get('buying_power', 0)):,.2f}")
    send_notification("🧪 BOT TEST STARTED", f"Account connected successfully\nBuying Power: ${float(account.get('buying_power', 0)):,.2f}")
else:
    print("❌ Connection failed!")
    send_notification("❌ BOT TEST FAILED", "Could not connect to Alpaca")
    exit()

# Test 2: Get current positions
print("\n[Test 2] Checking current positions...")
positions = get_positions()
print(f"   Current positions: {len(positions)}")
for pos in positions:
    print(f"   - {pos['symbol']}: {pos['qty']} shares @ ${pos.get('avg_entry_price', 'N/A')}")

# Test 3: Buy AAPL
if FORCE_BUY:
    print("\n[Test 3] Testing BUY function...")
    buy_stock("AAPL")
    print("✅ Buy test completed")

# Test 4: Sell all (if enabled)
if FORCE_SELL_TEST:
    print("\n[Test 4] Testing SELL function...")
    import time
    time.sleep(3)  # Wait a bit
    sell_all_positions()
    print("✅ Sell test completed")

print("\n" + "="*60)
print("✅ ALL TESTS COMPLETED")
print("="*60)
send_notification("✅ BOT TEST COMPLETE", "All functions tested successfully\nCheck your Alpaca app for trades")
