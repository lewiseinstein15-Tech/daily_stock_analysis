#!/usr/bin/env python3
"""
AI Trading Bot for Alpaca Paper Trading
Runs automatically via GitHub Actions
Follows strict market rules and risk management
"""

import os
import requests
import json
from datetime import datetime, timedelta
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
# 📊 TRADING RULES & PARAMETERS
# ============================================
BUY_SIGNAL_THRESHOLD = 60        # Buy when signal >= 60
SELL_SIGNAL_THRESHOLD = 30       # Sell when signal <= 30
TAKE_PROFIT_PERCENT = 15         # Take profit at +15%
STOP_LOSS_PERCENT = 8            # Stop loss at -8%
MAX_POSITION_PERCENT = 20        # Max 20% of account per stock
CASH_RESERVE_PERCENT = 20        # Keep 20% cash reserve
MAX_STOCKS = 5                   # Maximum 5 stocks at once
STOCKS_TO_TRADE = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA']

# ============================================
# 🛠️ HELPER FUNCTIONS
# ============================================

def send_notification(title, message, priority=3):
    """Send a clean notification to ntfy"""
    try:
        # Extract just the topic name from the URL
        topic = NTFY_URL.split('/')[-1]
        
        # Send as plain text with headers (looks much better on mobile)
        response = requests.post(
            f"https://ntfy.sh/{topic}",
            data=message.encode('utf-8'),
            headers={
                "Title": title,
                "Priority": str(priority),
                "Tags": "robot,chart_with_upwards_trend"
            }
        )
        print(f"✅ Notification sent: {title}")
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Notification failed: {e}")
        return False

def get_account_info():
    """Get account balance and status"""
    try:
        headers = {
            'APCA-API-KEY-ID': API_KEY,
            'APCA-API-SECRET-KEY': SECRET_KEY
        }
        response = requests.get(f"{BASE_URL}/account", headers=headers)
        if response.status_code == 200:
            return response.json()
        print(f"❌ Failed to get account info: {response.status_code}")
        return None
    except Exception as e:
        print(f"❌ Error getting account: {e}")
        return None

def get_current_positions():
    """Get all current stock positions"""
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
        print(f"❌ Error getting positions: {e}")
        return []

def is_market_open():
    """Check if US market is open (9:30 AM - 4:00 PM ET, Mon-Fri)"""
    try:
        et_timezone = pytz.timezone('America/New_York')
        now_et = datetime.now(et_timezone)
        
        # Check if weekend
        if now_et.weekday() >= 5:  # Saturday=5, Sunday=6
            print("📅 Market is CLOSED (Weekend)")
            return False
        
        # Check market hours (9:30 AM - 4:00 PM ET)
        market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        
        if market_open <= now_et <= market_close:
            print(f"✅ Market is OPEN (Current ET time: {now_et.strftime('%H:%M')})")
            return True
        else:
            print(f"📅 Market is CLOSED (Current ET time: {now_et.strftime('%H:%M')})")
            return False
    except Exception as e:
        print(f" Error checking market hours: {e}")
        return False

def get_vix_level():
    """Get VIX (volatility index) - lower is better"""
    try:
        headers = {
            'APCA-API-KEY-ID': API_KEY,
            'APCA-API-SECRET-KEY': SECRET_KEY
        }
        response = requests.get(f"{BASE_URL}/stocks/VIX/bars", 
                               headers=headers, 
                               params={'timeframe': '1Day', 'limit': 1})
        if response.status_code == 200:
            data = response.json()
            if data.get('bars'):
                vix_value = data['bars'][0].get('c', 20)
                print(f"📊 VIX Level: {vix_value}")
                return vix_value
    except Exception as e:
        print(f"⚠️ Could not get VIX: {e}")
    return 20

