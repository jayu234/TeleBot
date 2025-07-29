import requests
import schedule
import time
import threading
import telegram
import json
import asyncio
from fastapi import FastAPI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode

# --- Credentials ---
BOT_TOKEN = '8379459708:AAG4b1jBm6B9xQ1c2qIHlMvSEL3QiErpUPY'

# Initialize FastAPI
app = FastAPI()

# Global session for NSE requests
nse_session = None

# Bot application instance
telegram_app = None

# User preferences storage
user_preferences = {}

def create_nse_session():
    """Create a session optimized for NSE API calls"""
    global nse_session
    
    nse_session = requests.Session()
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache'
    }
    
    nse_session.headers.update(headers)
    return nse_session

def initialize_nse_session():
    """Initialize session by visiting NSE pages with better error handling"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"🔄 NSE session attempt {attempt + 1}/{max_retries}")
            
            # Try with longer timeout for production
            response = nse_session.get('https://www.nseindia.com', timeout=30)
            if response.status_code != 200:
                print(f"⚠️  Homepage returned {response.status_code}")
                if attempt < max_retries - 1:
                    time.sleep(5)
                    continue
                return False
            
            # Visit market pages with shorter timeouts
            try:
                nse_session.get('https://www.nseindia.com/market-data', timeout=20)
                nse_session.get('https://www.nseindia.com/option-chain', timeout=20)
            except Exception as e:
                print(f"⚠️  Secondary pages failed: {e}")
                # Continue anyway, main page worked
            
            time.sleep(2)
            
            # Update headers for API calls
            api_headers = {
                'Accept': 'application/json, text/plain, */*',
                'Referer': 'https://www.nseindia.com/option-chain',
                'X-Requested-With': 'XMLHttpRequest',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-origin'
            }
            nse_session.headers.update(api_headers)
            
            print(f"✅ NSE session initialized on attempt {attempt + 1}")
            return True
            
        except Exception as e:
            print(f"❌ NSE session attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                print(f"⏳ Retrying in 10 seconds...")
                time.sleep(10)
            else:
                print("❌ All NSE session attempts failed")
                return False
    
    return False

def get_nse_option_chain(symbol: str):
    """Fetch option chain data from NSE API"""
    try:
        indices = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX']
        
        if symbol.upper() in indices:
            api_url = f'https://www.nseindia.com/api/option-chain-indices?symbol={symbol.upper()}'
        else:
            api_url = f'https://www.nseindia.com/api/option-chain-equities?symbol={symbol.upper()}'
        
        response = nse_session.get(api_url, timeout=20)
        
        if response.status_code == 200:
            try:
                data = response.json()
                if 'records' in data and 'data' in data['records']:
                    return data['records'], data['records']['data']
                else:
                    return None, None
            except json.JSONDecodeError:
                return None, None
        else:
            return None, None
            
    except Exception:
        return None, None

def analyze_option_data(symbol: str) -> str:
    """Generate option chain analysis"""
    try:
        # Ensure NSE session is working
        if not nse_session or len(nse_session.cookies) == 0:
            print(f"🔄 Reinitializing NSE session for {symbol}")
            create_nse_session()
            if not initialize_nse_session():
                return f"""❌ NSE service temporarily unavailable for *{symbol.upper()}*

🔧 **Possible reasons:**
• NSE servers are blocking this IP
• Network connectivity issues
• NSE API temporarily down

💡 **Try again in a few minutes**

⚠️ *This commonly happens with cloud servers*"""
        
        records, option_data = get_nse_option_chain(symbol)
        
        if not records or not option_data:
            # Try reinitializing session once more
            print(f"🔄 Retrying NSE session for {symbol}")
            create_nse_session()
            if initialize_nse_session():
                records, option_data = get_nse_option_chain(symbol)
            
            if not records or not option_data:
                return f"""❌ No option data available for *{symbol.upper()}*

🔧 **Possible reasons:**
• Symbol may not have active F&O trading
• NSE API blocking requests
• Data temporarily unavailable

