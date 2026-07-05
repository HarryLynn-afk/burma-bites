# Copyright 2026 Burma Bites
import json
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

# Maps telegram chat_id to ADK session_id, so each user has a persistent session
chat_sessions: dict[str, str] = {}


async def get_session_id(chat_id: str) -> str:
    """Retrieve or lazily create an ADK session for a given Telegram chat_id."""
    if chat_id not in chat_sessions:
        session = await session_service.create_session(user_id=chat_id, app_name="telegram")
        chat_sessions[chat_id] = session.id
    return chat_sessions[chat_id]


def extract_reply(raw_text: str, bot_role: str) -> str:
    """
    Extract a clean, user-facing message from an ADK agent response.

    The ADK LLM agents may return structured JSON (when output_schema is set)
    or plain text. This function attempts to parse JSON and extract the
    correct human-readable field for each bot role. If JSON parsing fails,
    it returns the raw text unchanged.

    Args:
        raw_text: The full text content from the ADK event.
        bot_role: One of "customer", "kitchen", or "owner".

    Returns:
        A clean string suitable for sending directly to a Telegram user.
    """
    try:
        data = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        # Not JSON — return as-is (plain LLM text)
        return raw_text

    if bot_role == "customer":
        # Customer agent schema: {"message_to_customer": "...", ...}
        return data.get("message_to_customer", raw_text)

    elif bot_role == "kitchen":
        # Kitchen agent schema: {"summary": "...", ...}
        return data.get("summary", raw_text)

    elif bot_role == "owner":
        # Owner agent may return sales summary + recommendations
        parts = []
        if "sales_summary" in data:
            parts.append(data["sales_summary"])
        if "recommendations" in data:
            recs = data["recommendations"]
            if isinstance(recs, list):
                parts.append("\n".join(f"• {r}" for r in recs))
            else:
                parts.append(str(recs))
        return "\n\n".join(parts) if parts else raw_text

    return raw_text


async def process_agent_message(update: Update, prefix: str, bot_role: str):
    """
    Route a Telegram message to the appropriate ADK agent and reply cleanly.

    Collects all events from the runner, assembles the final text response,
    extracts the clean user-facing field from any structured JSON output,
    and sends exactly one reply message back to the user.

    Args:
        update: The incoming Telegram update.
        prefix: Keyword prefix injected into the message text for ADK routing
                (e.g. "kitchen:" forces the graph to the kitchen branch).
        bot_role: "customer", "kitchen", or "owner" — used for JSON extraction.
    """
    if not update.message or not update.message.text:
        return

    chat_id = str(update.message.chat_id)
    user_text = update.message.text

    # Show typing indicator while the LLM generates a response
    await update.message.reply_chat_action(action="typing")

    try:
        session_id = await get_session_id(chat_id)
        runner = Runner(agent=root_agent, session_service=session_service, app_name="telegram")

        # Prepend keyword so the graph router sends this to the correct agent
        routed_text = f"{prefix} {user_text}" if prefix else user_text
        message = types.Content(role="user", parts=[types.Part.from_text(text=routed_text)])

        # Collect all final-text events; skip tool-call and routing events
        response_parts: list[str] = []
        async for event in runner.run_async(
            new_message=message,
            user_id=chat_id,
            session_id=session_id
        ):
            # Only process events that carry actual text content
            if not event.content or not event.content.parts:
                continue
            # Skip intermediate events (tool calls, routing); only keep final agent replies
            if event.actions and event.actions.route:
                continue

            chunk = "".join(
                p.text for p in event.content.parts
                if hasattr(p, "text") and p.text
            )
            if chunk.strip():
                response_parts.append(chunk.strip())

        # Combine all collected chunks into one reply
        full_reply = "\n".join(response_parts)

        if full_reply:
            # Extract the clean user-facing field from structured JSON, if present
            clean_reply = extract_reply(full_reply, bot_role)
            await update.message.reply_text(clean_reply)
        else:
            await update.message.reply_text("I received your message but have no response at this time.")

    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        await update.message.reply_text("Sorry, I encountered an error processing your request.")


async def customer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Customer bot handler — no prefix, defaults to Customer Agent."""
    await process_agent_message(update, "", "customer")


async def kitchen_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kitchen bot handler — forces routing to Kitchen Agent."""
    await process_agent_message(update, "kitchen:", "kitchen")


async def owner_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner bot handler — forces routing to Owner Agent."""
    await process_agent_message(update, "owner:", "owner")


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command — send a greeting in all three bots."""
    await update.message.reply_text("Mingalaba! 🍜 I am ready to help.")


def create_bot_app(token: str, handler_func):
    """Factory to create a configured Telegram Application with the given message handler."""
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handler_func))
    return app
