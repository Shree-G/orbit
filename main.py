import logging
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from config.settings import TELEGRAM_BOT_TOKEN
from database.supabase_client import supabase
from onboarding.quiz_manager import QuizManager
from auth.oauth_flow import get_authorization_url

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start command handler.
    1. Registers user in DB.
    2. Checks quiz status.
    3. Starts quiz if needed.
    """
    user = update.effective_user
    if not user:
        return

    telegram_id = user.id
    username = user.username or "Unknown"
    
    logger.info(f"User {telegram_id} ({username}) started the bot.")

    # 1. Register User (Upsert)
    try:
        data = {
            "telegram_id": telegram_id,
            "email": None, # Will be filled later or via Google Auth
        }
        
        res = supabase.table("users").select("quiz_completed").eq("telegram_id", telegram_id).execute()
        
        if not res.data:
            # New User
            supabase.table("users").insert(data).execute()
            quiz_completed = False
        else:
            quiz_completed = res.data[0]['quiz_completed']

    except Exception as e:
        logger.error(f"Database Error: {e}")
        await update.message.reply_text("Internal Server Error. Please try again later.")
        return

    # 2. Check Quiz Status
    if not quiz_completed:
        # Start Quiz
        question = QuizManager.start_quiz(telegram_id)
        await update.message.reply_text(question)
    else:
        await update.message.reply_text("Welcome back! You have already verified your profile. Run /setup to connect your Google Calendar.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Main message handler.
    Routes to QuizManager if quiz is incomplete.
    """
    user = update.effective_user
    if not user:
        return
        
    telegram_id = user.id
    text = update.message.text

    # 1. Check Quiz Status
    try:
        res = supabase.table("users").select("quiz_completed").eq("telegram_id", telegram_id).execute()
        if not res.data:
            # Should normally not happen if /start was run, but handle graceful
             await start(update, context)
             return
             
        quiz_completed = res.data[0]['quiz_completed']
        
    except Exception as e:
        logger.error(f"Database Error: {e}")
        return

    if not quiz_completed:
        # Route to QuizManager
        response_text = await asyncio.to_thread(QuizManager.handle_response, telegram_id, text)
        await update.message.reply_text(response_text)
    else:
        # Agent Logic (Placeholder)
        await update.message.reply_text("I heard you, but my brain (Agent) isn't connected yet! Check back on Day 6.")

async def setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /setup command handler.
    Generates and sends the Google OAuth 2.0 authorization link.
    """
    user = update.effective_user
    if not user:
        return
        
    telegram_id = user.id
    
    try:
        logger.info(f"Generating OAuth URL for user {telegram_id}")
        auth_url = get_authorization_url(telegram_id)
        
        msg = (
            "🔗 *Google Calendar Integration*\n\n"
            "Please click the link below to authorize Orbit to access your calendar. "
            "This allows me to schedule and manage your events proactively.\n\n"
            f"[Authorize with Google]({auth_url})"
        )
        
        await update.message.reply_text(msg, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error generating OAuth URL: {e}")
        await update.message.reply_text("Error generating authorization link. Please check the logs.")

if __name__ == '__main__':
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN is missing.")
        exit(1)
        
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    start_handler = CommandHandler('start', start)
    setup_handler = CommandHandler('setup', setup)
    msg_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    
    application.add_handler(start_handler)
    application.add_handler(setup_handler)
    application.add_handler(msg_handler)
    
    print("Bot is polling...")
    application.run_polling()