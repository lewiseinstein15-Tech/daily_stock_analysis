#!/usr/bin/env python3
"""
Production AI Trading Bot
- Runs 24/7 on schedule
- Manages account balance
- Tracks profit/loss
- Sends detailed reports
"""

import os
import requests
import time
from datetime import datetime, timedelta
import pytz

# ============================================
# 🔑 CONFIGURATION
# ============================================
API_KEY = os.environ.get('ALPACA_API_KEY')
SECRET_KEY = os.environ.get('ALPACA_SECRET_KEY')
BASE_URL = 'https://paper-api.alpaca.markets/v2'
NTFY_TOPIC = "my-stock-report-kenya"

# Trading Rules
BUY_SIGNAL_THRESHOLD = 60        # Buy when >= 60
SELL_SIGNAL_THRESHOLD = 30       # Sell when <= 30
TAKE_PROFIT_PERCENT = 10         # Take profit at +10%
STOP_LOSS_PERCENT = 5            # Stop loss at -5%
MAX_POSITION_PERCENT = 40        # Max 40% of account per stock
CASH_RESERVE_PERCENT = 20        # Keep 20% cash reserve
MAX_STOCKS = 3                   # Max 3 stocks at once
STOCKS_TO_TRADE = ['AAPL', 'MSFT', 'NVDA']

# ============================================
# 📡 NOTIFICATION FUNCTION
# ============================================

def send_notification(title, message, priority=3):
    """Send clean notification to ntfy"""
    try:
        # Clean emojis and special chars
        title_clean = ''.join(c for c in title if ord(c) < 128)
        message_clean = ''.join(c for c in message if ord(c) < 128)
        
        response = requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message_clean,
            headers={
                "Title": title_clean,
                "Priority": str(priority)
            }
        )
        print(f"Sent: {title_clean}")
        return True
    except Exception as e:
        print(f"Notification failed: {e}")
        return False

# ============================================
# 📊 ACCOUNT FUNCTIONS
# ============================================

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
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None

def get_positions():
    """Get current positions with details"""
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

def get_stock_price(symbol):
    """Get current stock price"""
    try:
        headers = {
            'APCA-API-KEY-ID': API_KEY,
            'APCA-API-SECRET-KEY': SECRET_KEY
        }
        response = requests.get(f"{BASE_URL}/stocks/{symbol}/quotes", headers=headers)
        if response.status_code == 200:
            data = response.json()
            return float(data.get('askPrice', 0))
    except:
        pass
    return 0

# ============================================
# 📈 MARKET ANALYSIS
# ============================================

def get_market_signal():
    """Calculate market signal (0-100)"""
    print("Analyzing market...")
    
    try:
        headers = {
            'APCA-API-KEY-ID': API_KEY,
            'APCA-API-SECRET-KEY': SECRET_KEY
        }
        
        # Get SPY 5-day performance
        response = requests.get(f"{BASE_URL}/stocks/SPY/bars",
                               headers=headers,
                               params={'timeframe': '1Day', 'limit': 5})
        
        if response.status_code == 200:
            data = response.json()
            bars = data.get('bars', [])
            
            if len(bars) >= 2:
                oldest = bars[0].get('c', 0)
                latest = bars[-1].get('c', 0)
                change = ((latest - oldest) / oldest) * 100
                
                # Convert to signal score
                if change > 3:
                    return 85
                elif change > 1:
                    return 70
                elif change > -1:
                    return 50
                elif change > -3:
                    return 35
                else:
                    return 15
    except Exception as e:
        print(f"Signal error: {e}")
    
    return 50  # Default neutral

def is_market_open():
    """Check if US market is open"""
    try:
        et_tz = pytz.timezone('America/New_York')
        now = datetime.now(et_tz)
        
        # Weekend check
        if now.weekday() >= 5:
            return False
        
        # Market hours: 9:30 AM - 4:00 PM ET
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
        
        return market_open <= now <= market_close
    except:
        return False

