import httpx
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

# Global session for NSE requests (HTTP2)
nse_client = None

# Bot application instance
telegram_app = None

# User preferences storage
user_preferences = {}

def create_nse_client():
    """Create HTTP2 client optimized for NSE API calls on cloud servers"""
    global nse_client
    
    # HTTP2 headers that work with NSE from cloud servers
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache'
    }
    
    # Create HTTP2 client - this is the key difference for cloud servers
    nse_client = httpx.Client(
        headers=headers,
        http2=True,  # This enables HTTP2 - crucial for cloud servers
        timeout=30.0,
        follow_redirects=True
    )
    
    print("✅ HTTP2 client created for NSE")
    return nse_client

def initialize_nse_session():
    """Initialize HTTP2 session for cloud server compatibility"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"🔄 HTTP2 session attempt {attempt + 1}/{max_retries}")
            
            # Visit NSE homepage with HTTP2
            response = nse_client.get('https://www.nseindia.com', timeout=30)
            
            if response.status_code != 200:
                print(f"⚠️  Homepage returned {response.status_code}")
                if attempt < max_retries - 1:
                    time.sleep(5)
                    continue
                return False
            
            print(f"✅ NSE homepage accessible via HTTP2: {response.status_code}")
            
            # Visit additional pages to establish session
            try:
                nse_client.get('https://www.nseindia.com/market-data', timeout=20)
                nse_client.get('https://www.nseindia.com/option-chain', timeout=20)
            except Exception as e:
                print(f"⚠️  Secondary pages failed: {e}")
                # Continue anyway, main page worked
            
            time.sleep(2)
            
            # Update headers for API calls
            nse_client.headers.update({
                'Accept': 'application/json, text/plain, */*',
                'Referer': 'https://www.nseindia.com/option-chain',
                'X-Requested-With': 'XMLHttpRequest',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-origin'
            })
            
            print(f"✅ HTTP2 session initialized successfully on attempt {attempt + 1}")
            return True
            
        except Exception as e:
            print(f"❌ HTTP2 session attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                print(f"⏳ Retrying in 10 seconds...")
                time.sleep(10)
            else:
                print("❌ All HTTP2 session attempts failed")
                return False
    
    return False

def get_nse_option_chain(symbol: str):
    """Fetch option chain data using HTTP2 client"""
    try:
        indices = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX']
        
        if symbol.upper() in indices:
            api_url = f'https://www.nseindia.com/api/option-chain-indices?symbol={symbol.upper()}'
        else:
            api_url = f'https://www.nseindia.com/api/option-chain-equities?symbol={symbol.upper()}'
        
        # Use HTTP2 client instead of requests
        response = nse_client.get(api_url, timeout=20)
        
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
            print(f"❌ HTTP2 request failed: {response.status_code}")
            return None, None
            
    except Exception as e:
        print(f"❌ HTTP2 request exception: {e}")
        return None, None

def analyze_option_data(symbol: str) -> str:
    """Generate option chain analysis using HTTP2"""
    try:
        # Ensure HTTP2 client is working
        if not nse_client:
            print(f"🔄 Creating HTTP2 client for {symbol}")
            create_nse_client()
            if not initialize_nse_session():
                return f"❌ Could not establish HTTP2 connection for {symbol.upper()}"
        
        records, option_data = get_nse_option_chain(symbol)
        
        if not records or not option_data:
            # Try reinitializing session once more
            print(f"🔄 Retrying HTTP2 connection for {symbol}")
            create_nse_client()
            if initialize_nse_session():
                records, option_data = get_nse_option_chain(symbol)
            
            if not records or not option_data:
                return f"""❌ No option data available for *{symbol.upper()}*

🔧 **Possible reasons:**
• Symbol may not have active F&O trading
• NSE API temporarily unavailable
• Network connectivity issues

💡 **Try these symbols instead:**
NIFTY, BANKNIFTY, RELIANCE, TCS, HDFCBANK