def get_market_signal():
    """Get market signal based on SPY momentum"""
    print("📊 Calculating market signal...")
    
    try:
        headers = {
            'APCA-API-KEY-ID': API_KEY,
            'APCA-API-SECRET-KEY': SECRET_KEY
        }
        
        response = requests.get(f"{BASE_URL}/stocks/SPY/bars",
                               headers=headers,
                               params={'timeframe': '1Day', 'limit': 5})
        
        if response.status_code == 200:
            data = response.json()
            bars = data.get('bars', [])
            
            if len(bars) >= 2:
                oldest_price = bars[0].get('c', 0)
                latest_price = bars[-1].get('c', 0)
                change_percent = ((latest_price - oldest_price) / oldest_price) * 100
                
                print(f"   SPY 5-day change: {change_percent:.2f}%")
                
                if change_percent > 2:
                    signal = 80
                elif change_percent > 0:
                    signal = 65
                elif change_percent > -2:
                    signal = 45
                else:
                    signal = 25
                
                print(f"   Market Signal: {signal}/100")
                return signal
    except Exception as e:
        print(f"⚠️ Could not calculate signal: {e}")
    
    return 50

def buy_stock(symbol, qty, buying_power):
    """Place a buy order with risk checks"""
    try:
        headers = {
            'APCA-API-KEY-ID': API_KEY,
            'APCA-API-SECRET-KEY': SECRET_KEY
        }
        
        position_value = qty * 150
        max_allowed = buying_power * (MAX_POSITION_PERCENT / 100)
        
        if position_value > max_allowed:
            print(f"⚠️ Skipping {symbol}: Position too large")
            return False
        
        order_data = {
            "symbol": symbol,
            "qty": qty,
            "side": "buy",
            "type": "market",
            "time_in_force": "day"
        }
        
        response = requests.post(f"{BASE_URL}/orders", headers=headers, json=order_data)
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ BOUGHT {qty} {symbol} @ market")
            send_notification(
                " BUY ORDER",
                f"Bought {qty} {symbol}\nSignal: Good market conditions\nTime: {datetime.now().strftime('%H:%M')}"
            )
            return True
        else:
            print(f"❌ Buy order failed for {symbol}: {response.json()}")
            return False
    except Exception as e:
        print(f"❌ Error buying {symbol}: {e}")
        return False

def sell_stock(symbol, qty=None, reason=""):
    """Place a sell order"""
    try:
        headers = {
            'APCA-API-KEY-ID': API_KEY,
            'APCA-API-SECRET-KEY': SECRET_KEY
        }
        
        order_data = {
            "symbol": symbol,
            "qty": qty if qty else "all",
            "side": "sell",
            "type": "market",
            "time_in_force": "day"
        }
        
        response = requests.post(f"{BASE_URL}/orders", headers=headers, json=order_data)
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ SOLD {symbol} - Reason: {reason}")
            send_notification(
                " SELL ORDER",
                f"Sold {symbol}\nReason: {reason}\nTime: {datetime.now().strftime('%H:%M')}"
            )
            return True
        else:
            print(f"❌ Sell order failed: {response.json()}")
            return False
    except Exception as e:
        print(f"❌ Error selling {symbol}: {e}")
        return False

def check_profit_loss(positions):
    """Check if any positions hit take-profit or stop-loss"""
    for pos in positions:
        try:
            symbol = pos['symbol']
            qty = float(pos['qty'])
            avg_price = float(pos['avg_entry_price'])
            current_price = float(pos['current_price'])
            
            pnl_percent = ((current_price - avg_price) / avg_price) * 100
            
            print(f"   {symbol}: {pnl_percent:+.2f}% (${avg_price} → ${current_price})")
            
            if pnl_percent >= TAKE_PROFIT_PERCENT:
                print(f"   🎯 Take-profit hit for {symbol} (+{pnl_percent:.2f}%)")
                sell_stock(symbol, reason=f"Take-profit +{pnl_percent:.1f}%")
            
            elif pnl_percent <= -STOP_LOSS_PERCENT:
                print(f"   🛑 Stop-loss hit for {symbol} ({pnl_percent:.2f}%)")
                sell_stock(symbol, reason=f"Stop-loss {pnl_percent:.1f}%")
                
        except Exception as e:
            print(f"️ Error checking P&L for {pos.get('symbol', 'unknown')}: {e}")