# ============================================
# 💼 TRADING FUNCTIONS
# ============================================

def buy_stock(symbol, qty, buy_price):
    """Buy stock and track details"""
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
            result = response.json()
            actual_price = buy_price  # Market order price
            
            total_cost = actual_price * qty
            
            message = f"""BOUGHT {qty} {symbol}
Price: ${actual_price:.2f}
Total: ${total_cost:.2f}
Time: {datetime.now().strftime('%H:%M')}"""
            
            send_notification("BUY ORDER", message)
            print(f"BOUGHT {qty} {symbol} @ ${actual_price:.2f}")
            return True
        else:
            print(f"Buy failed: {response.json()}")
            return False
    except Exception as e:
        print(f"Buy error: {e}")
        return False

def sell_stock(symbol, qty, reason=""):
    """Sell stock and calculate profit/loss"""
    try:
        # Get current positions to find avg entry price
        positions = get_positions()
        entry_price = 0
        
        for pos in positions:
            if pos['symbol'] == symbol:
                entry_price = float(pos.get('avg_entry_price', 0))
                break
        
        # Get current price
        current_price = get_stock_price(symbol)
        
        headers = {
            'APCA-API-KEY-ID': API_KEY,
            'APCA-API-SECRET-KEY': SECRET_KEY
        }
        
        order_data = {
            "symbol": symbol,
            "qty": qty,
            "side": "sell",
            "type": "market",
            "time_in_force": "day"
        }
        
        response = requests.post(f"{BASE_URL}/orders", headers=headers, json=order_data)
        
        if response.status_code == 200:
            # Calculate profit/loss
            if entry_price > 0 and current_price > 0:
                pnl_per_share = current_price - entry_price
                total_pnl = pnl_per_share * qty
                pnl_percent = (pnl_per_share / entry_price) * 100
                
                profit_type = "PROFIT" if total_pnl > 0 else "LOSS"
                
                message = f"""SOLD {qty} {symbol}
Sell Price: ${current_price:.2f}
Buy Price: ${entry_price:.2f}
{profit_type}: ${total_pnl:.2f} ({pnl_percent:+.2f}%)
Reason: {reason}"""
            else:
                message = f"""SOLD {qty} {symbol}
Price: ${current_price:.2f}
Reason: {reason}"""
            
            send_notification("SELL ORDER", message)
            print(f"SOLD {qty} {symbol} @ ${current_price:.2f}")
            return True
        else:
            print(f"Sell failed: {response.json()}")
            return False
    except Exception as e:
        print(f"Sell error: {e}")
        return False

# ============================================
# 🤖 MAIN TRADING LOGIC
# ============================================