💡 **Try these symbols instead:**
NIFTY, BANKNIFTY, RELIANCE, TCS, HDFCBANK"""
        
        underlying_value = records.get('underlyingValue', 'N/A')
        expiry_dates = records.get('expiryDates', [])
        expiry = expiry_dates[0] if expiry_dates else 'N/A'
        
        max_call_oi = {'strike': 0, 'oi': 0}
        max_put_oi = {'strike': 0, 'oi': 0}
        total_call_oi = 0
        total_put_oi = 0
        valid_strikes = 0
        
        for strike_data in option_data:
            strike_price = strike_data.get('strikePrice', 0)
            if not strike_price:
                continue
                
            valid_strikes += 1
            
            ce_data = strike_data.get('CE', {})
            ce_oi = ce_data.get('openInterest', 0) or 0
            
            pe_data = strike_data.get('PE', {})
            pe_oi = pe_data.get('openInterest', 0) or 0
            
            if ce_oi > max_call_oi['oi']:
                max_call_oi = {'strike': strike_price, 'oi': ce_oi}
                
            if pe_oi > max_put_oi['oi']:
                max_put_oi = {'strike': strike_price, 'oi': pe_oi}
            
            total_call_oi += ce_oi
            total_put_oi += pe_oi
        
        if valid_strikes == 0:
            return f"❌ No valid option strikes found for *{symbol.upper()}*"
        
        pcr = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else 0
        
        if pcr < 0.7:
            sentiment = "📉 **Bearish** (Heavy Call Writing)"
            emoji = "🐻"
        elif pcr > 1.3:
            sentiment = "📈 **Bullish** (Heavy Put Writing)"
            emoji = "🐂"
        else:
            sentiment = "⚖️ **Neutral** (Balanced Activity)"
            emoji = "⚖️"
        
        return f"""{emoji} **{symbol.upper()}** Option Analysis

💰 **Price:** ₹{underlying_value}
🗓️ **Expiry:** {expiry}

**🔴 MAX CALL OI:** ₹{max_call_oi['strike']} → {max_call_oi['oi']:,}
**🟢 MAX PUT OI:** ₹{max_put_oi['strike']} → {max_put_oi['oi']:,}

**📊 PCR:** `{pcr}` | **🎯 Bias:** {sentiment}"""
        
    except Exception as e:
        return f"""❌ Analysis error for *{symbol.upper()}*

**Error:** {str(e)}

🔄 **Please try again in a few minutes**"""

# Telegram Bot Handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    welcome_message = """🎯 **Welcome to NSE Option Chain Bot!**

This bot provides option chain analysis for NSE stocks and indices.

📊 **How it works:**
• Get real-time option chain data
• View Put-Call Ratio (PCR) analysis  
• Track maximum Call/Put OI levels
• Schedule daily reports

🔸 **Please send me a list of symbols (comma-separated)**

**Examples:**
`NIFTY, BANKNIFTY, RELIANCE`
`TCS, HDFCBANK, ICICIBANK`
`FINNIFTY, INFY, LT`