# ============================================
# 🤖 MAIN TRADING LOGIC
# ============================================

def run_trading_bot():
    """Main trading bot function"""
    print("="*60)
    print("🤖 AI TRADING BOT STARTING")
    print(f" Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    # Rule 1: Check if market is open
    if not is_market_open():
        print("⏰ Market is closed. Exiting.")
        send_notification(" Bot Skipped", "Market is closed. Next run: Next trading day")
        return
    
    # Rule 2: Check VIX (volatility)
    vix = get_vix_level()
    if vix > 30:
        print(f"️ VIX too high ({vix}). Market too volatile. Skipping.")
        send_notification("️ Bot Skipped", f"VIX too high: {vix}. Market too volatile.")
        return
    
    # Rule 3: Get account info
    account = get_account_info()
    if not account:
        print("❌ Failed to get account info. Exiting.")
        return
    
    buying_power = float(account.get('buying_power', 0))
    print(f"💵 Available Cash: ${buying_power:,.2f}")
    
    # Rule 4: Get current positions
    positions = get_current_positions()
    print(f"📊 Current Positions: {len(positions)} stocks")
    for pos in positions:
        print(f"   - {pos['symbol']}: {pos['qty']} shares")
    
    # Rule 5: Check profit/loss on existing positions
    print("\n🔍 Checking profit/loss...")
    check_profit_loss(positions)
    
    # Rule 6: Get market signal
    print("\n📊 Analyzing market...")
    signal = get_market_signal()
    
    # Rule 7: Make trading decision
    if signal >= BUY_SIGNAL_THRESHOLD:
        print(f"\n✅ SIGNAL: {signal}/100 - GOOD CONDITIONS")
        
        reserve = buying_power * (CASH_RESERVE_PERCENT / 100)
        available_cash = buying_power - reserve
        
        if available_cash < 1000:
            print(f"⚠️ Not enough cash after reserve (${available_cash:.2f})")
            send_notification("⚠️ Low Cash", f"Only ${available_cash:.2f} available after reserve")
            return
        
        if len(positions) >= MAX_STOCKS:
            print(f"️ Already have {len(positions)} stocks (max: {MAX_STOCKS})")
            return
        
        print(f"\n💵 Buying with ${available_cash:,.2f} (keeping ${reserve:,.2f} reserve)")
        
        stocks_to_buy = 2
        for stock in STOCKS_TO_TRADE:
            owned = any(pos['symbol'] == stock for pos in positions)
            if owned:
                continue
            
            if buy_stock(stock, qty=1, buying_power=buying_power):
                stocks_to_buy -= 1
                if stocks_to_buy <= 0:
                    break
        
        send_notification(
            "✅ Bot Complete",
            f"Signal: {signal}/100\nAction: Bought stocks\nCash used: ${available_cash:,.2f}"
        )
        
    elif signal <= SELL_SIGNAL_THRESHOLD:
        print(f"\n⚠️ SIGNAL: {signal}/100 - DANGER ZONE")
        
        if positions:
            print(f"\n Selling all {len(positions)} positions...")
            for pos in positions:
                sell_stock(pos['symbol'], reason=f"Low signal {signal}/100")
            
            send_notification(
                "️ DANGER ZONE",
                f"Signal: {signal}/100\nAction: Sold all positions\nReason: Market too weak"
            )
        else:
            print("No positions to sell")
            send_notification("⚠️ Danger Zone", f"Signal {signal}/100 but no positions to sell")
            
    else:
        print(f"\n⏸️ SIGNAL: {signal}/100 - HOLDING")
        send_notification(
            "⏸️ Bot Complete",
            f"Signal: {signal}/100\nAction: Holding positions\nStatus: Neutral market"
        )
    
    print("\n" + "="*60)
    print("✅ TRADING BOT COMPLETE")
    print("="*60)

# ============================================
# 🚀 RUN THE BOT
# ============================================

if __name__ == "__main__":
    run_trading_bot()
