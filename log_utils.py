import os
from datetime import datetime
from typing import List
import pytz
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_LOG_CHANNEL_ID = os.getenv("TELEGRAM_LOG_CHANNEL_ID")
UKRAINE_TZ = pytz.timezone("Europe/Kyiv")

log_messages: List[str] = []


def get_ukraine_time() -> datetime:
    return datetime.now().astimezone(UKRAINE_TZ)


def log_to_buffer(message: str) -> None:
    ts = get_ukraine_time().strftime("%H:%M:%S")
    line = f"{ts} - {message}"
    print(line)
    log_messages.append(line)


def send_log_to_channel() -> None:
    if not TELEGRAM_LOG_CHANNEL_ID or not TELEGRAM_BOT_TOKEN or not log_messages:
        return

    try:
        text = "📊 ЛОГ ВИКОНАННЯ СКРИПТА\n\n"
        text += "\n".join(log_messages)
        text += (
            f"\n\n⏰ Завершено: "
            f"{get_ukraine_time().strftime('%d.%m.%Y %H:%M:%S')} (Київський час)"
        )

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": TELEGRAM_LOG_CHANNEL_ID,
            "text": text,
            "parse_mode": "HTML",
        }
        requests.post(url, data=data, timeout=10)
    except Exception:
        pass