💡 **Supported:** All NSE stocks/indices with F&O trading"""

    await update.message.reply_text(welcome_message, parse_mode=ParseMode.MARKDOWN)

async def handle_symbols(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle symbol input from user"""
    user_id = update.effective_user.id
    symbols_text = update.message.text.strip()
    
    # Parse comma-separated symbols
    symbols = [symbol.strip().upper() for symbol in symbols_text.split(',') if symbol.strip()]
    
    if not symbols:
        await update.message.reply_text("❌ Please provide valid symbols separated by commas.\n\nExample: `NIFTY, RELIANCE, TCS`", parse_mode=ParseMode.MARKDOWN)
        return
    
    # Store user preferences
    user_preferences[user_id] = {
        'symbols': symbols,
        'daily_reports': False
    }
    
    symbols_list = '\n'.join([f"• {symbol}" for symbol in symbols])
    
    # Create inline keyboard for options
    keyboard = [
        [InlineKeyboardButton("📊 See Report Now", callback_data="report_now")],
        [InlineKeyboardButton("⏰ Schedule Daily Reports", callback_data="schedule_daily")],
        [InlineKeyboardButton("🔄 Change Symbols", callback_data="change_symbols")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = f"""✅ **Symbols Configured Successfully!**

**Your Symbols:**
{symbols_list}

**What would you like to do?**"""
    
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    user_id = query.from_user.id
    
    await query.answer()
    
    if user_id not in user_preferences:
        await query.edit_message_text("❌ Please start over with /start command.")
        return
    
    user_symbols = user_preferences[user_id]['symbols']
    
    if query.data == "report_now":
        await query.edit_message_text("🔄 **Generating reports...**\n\nPlease wait while I fetch the latest data.", parse_mode=ParseMode.MARKDOWN)
        
        # Generate reports for all user symbols
        for symbol in user_symbols:
            try:
                analysis = analyze_option_data(symbol)
                await context.bot.send_message(chat_id=user_id, text=analysis, parse_mode=ParseMode.MARKDOWN)
                time.sleep(1)  # Small delay between reports
            except Exception as e:
                await context.bot.send_message(chat_id=user_id, text=f"❌ Failed to generate report for {symbol}: {str(e)}")
        
        await context.bot.send_message(chat_id=user_id, text="✅ **All reports generated!**\n\nUse /start to reconfigure or get new reports.", parse_mode=ParseMode.MARKDOWN)
    
    elif query.data == "schedule_daily":
        user_preferences[user_id]['daily_reports'] = True
        
        symbols_list = ', '.join(user_symbols)
        message = f"""⏰ **Daily Reports Scheduled!**

**Your Symbols:** {symbols_list}
**Schedule:** 09:20 AM & 03:25 PM (Market Hours)

You'll receive automatic reports for these symbols every trading day.

💡 Use /stop to disable daily reports
💡 Use /start to change symbols"""
        
        await query.edit_message_text(message, parse_mode=ParseMode.MARKDOWN)
    
    elif query.data == "change_symbols":
        await query.edit_message_text("🔄 **Please send me new symbols (comma-separated):**\n\nExample: `NIFTY, BANKNIFTY, RELIANCE`", parse_mode=ParseMode.MARKDOWN)

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stop command"""
    user_id = update.effective_user.id
    
    if user_id in user_preferences:
        user_preferences[user_id]['daily_reports'] = False
        await update.message.reply_text("⏹️ **Daily reports stopped.**\n\nUse /start to reconfigure the bot.", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("❌ No active configuration found.\n\nUse /start to configure the bot.", parse_mode=ParseMode.MARKDOWN)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command"""
    user_id = update.effective_user.id
    
    if user_id not in user_preferences:
        await update.message.reply_text("❌ No configuration found.\n\nUse /start to configure the bot.", parse_mode=ParseMode.MARKDOWN)
        return
    
    user_config = user_preferences[user_id]
    symbols_list = ', '.join(user_config['symbols'])
    daily_status = "✅ Enabled" if user_config['daily_reports'] else "❌ Disabled"
    
    message = f"""📊 **Your Bot Status**

**Symbols:** {symbols_list}
**Daily Reports:** {daily_status}
**Schedule:** 09:20 AM & 03:25 PM

💡 Use /start to reconfigure
💡 Use /stop to disable daily reports"""
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

def send_daily_reports():
    """Wrapper function for scheduler"""
    if not telegram_app or not user_preferences:
        return
        
    # Simple approach: use the bot's send_message directly
    for user_id, config in user_preferences.items():
        if not config.get('daily_reports', False):
            continue
            
        try:
            # Send header message synchronously
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Send header
            loop.run_until_complete(telegram_app.bot.send_message(
                chat_id=user_id,
                text=f"📊 **Daily Market Report** | {time.strftime('%d %b %Y, %H:%M')} IST",
                parse_mode=ParseMode.MARKDOWN
            ))
            
            # Send reports for each symbol
            for symbol in config['symbols']:
                try:
                    analysis = analyze_option_data(symbol)
                    loop.run_until_complete(telegram_app.bot.send_message(
                        chat_id=user_id, 
                        text=analysis, 
                        parse_mode=ParseMode.MARKDOWN
                    ))
                    time.sleep(1)
                except Exception as e:
                    print(f"❌ Failed to send {symbol} report to {user_id}: {e}")
            
            loop.close()
                    
        except Exception as e:
            print(f"❌ Failed to send daily report to {user_id}: {e}")

def run_scheduler():
    """Run the daily report scheduler"""
    schedule.every().day.at("09:20").do(send_daily_reports)
    schedule.every().day.at("15:25").do(send_daily_reports)
    
    while True:
        schedule.run_pending()
        time.sleep(60)

def start_fastapi():
    """Start FastAPI in background thread"""
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10001, log_level="error")

# FastAPI endpoints
@app.get("/")
def health_check():
    return {
        "status": "NSE Option Bot is running",
        "nse_session": "active" if (nse_session and len(nse_session.cookies) > 0) else "inactive",
        "active_users": len(user_preferences),
        "telegram_bot": "active" if telegram_app else "inactive"
    }

@app.get("/users")
def get_users():
    """Debug endpoint to see user configurations"""
    if not user_preferences:
        return {"users": 0, "details": "No users configured"}
    
    user_details = {}
    for user_id, config in user_preferences.items():
        user_details[str(user_id)] = {
            "symbols": config.get('symbols', []),
            "daily_reports": config.get('daily_reports', False)
        }
    
    return {
        "users": len(user_preferences),
        "details": user_details
    }

@app.get("/test-nse")
def test_nse_connection():
    """Test NSE connectivity"""
    try:
        if not nse_session:
            create_nse_session()
        
        # Try a simple request to NSE
        response = nse_session.get('https://www.nseindia.com', timeout=10)
        
        return {
            "nse_status": "reachable" if response.status_code == 200 else "unreachable",
            "status_code": response.status_code,
            "cookies": len(nse_session.cookies),
            "test_time": time.strftime('%Y-%m-%d %H:%M:%S')
        }
    except Exception as e:
        return {
            "nse_status": "error",
            "error": str(e),
            "test_time": time.strftime('%Y-%m-%d %H:%M:%S')
        }

@app.post("/retry-nse")
def retry_nse_connection():
    """Manually retry NSE session initialization"""
    try:
        create_nse_session()
        success = initialize_nse_session()
        
        return {
            "success": success,
            "cookies": len(nse_session.cookies) if nse_session else 0,
            "message": "NSE session reinitialized" if success else "NSE session failed",
            "retry_time": time.strftime('%Y-%m-%d %H:%M:%S')
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "retry_time": time.strftime('%Y-%m-%d %H:%M:%S')
        }

def main():
    """Main function - Telegram bot in main thread, FastAPI in background"""
    global telegram_app, nse_session
    
    print("🚀 Starting NSE Option Chain Bot...")
    
    # Initialize NSE session (don't fail if this doesn't work initially)
    create_nse_session()
    session_ok = initialize_nse_session()
    
    if not session_ok:
        print("⚠️  NSE session failed, but continuing anyway. Will retry later.")
    
    # Start FastAPI in background thread
    print("🌐 Starting FastAPI server...")
    threading.Thread(target=start_fastapi, daemon=True).start()
    
    # Start scheduler in background thread
    print("⏰ Starting scheduler...")
    threading.Thread(target=run_scheduler, daemon=True).start()
    
    # Small delay to let FastAPI start
    time.sleep(3)
    
    try:
        # Create Telegram application (in main thread)
        print("🤖 Creating Telegram application...")
        telegram_app = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        telegram_app.add_handler(CommandHandler("start", start_command))
        telegram_app.add_handler(CommandHandler("stop", stop_command))
        telegram_app.add_handler(CommandHandler("status", status_command))
        telegram_app.add_handler(CallbackQueryHandler(handle_callback_query))
        telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_symbols))
        
        print("✅ Telegram bot configured successfully")
        print("✅ FastAPI server running in background")
        print("✅ All systems ready")
        
        # Run the bot in main thread (this blocks)
        telegram_app.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        print(f"❌ Critical error starting bot: {e}")
        # Fallback: just run FastAPI if Telegram fails
        print("🔄 Falling back to FastAPI-only mode...")
        
        # Keep the process alive for Render
        while True:
            time.sleep(60)

if __name__ == "__main__":
    main()