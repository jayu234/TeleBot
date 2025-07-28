import requests
import schedule
import time
import threading
import telegram
from fastapi import FastAPI
from telegram.constants import ParseMode

# --- Credentials ---
BOT_TOKEN = '8379459708:AAG4b1jBm6B9xQ1c2qIHlMvSEL3QiErpUPY'
CHAT_ID = '5872719081'
DEFAULT_SYMBOL = 'ONGC'

# Initialize bot and web app
bot = telegram.Bot(token=BOT_TOKEN)
app = FastAPI()

# NSE API settings
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
}

# API endpoints - separate for stocks and indices
NSE_STOCK_API = 'https://www.nseindia.com/api/option-chain-equities?symbol={}'
NSE_INDEX_API = 'https://www.nseindia.com/api/option-chain-indices?symbol={}'

def get_api_url(symbol: str) -> str:
    """Determine correct API endpoint based on symbol"""
    # List of major indices
    indices = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX']
    
    if symbol.upper() in indices:
        return NSE_INDEX_API.format(symbol.upper())
    else:
        return NSE_STOCK_API.format(symbol.upper())

def fetch_option_chain(symbol: str):
    """Fetch option chain data from NSE"""
    try:
        session = requests.Session()
        
        # First, visit the main page to get cookies
        session.get('https://www.nseindia.com', headers=HEADERS, timeout=10)
        
        # Get the appropriate API URL
        api_url = get_api_url(symbol)
        
        # Fetch option chain data
        response = session.get(api_url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        # Return the records and filtered data
        if 'records' in data:
            return data['records'], data['records'].get('data', [])
        else:
            raise ValueError("Invalid API response structure")
            
    except requests.exceptions.RequestException as e:
        raise Exception(f"Network error: {e}")
    except ValueError as e:
        raise Exception(f"Data parsing error: {e}")
    except Exception as e:
        raise Exception(f"Unexpected error: {e}")

def analyze(symbol: str) -> str:
    """Analyze option chain data and generate report"""
    try:
        records, strikes = fetch_option_chain(symbol)
        
        if not strikes:
            return f"❌ No option data available for {symbol.upper()}"
        
        # Get expiry date
        expiry_dates = records.get('expiryDates', [])
        expiry = expiry_dates[0] if expiry_dates else "N/A"
        
        # Initialize variables for analysis
        max_call_oi = {'strike': None, 'oi': 0}
        max_put_oi = {'strike': None, 'oi': 0}
        total_call_oi = 0
        total_put_oi = 0
        
        # Analyze each strike
        for strike_data in strikes:
            strike_price = strike_data.get('strikePrice')
            if not strike_price:
                continue
                
            # Call option data
            ce_data = strike_data.get('CE', {})
            ce_oi = ce_data.get('openInterest', 0)
            
            # Put option data  
            pe_data = strike_data.get('PE', {})
            pe_oi = pe_data.get('openInterest', 0)
            
            # Track maximum OI strikes
            if ce_oi > max_call_oi['oi']:
                max_call_oi = {'strike': strike_price, 'oi': ce_oi}
                
            if pe_oi > max_put_oi['oi']:
                max_put_oi = {'strike': strike_price, 'oi': pe_oi}
            
            # Sum total OI
            total_call_oi += ce_oi
            total_put_oi += pe_oi
        
        # Calculate Put-Call Ratio
        pcr = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else 0
        
        # Determine market bias
        if pcr < 0.7:
            bias = '📉 Bearish (High call activity)'
        elif pcr > 1.3:
            bias = '📈 Bullish (High put activity)'
        else:
            bias = '⚖️ Neutral (Balanced activity)'
        
        # Get current underlying price
        underlying_value = records.get('underlyingValue', 'N/A')
        
        # Construct the report message
        msg = f"""
📈 *{symbol.upper()}* Option Analysis
💰 Underlying: ₹{underlying_value}
🗓️ Expiry: `{expiry}`

🔴 Max Call OI: ₹{max_call_oi['strike']} ({max_call_oi['oi']:,})
🟢 Max Put OI: ₹{max_put_oi['strike']} ({max_put_oi['oi']:,})

📊 Put-Call Ratio: `{pcr}`
🧭 Market Bias: {bias}

⚠️ *Disclaimer: Not financial advice*
"""
        return msg.strip()
        
    except Exception as e:
        return f"❌ Error analyzing {symbol.upper()}: {str(e)}"

def send_report():
    """Send option chain report via Telegram"""
    try:
        text = analyze(DEFAULT_SYMBOL)
        bot.send_message(
            chat_id=CHAT_ID, 
            text=text, 
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
    except Exception as e:
        print(f"Error sending report: {e}")

def schedule_reports():
    """Schedule daily reports"""
    # Market opening and closing reports
    schedule.every().day.at("09:20").do(send_report)  # After market opens
    schedule.every().day.at("15:25").do(send_report)  # Before market closes
    
    while True:
        schedule.run_pending()
        time.sleep(60)

# Start scheduler in background thread
threading.Thread(target=schedule_reports, daemon=True).start()

# FastAPI endpoints
@app.get("/")
def read_root():
    return {"status": "NSE Option Chain Bot is running", "symbol": DEFAULT_SYMBOL}

@app.get("/report")
def get_report():
    """Manual trigger for getting report"""
    try:
        report = analyze(DEFAULT_SYMBOL)
        return {"report": report}
    except Exception as e:
        return {"error": str(e)}

@app.get("/report/{symbol}")
def get_symbol_report(symbol: str):
    """Get report for specific symbol"""
    try:
        report = analyze(symbol)
        return {"symbol": symbol.upper(), "report": report}
    except Exception as e:
        return {"error": str(e)}

# Send initial report on startup
if __name__ == "__main__":
    try:
        send_report()
    except Exception as e:
        print(f"Error sending initial report: {e}")