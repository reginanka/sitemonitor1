"""
Обробка відправлення повідомлень в Telegram
"""

import os
import logging
from pathlib import Path
from telegram import Bot
from telegram.error import TelegramError
import asyncio

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')
TELEGRAM_LOG_CHANNEL_ID = os.getenv('TELEGRAM_LOG_CHANNEL_ID')


async def send_message(message: str, channel_id: str = TELEGRAM_CHANNEL_ID):
    """Відправити текстове повідомлення"""
    if not TELEGRAM_BOT_TOKEN or not channel_id:
        logger.error("Telegram BOT_TOKEN або CHANNEL_ID не налаштовані")
        return False
    
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        await bot.send_message(
            chat_id=channel_id,
            text=message,
            parse_mode='HTML'
        )
        logger.info("Повідомлення відправлено в Telegram")
        return True
    except TelegramError as e:
        logger.error(f"Помилка при відправці Telegram: {e}")
        return False


async def send_photo(image_path: Path, caption: str = None, 
                    channel_id: str = TELEGRAM_CHANNEL_ID):
    """Відправити картинку"""
    if not TELEGRAM_BOT_TOKEN or not channel_id:
        logger.error("Telegram BOT_TOKEN або CHANNEL_ID не налаштовані")
        return False
    
    if not image_path.exists():
        logger.error(f"Файл картинки не знайдено: {image_path}")
        return False
    
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        with open(image_path, 'rb') as f:
            await bot.send_photo(
                chat_id=channel_id,
                photo=f,
                caption=caption,
                parse_mode='HTML'
            )
        logger.info(f"Картинка відправлена в Telegram: {image_path.name}")
        return True
    except TelegramError as e:
        logger.error(f"Помилка при відправці картинки Telegram: {e}")
        return False


def send_to_telegram_sync(message: str, image_path: Path = None):
    """Синхронна обгортка для відправлення"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(send_message(message))
        
        if image_path and image_path.exists():
            loop.run_until_complete(send_photo(image_path, caption=message))
    finally:
        loop.close()
