# ONGC Option Chain Telegram Bot (Python 3.11+)
# Dependencies: requests, beautifulsoup4, python-telegram-bot (v20+), schedule

import requests
import datetime
import telegram
import schedule
import time
from bs4 import BeautifulSoup
from telegram.constants import ParseMode

# --- FILLED CREDENTIALS ---
BOT_TOKEN = '8379459708:AAG4b1jBm6B9xQ1c2qIHlMvSEL3QiErpUPY'
CHAT_ID = '5872719081'
DEFAULT_SYMBOL = 'ONGC'
EXPIRY_DATE = ''  # auto-detected

bot = telegram.Bot(token=BOT_TOKEN)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

NSE_BASE = 'https://www.nseindia.com'
OC_API = 'https://www.nseindia.com/api/option-chain-equities?symbol={}'


def fetch_option_chain(symbol):
    session = requests.Session()
    session.get(NSE_BASE, headers=HEADERS)
    url = OC_API.format(symbol.upper())
    res = session.get(url, headers=HEADERS)
    res.raise_for_status()
    data = res.json()
    return data['records'], data['filtered']['data']


def analyze(symbol):
    try:
        records, filtered = fetch_option_chain(symbol)
        expiry = records['expiryDates'][0]
        strikes = filtered

        resistance = {'strike': None, 'OI': 0}
        support = {'strike': None, 'OI': 0}
        total_call_oi = 0
        total_put_oi = 0

        for item in strikes:
            strike_price = item['strikePrice']
            ce = item.get('CE', {})
            pe = item.get('PE', {})

            ce_oi = ce.get('openInterest', 0)
            pe_oi = pe.get('openInterest', 0)

            if ce_oi > resistance['OI']:
                resistance = {'strike': strike_price, 'OI': ce_oi}

            if pe_oi > support['OI']:
                support = {'strike': strike_price, 'OI': pe_oi}

            total_call_oi += ce_oi
            total_put_oi += pe_oi

        pcr = round(total_put_oi / total_call_oi, 2) if total_call_oi else 0

        msg = f"\n📈 Option Chain Summary for *{symbol.upper()}*\n"
        msg += f"🗓️ Expiry: `{expiry}`\n"
        msg += f"\n🔹 *Resistance* (Highest Call OI): ₹{resistance['strike']} ({resistance['OI']:,})"
        msg += f"\n🔸 *Support* (Highest Put OI): ₹{support['strike']} ({support['OI']:,})"
        msg += f"\n📊 *PCR (Put/Call Ratio)*: `{pcr}`"

        if pcr < 0.5:
            bias = '📉 Bearish or range-bound'
        elif pcr > 1.2:
            bias = '📈 Bullish or potential reversal'
        else:
            bias = '⚖️ Neutral or balanced'

        msg += f"\n\n🧭 *Market Bias:* {bias}"
        msg += "\n\n⚠️ Data is near real-time. Not for trading advice."

        return msg
    except Exception as e:
        return f"❌ Error fetching data for {symbol.upper()}: {str(e)}"


def send_morning_report():
    text = analyze(DEFAULT_SYMBOL)
    bot.send_message(chat_id=CHAT_ID, text=text, parse_mode=ParseMode.MARKDOWN)


def send_evening_report():
    text = analyze(DEFAULT_SYMBOL)
    bot.send_message(chat_id=CHAT_ID, text="📉 Market Close Update:\n" + text, parse_mode=ParseMode.MARKDOWN)


# --- Scheduler (for local testing) ---
# schedule.every().day.at("09:15").do(send_morning_report)
# schedule.every().day.at("15:40").do(send_evening_report)

# while True:
#     schedule.run_pending()
#     time.sleep(60)

# --- Manual Run Example ---
if __name__ == '__main__':
    print(analyze("ONGC"))
    # print(analyze("RELIANCE"))
