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
                  'Chrome/120.0.0.0 Safari/537.36'
}
NSE_API = 'https://www.nseindia.com/api/option-chain-equities?symbol={}'


def fetch_option_chain(symbol: str):
    session = requests.Session()
    session.get('https://www.nseindia.com', headers=HEADERS)
    response = session.get(NSE_API.format(symbol.upper()), headers=HEADERS)
    response.raise_for_status()
    data = response.json()
    return data['records'], data['filtered']['data']


def analyze(symbol: str) -> str:
    try:
        records, strikes = fetch_option_chain(symbol)
        expiry = records['expiryDates'][0]

        # Find highest Open Interest
        resistance = {'strike': None, 'OI': 0}
        support = {'strike': None, 'OI': 0}
        total_call_oi = 0
        total_put_oi = 0

        for item in strikes:
            strike = item['strikePrice']
            ce_oi = item.get('CE', {}).get('openInterest', 0)
            pe_oi = item.get('PE', {}).get('openInterest', 0)

            if ce_oi > resistance['OI']:
                resistance = {'strike': strike, 'OI': ce_oi}
            if pe_oi > support['OI']:
                support = {'strike': strike, 'OI': pe_oi}

            total_call_oi += ce_oi
            total_put_oi += pe_oi

        pcr = round(total_put_oi / total_call_oi, 2) if total_call_oi else 0
        bias = '📉 Bearish or range-bound' if pcr < 0.5 else \
               '📈 Bullish or potential reversal' if pcr > 1.2 else \
               '⚖️ Neutral or balanced'

        # Construct message with triple-quoted f-string
        msg = f"""
📈 *{symbol.upper()}* Option Chain
🗓️ Expiry: `{expiry}`
🔹 Resistance: ₹{resistance['strike']} ({resistance['OI']:,})
🔸 Support: ₹{support['strike']} ({support['OI']:,})
📊 PCR: `{pcr}`

🧭 Bias: {bias}
⚠️ Not financial advice.
"""
        return msg.strip()

    except Exception as e:
        return f"❌ Error fetching data for {symbol.upper()}: {e}"


def send_report():
    text = analyze(DEFAULT_SYMBOL)
    bot.send_message(chat_id=CHAT_ID, text=text, parse_mode=ParseMode.MARKDOWN)


def schedule_reports():
    schedule.every().day.at("09:15").do(send_report)
    schedule.every().day.at("15:40").do(send_report)
    while True:
        schedule.run_pending()
        time.sleep(60)

# Start scheduler in a background thread
threading.Thread(target=schedule_reports, daemon=True).start()

# Root endpoint to keep Render web service alive
@app.get("/")
def read_root():
    return {"status": "Bot is running"}
    
send_report()
