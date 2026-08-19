#!/usr/bin/env python3
"""
AI Trading Bot - Fixed notification encoding
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
# 📊 TRADING RULES
# ============================================
BUY_SIGNAL_THRESHOLD = 60
SELL_SIGNAL_THRESHOLD = 30
TAKE_PROFIT_PERCENT = 15
STOP_LOSS_PERCENT = 8
MAX_POSITION_PERCENT = 20
CASH_RESERVE_PERCENT = 20
MAX_STOCKS = 5
STOCKS_TO_TRADE = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA']

# ============================================
# ️ FUNCTIONS
# ============================================

def send_notification(title, message, priority=3):
    """Send notification to ntfy - ASCII only"""
    try:
        topic = NTFY_URL.split('/')[-1]
        
        # Remove emojis and use ASCII only
        title_clean = title.encode('ascii', 'ignore').decode('ascii')
        message_clean = message.encode('ascii', 'ignore').decode('ascii')
        
        response = requests.post(
            f"https://ntfy.sh/{topic}",
            data=message_clean,
            headers={
                "Title": title_clean,
                "Priority": str(priority)
            }
        )
        print(f"Notification sent: {title_clean}")
        return response.status_code == 200
    except Exception as e:
        print(f"Notification failed: {e}")
        return False

def get_account_info():
    """Get account balance"""
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
        print(f"Error getting account: {e}")
        return None

def get_current_positions():
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
        print(f"Error getting positions: {e}")
        return []

def is_market_open():
    """Check if market is open"""
    try:
        et_timezone = pytz.timezone('America/New_York')
        now_et = datetime.now(et_timezone)
        
        if now_et.weekday() >= 5:
            print("Market is CLOSED (Weekend)")
            return False
        
        market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        
        if market_open <= now_et <= market_close:
            print(f"Market is OPEN (ET: {now_et.strftime('%H:%M')})")
            return True
        else:
            print(f"Market is CLOSED (ET: {now_et.strftime('%H:%M')})")
            return False
    except Exception as e:
        print(f"Error checking market: {e}")
        return False

def get_market_signal():
    """Get market signal from SPY"""
    print("Calculating market signal...")
    
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
                
                print(f"SPY 5-day change: {change_percent:.2f}%")
                
                if change_percent > 2:
                    signal = 80
                elif change_percent > 0:
                    signal = 65
                elif change_percent > -2:
                    signal = 45
                else:
                    signal = 25
                
                print(f"Market Signal: {signal}/100")
                return signal
    except Exception as e:
        print(f"Could not calculate signal: {e}")
    
    return 50

def buy_stock(symbol, qty, buying_power):
    """Buy stock"""
    try:
        headers = {
            'APCA-API-KEY-ID': API_KEY,
            'APCA-API-SECRET-KEY': SECRET_KEY
        }
        
        order_data = {
            "symbol": symbol,
            "qty": qty,
            "side": "buy",
            "type": "market",
            "time_in_force": "day"
        }
        
        response = requests.post(f"{BASE_URL}/orders", headers=headers, json=order_data)
        
        if response.status_code == 200:
            print(f"BOUGHT {qty} {symbol}")
            send_notification(
                "BUY ORDER",
                f"Bought {qty} {symbol}\nSignal: Good market conditions\nTime: {datetime.now().strftime('%H:%M')}"
            )
            return True
        else:
            print(f"Buy failed: {response.json()}")
            return False
    except Exception as e:
        print(f"Error buying {symbol}: {e}")
        return False

def sell_stock(symbol, qty=None, reason=""):
    """Sell stock"""
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
            print(f"SOLD {symbol} - Reason: {reason}")
            send_notification(
                "SELL ORDER",
                f"Sold {symbol}\nReason: {reason}\nTime: {datetime.now().strftime('%H:%M')}"
            )
            return True
        else:
            print(f"Sell failed: {response.json()}")
            return False
    except Exception as e:
        print(f"Error selling {symbol}: {e}")
        return False

def check_profit_loss(positions):
    """Check P&L"""
    for pos in positions:
        try:
            symbol = pos['symbol']
            avg_price = float(pos['avg_entry_price'])
            current_price = float(pos['current_price'])
            
            pnl_percent = ((current_price - avg_price) / avg_price) * 100
            
            print(f"{symbol}: {pnl_percent:+.2f}%")
            
            if pnl_percent >= TAKE_PROFIT_PERCENT:
                print(f"Take-profit hit for {symbol}")
                sell_stock(symbol, reason=f"Take-profit +{pnl_percent:.1f}%")
            elif pnl_percent <= -STOP_LOSS_PERCENT:
                print(f"Stop-loss hit for {symbol}")
                sell_stock(symbol, reason=f"Stop-loss {pnl_percent:.1f}%")
        except Exception as e:
            print(f"Error checking P&L: {e}")

# ============================================
# 🤖 MAIN FUNCTION
# ============================================

def run_trading_bot():
    """Main bot logic"""
    print("="*60)
    print("AI TRADING BOT STARTING")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    # Check market
    if not is_market_open():
        print("Market closed. Exiting.")
        send_notification("Bot Skipped", "Market is closed. Next run: Next trading day")
        return
    
    # Get account
    account = get_account_info()
    if not account:
        print("Failed to get account info.")
        return
    
    buying_power = float(account.get('buying_power', 0))
    print(f"Available Cash: ${buying_power:,.2f}")
    
    # Get positions
    positions = get_current_positions()
    print(f"Current Positions: {len(positions)} stocks")
    
    # Check P&L
    print("Checking profit/loss...")
    check_profit_loss(positions)
    
    # Get signal
    print("Analyzing market...")
    signal = get_market_signal()
    
    # Make decision
    if signal >= BUY_SIGNAL_THRESHOLD:
        print(f"SIGNAL: {signal}/100 - GOOD CONDITIONS")
        
        reserve = buying_power * (CASH_RESERVE_PERCENT / 100)
        available_cash = buying_power - reserve
        
        if available_cash < 1000:
            print(f"Not enough cash: ${available_cash:.2f}")
            send_notification("Low Cash", f"Only ${available_cash:.2f} available")
            return
        
        if len(positions) >= MAX_STOCKS:
            print(f"Already have {len(positions)} stocks")
            return
        
        print(f"Buying with ${available_cash:,.2f}")
        
        stocks_to_buy = 2
        for stock in STOCKS_TO_TRADE:
            owned = any(pos['symbol'] == stock for pos in positions)
            if owned:
                continue
            
            if buy_stock(stock, qty=1, buying_power=buying_power):
                stocks_to_buy -= 1
                if stocks_to_buy <= 0:
                    break
        
        send_notification("Bot Complete", f"Signal: {signal}/100\nAction: Bought stocks")
        
    elif signal <= SELL_SIGNAL_THRESHOLD:
        print(f"SIGNAL: {signal}/100 - DANGER ZONE")
        
        if positions:
            print(f"Selling all {len(positions)} positions...")
            for pos in positions:
                sell_stock(pos['symbol'], reason=f"Low signal {signal}/100")
            
            send_notification("DANGER ZONE", f"Signal: {signal}/100\nSold all positions")
        else:
            send_notification("Danger Zone", f"Signal {signal}/100 - No positions")
            
    else:
        print(f"SIGNAL: {signal}/100 - HOLDING")
        send_notification("Bot Complete", f"Signal: {signal}/100\nAction: Holding")
    
    print("="*60)
    print("TRADING BOT COMPLETE")
    print("="*60)

# ============================================
# 🚀 RUN
# ============================================

if __name__ == "__main__":
    run_trading_bot()
