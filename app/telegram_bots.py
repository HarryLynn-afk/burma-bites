# Copyright 2026 Burma Bites
import logging
from telegram import Update
from telegram.ext import ContextTypes, ApplicationBuilder, MessageHandler, filters, CommandHandler
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agent import root_agent

logger = logging.getLogger(__name__)

# Shared session service for all bots
session_service = InMemorySessionService()

# Maps telegram chat_id to ADK session_id
chat_sessions: dict[str, str] = {}

async def get_session_id(chat_id: str) -> str:
    """Retrieve or create a session for a given chat_id."""
    if chat_id not in chat_sessions:
        session = await session_service.create_session(user_id=chat_id, app_name="telegram")
        chat_sessions[chat_id] = session.id
    return chat_sessions[chat_id]

async def process_agent_message(update: Update, prefix: str):
    """Pass the user's message to the ADK agent, optionally prefixing for routing."""
    if not update.message or not update.message.text:
        return

    chat_id = str(update.message.chat_id)
    user_text = update.message.text
    
    # Show typing indicator while the LLM generates a response
    await update.message.reply_chat_action(action="typing")

    try:
        session_id = await get_session_id(chat_id)
        runner = Runner(agent=root_agent, session_service=session_service, app_name="telegram")
        
        # Prepend keyword for routing (e.g., 'kitchen: ' to force kitchen agent)
        routed_text = f"{prefix} {user_text}" if prefix else user_text
        message = types.Content(role="user", parts=[types.Part.from_text(text=routed_text)])
        
        async for event in runner.run_async(
            new_message=message,
            user_id=chat_id,
            session_id=session_id
        ):
            if event.content and event.content.parts:
                reply_text = "".join(p.text for p in event.content.parts if hasattr(p, "text"))
                if reply_text.strip():
                    await update.message.reply_text(reply_text)
                    
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        await update.message.reply_text("Sorry, I encountered an error processing your request.")

async def customer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Customer bot handler — no prefix, defaults to Customer Agent."""
    await process_agent_message(update, "")

async def kitchen_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kitchen bot handler — forces routing to Kitchen Agent."""
    await process_agent_message(update, "kitchen:")

async def owner_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner bot handler — forces routing to Owner Agent."""
    await process_agent_message(update, "owner:")

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command for all bots."""
    await update.message.reply_text("Mingalaba! I am ready to help.")

def create_bot_app(token: str, handler_func):
    """Factory to create a Telegram Application with the given handler."""
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handler_func))
    return app