🔄 **Using HTTP2 protocol for cloud server compatibility**"""
        
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

**📊 PCR:** `{pcr}` | **🎯 Bias:** {sentiment}

🔗 *Powered by HTTP2 for cloud compatibility*"""
        
    except Exception as e:
        return f"""❌ Analysis error for *{symbol.upper()}*

**Error:** {str(e)}

🔄 **Using HTTP2 protocol - please try again**"""

# Telegram Bot Handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    nse_available = nse_client is not None
    status_info = "🟢 **HTTP2 Connection Active**" if nse_available else "🔶 **Initializing Connection...**"
    
    welcome_message = f"""🎯 **Welcome to NSE Option Chain Bot!**

{status_info}

📊 **Features:**
• Real-time option chain analysis
• Put-Call Ratio (PCR) calculations
• Maximum Call/Put OI tracking
• Daily scheduled reports

🔸 **Please send me a list of symbols (comma-separated)**

**Examples:**
`NIFTY, BANKNIFTY, RELIANCE`
`TCS, HDFCBANK, ICICIBANK`
`FINNIFTY, INFY, LT`

💡 **All NSE F&O symbols supported**
🚀 *Using HTTP2 protocol for cloud server compatibility*"""

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
    """Send daily reports using HTTP2 client"""
    if not telegram_app or not user_preferences:
        return
        
    # Ensure HTTP2 client is ready
    if not nse_client:
        create_nse_client()
        initialize_nse_session()
    
    for user_id, config in user_preferences.items():
        if not config.get('daily_reports', False):
            continue
            
        try:
            # Send reports using HTTP2 client
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
    print("🌐 FastAPI starting on port 10001...")
    uvicorn.run(app, host="0.0.0.0", port=10001, log_level="error")

# FastAPI endpoints
@app.get("/")
def health_check():
    nse_working = nse_client is not None
    
    return {
        "status": "NSE Option Bot is running",
        "protocol": "HTTP2",
        "nse_connection": "active" if nse_working else "inactive",
        "active_users": len(user_preferences),
        "telegram_bot": "active" if telegram_app else "inactive",
        "note": "Using HTTP2 protocol for cloud server compatibility"
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
    """Test NSE connectivity with HTTP2"""
    try:
        if not nse_client:
            create_nse_client()
        
        # Try a simple HTTP2 request to NSE
        response = nse_client.get('https://www.nseindia.com', timeout=10)
        
        return {
            "protocol": "HTTP2",
            "nse_status": "reachable" if response.status_code == 200 else "unreachable",
            "status_code": response.status_code,
            "http_version": str(response.http_version),
            "test_time": time.strftime('%Y-%m-%d %H:%M:%S')
        }
    except Exception as e:
        return {
            "protocol": "HTTP2",
            "nse_status": "error",
            "error": str(e),
            "test_time": time.strftime('%Y-%m-%d %H:%M:%S')
        }

@app.post("/retry-nse")
def retry_nse_connection():
    """Manually retry NSE HTTP2 connection"""
    try:
        create_nse_client()
        success = initialize_nse_session()
        
        return {
            "success": success,
            "protocol": "HTTP2",
            "message": "HTTP2 connection reinitialized" if success else "HTTP2 connection failed",
            "retry_time": time.strftime('%Y-%m-%d %H:%M:%S')
        }
    except Exception as e:
        return {
            "success": False,
            "protocol": "HTTP2",
            "error": str(e),
            "retry_time": time.strftime('%Y-%m-%d %H:%M:%S')
        }

def main():
    """Main function - Telegram bot in main thread, FastAPI in background"""
    global telegram_app, nse_client
    
    print("🚀 Starting NSE Option Chain Bot with HTTP2...")
    
    # Initialize HTTP2 client (cloud server compatible)
    create_nse_client()
    session_ok = initialize_nse_session()
    
    if session_ok:
        print("✅ HTTP2 connection to NSE established")
    else:
        print("⚠️  HTTP2 connection failed, but continuing anyway")
    
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
        print("✅ HTTP2 client ready for NSE API calls")
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