def run_trading_bot():
    """Main trading bot - runs every cycle"""
    
    print("="*60)
    print("TRADING BOT CYCLE")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    # Check if market is open
    if not is_market_open():
        print("Market closed. Skipping.")
        return
    
    # Get account info
    account = get_account_info()
    if not account:
        print("Failed to get account")
        return
    
    buying_power = float(account.get('buying_power', 0))
    equity = float(account.get('equity', 0))
    
    print(f"Account Equity: ${equity:,.2f}")
    print(f"Buying Power: ${buying_power:,.2f}")
    
    # Get current positions
    positions = get_positions()
    print(f"Current Positions: {len(positions)}")
    
    # Check each position for profit/loss
    print("\nChecking positions...")
    for pos in positions:
        symbol = pos['symbol']
        qty = float(pos['qty'])
        entry_price = float(pos.get('avg_entry_price', 0))
        current_price = float(pos.get('current_price', 0))
        market_value = float(pos.get('market_value', 0))
        
        pnl_percent = ((current_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
        
        print(f"  {symbol}: {qty} shares @ ${entry_price:.2f} -> ${current_price:.2f} ({pnl_percent:+.2f}%)")
        
        # Check take-profit
        if pnl_percent >= TAKE_PROFIT_PERCENT:
            print(f"  Take-profit hit! Selling {symbol}")
            sell_stock(symbol, qty, f"Take-profit +{pnl_percent:.1f}%")
        
        # Check stop-loss
        elif pnl_percent <= -STOP_LOSS_PERCENT:
            print(f"  Stop-loss hit! Selling {symbol}")
            sell_stock(symbol, qty, f"Stop-loss {pnl_percent:.1f}%")
    
    # Get fresh positions after sales
    positions = get_positions()
    
    # Get market signal
    signal = get_market_signal()
    print(f"\nMarket Signal: {signal}/100")
    
    # Make decision
    if signal >= BUY_SIGNAL_THRESHOLD:
        print(f"Signal {signal} >= {BUY_SIGNAL_THRESHOLD} -> BUY MODE")
        
        # Calculate how much to invest
        reserve = buying_power * (CASH_RESERVE_PERCENT / 100)
        investable = buying_power - reserve
        
        if investable < 500:
            print(f"Not enough cash to invest: ${investable:.2f}")
            send_notification("Low Cash", f"Only ${investable:.2f} available after reserve")
            return
        
        # Check if we can buy more stocks
        if len(positions) >= MAX_STOCKS:
            print(f"Already have {len(positions)} stocks (max: {MAX_STOCKS})")
            send_notification("Portfolio Full", f"Holding {len(positions)} stocks. No new buys.")
            return
        
        # Buy 1-2 stocks
        print(f"\nInvesting ${investable:.2f} (keeping ${reserve:.2f} reserve)")
        
        stocks_bought = 0
        for stock in STOCKS_TO_TRADE:
            # Check if already owned
            owned = any(pos['symbol'] == stock for pos in positions)
            if owned:
                continue
            
            # Get current price
            price = get_stock_price(stock)
            if price <= 0:
                continue
            
            # Calculate quantity (max 40% of account per stock)
            max_investment = buying_power * (MAX_POSITION_PERCENT / 100)
            qty = min(int(max_investment / price), int(investable / price))
            
            if qty >= 1:
                if buy_stock(stock, qty, price):
                    stocks_bought += 1
                    investable -= (price * qty)
                    
                    if stocks_bought >= 2:  # Buy max 2 stocks per cycle
                        break
        
        # Send summary
        if stocks_bought > 0:
            send_notification("BUY COMPLETE", f"Bought {stocks_bought} stocks\nSignal: {signal}/100\nRemaining Cash: ${investable:.2f}")
        else:
            send_notification("No Buys", f"Signal {signal}/100 but no suitable stocks found")
    
    elif signal <= SELL_SIGNAL_THRESHOLD:
        print(f"Signal {signal} <= {SELL_SIGNAL_THRESHOLD} -> SELL MODE")
        
        if positions:
            print(f"Selling all {len(positions)} positions...")
            for pos in positions:
                sell_stock(pos['symbol'], float(pos['qty']), f"Low signal {signal}/100")
            
            send_notification("DANGER ZONE", f"Signal {signal}/100\nSold all {len(positions)} positions")
        else:
            send_notification("Danger Zone", f"Signal {signal}/100 - No positions to sell")
    
    else:
        print(f"Signal {signal} -> HOLD MODE")
        
        # Send daily summary if we have positions
        if positions:
            total_value = sum(float(pos.get('market_value', 0)) for pos in positions)
            total_pnl = sum(float(pos.get('unrealized_pl', 0)) for pos in positions)
            
            summary = f"""Signal: {signal}/100
Positions: {len(positions)}
Total Value: ${total_value:.2f}
Unrealized P/L: ${total_pnl:.2f}
Cash: ${buying_power:.2f}
Equity: ${equity:.2f}"""
            
            send_notification("HOLDING", summary)

# ============================================
# 🚀 RUN THE BOT
# ============================================

if __name__ == "__main__":
    run_trading_bot()
