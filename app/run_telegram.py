# Copyright 2026 Burma Bites
import asyncio
import logging
import os
import signal
from dotenv import load_dotenv

# MUST load environment variables BEFORE importing agent code
load_dotenv()

from app.telegram_bots import create_bot_app, customer_handler, kitchen_handler, owner_handler

# Set up standard logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# To quiet down httpx logging
logging.getLogger("httpx").setLevel(logging.WARNING)

async def main():
    # Ensure environment variables are loaded (already done at top of file)
    
    customer_token = os.getenv("CUSTOMER_BOT_TOKEN")
    kitchen_token = os.getenv("KITCHEN_BOT_TOKEN")
    owner_token = os.getenv("OWNER_BOT_TOKEN")
    
    if not all([customer_token, kitchen_token, owner_token]):
        logger.error("Missing one or more Telegram bot tokens in environment.")
        logger.error("Ensure CUSTOMER_BOT_TOKEN, KITCHEN_BOT_TOKEN, and OWNER_BOT_TOKEN are set.")
        return

    logger.info("Initializing bots...")
    customer_bot = create_bot_app(customer_token, customer_handler)
    kitchen_bot = create_bot_app(kitchen_token, kitchen_handler)
    owner_bot = create_bot_app(owner_token, owner_handler)

    # Initialize all three bots
    await customer_bot.initialize()
    await kitchen_bot.initialize()
    await owner_bot.initialize()

    # Start all three bots
    await customer_bot.start()
    await kitchen_bot.start()
    await owner_bot.start()

    logger.info("Starting polling...")
    await customer_bot.updater.start_polling()
    await kitchen_bot.updater.start_polling()
    await owner_bot.updater.start_polling()

    logger.info("All 3 Telegram bots are running concurrently. Press Ctrl+C to stop.")
    
    # Wait for shutdown signal (Ctrl+C)
    stop_event = asyncio.Event()
    
    def signal_handler():
        logger.info("Stop signal received, shutting down gracefully...")
        stop_event.set()
        
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)
        
    await stop_event.wait()
    
    # Graceful shutdown
    logger.info("Stopping updaters...")
    await customer_bot.updater.stop()
    await kitchen_bot.updater.stop()
    await owner_bot.updater.stop()
    
    logger.info("Stopping applications...")
    await customer_bot.stop()
    await kitchen_bot.stop()
    await owner_bot.stop()
    
    logger.info("Shutting down...")
    await customer_bot.shutdown()
    await kitchen_bot.shutdown()
    await owner_bot.shutdown()
    logger.info("Shutdown complete.")

if __name__ == "__main__":
    asyncio.run(main())
