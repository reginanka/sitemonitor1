import os
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests

from log_utils import log_to_buffer, send_log_to_channel
from site_content import get_schedule_content, take_screenshot_between_elements
from telegram_handler import send_notification

API_BASE_URL = os.getenv("API_BASE_URL")

QUEUES = [(i, j) for i in range(1, 7) for j in range(1, 2 + 1)]

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

CURRENT_FILE = DATA_DIR / "current.json"
PREVIOUS_FILE = DATA_DIR / "previous.json"
HASH_FILE = DATA_DIR / "last_hash.json"


def fetch_schedule(cherga_id: int, pidcherga_id: int) -> List[Dict]:
    resp: Optional[requests.Response] = None
    try:
        params = {"cherga_id": cherga_id, "pidcherga_id": pidcherga_id}
        resp = requests.get(API_BASE_URL, params=params, timeout=10)
        resp.raise_for_status()

        text = resp.text.strip()

        # якщо це вже масив, просто парсимо
        if text.startswith("[") and text.endswith("]"):
            data = json.loads(text)
        else:
            # формат {...},{...},{...} → робимо [{...},{...},{...}]
            if text.startswith("{"):
                text = f"[{text}]"
            data = json.loads(text)

        if isinstance(data, list):
            return data

        log_to_buffer(f"⚠️ Відповідь не список для {cherga_id}.{pidcherga_id}")
        return []

    except Exception as e:
        body = resp.text[:200] if resp is not None else ""
        log_to_buffer(
            f"❌ Помилка {cherga_id}.{pidcherga_id}: {e}. "
            f"Фрагмент відповіді: {body}"
        )
        return []


def fetch_all_schedules() -> Dict[str, List[Dict]]:
    all_schedules: Dict[str, List[Dict]] = {}
    log_to_buffer("📡 Завантажую графіки по всіх чергах...")

    for cherga_id, pidcherga_id in QUEUES:
        queue_key = f"{cherga_id}.{pidcherga_id}"
        schedule = fetch_schedule(cherga_id, pidcherga_id)
        all_schedules[queue_key] = schedule
        log_to_buffer(f"  ✓ {queue_key}: {len(schedule)} записів")

    return all_schedules


def save_json(data, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(path: Path):
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def calculate_hash(obj) -> str:
    json_str = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(json_str.encode("utf-8")).hexdigest()


def load_last_hash() -> Dict:
    return load_json(HASH_FILE)


def save_last_hash(schedules: Dict, timestamp: str) -> None:
    hash_data = {
        "timestamp": timestamp,
        "schedules_hash": calculate_hash(schedules),
        "queues": {
            key: calculate_hash(schedule)
            for key, schedule in schedules.items()
        },
    }
    save_json(hash_data, HASH_FILE)


def get_changed_queues(
    current_schedules: Dict[str, List[Dict]], last_hash_data: Dict
) -> List[str]:
    last_queues_hashes: Dict[str, str] = last_hash_data.get("queues", {})
    changed: List[str] = []
    for queue_key, schedule in current_schedules.items():
        queue_hash = calculate_hash(schedule)
        if queue_hash != last_queues_hashes.get(queue_key):
            changed.append(queue_key)
    return changed


def format_queues(queues: List[str]) -> str:
    queues = sorted(queues)
    if len(queues) == 1:
        return f"черги {queues[0]}"
    if len(queues) == 2:
        return f"черг {queues[0]} та {queues[1]}"
    return "черг " + ", ".join(queues)


def main():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_to_buffer("=" * 60)
    log_to_buffer(f"🚀 СТАРТ [{timestamp}]")
    log_to_buffer("=" * 60)

    try:
        # 1. Завантаження графіків по API
        current_schedules = fetch_all_schedules()
        if not current_schedules:
            log_to_buffer("❌ Не вдалось завантажити жоден графік")
            return

        # 2. Перевірка загального хешу
        last_hash_data = load_last_hash()
        current_hash = calculate_hash(current_schedules)

        if current_hash == last_hash_data.get("schedules_hash"):
            log_to_buffer("✅ Дані по всіх чергах не змінилися (хеш збігається)")
            return

        log_to_buffer("⚠️ Є зміни в даних (загальний хеш інший)")

        # 3. Визначити, які саме черги змінилися
        changed_queues = get_changed_queues(current_schedules, last_hash_data)
        if not changed_queues:
            log_to_buffer("⚠️ Загальний хеш змінився, але список змінених черг порожній")
            return

        log_to_buffer(f"🔔 Зміни виявлено для: {', '.join(changed_queues)}")

        # 4. Отримати текст і дату з сайту
        message_content, date_content = get_schedule_content()
        if not message_content:
            log_to_buffer("❌ Не вдалося отримати важливе повідомлення з сайту")
            return

        # 5. Скріншот із сайту
        screenshot_path, screenshot_hash = take_screenshot_between_elements()
        if not screenshot_path:
            log_to_buffer("❌ Не вдалося створити скріншот")

        # 6. Формування повідомлення для каналу
        queues_str = format_queues(changed_queues)
        final_message = (
            f"Для {queues_str} 🔔 ОНОВЛЕННЯ ГРАФІКА ВІДКЛЮЧЕНЬ\n\n"
            f"{message_content}\n\n"
            f"🔗 Переглянути графік на сайті\n\n"
        )
        if date_content:
            final_message += f"{date_content}\n\n"
        final_message += "⚡️ ПІДПИСАТИСЯ ⚡️"

        # 7. Відправити в Telegram
        from pathlib import Path as _Path

        img_path = _Path(screenshot_path) if screenshot_path else None
        ok = send_notification(final_message, img_path)
        if ok:
            log_to_buffer("✅ Повідомлення з оновленням відправлено в канал")
        else:
            log_to_buffer("❌ Помилка надсилання повідомлення в канал")

        # 8. Оновити last_hash по API
        save_json(current_schedules, CURRENT_FILE)
        save_json(current_schedules, PREVIOUS_FILE)
        save_last_hash(current_schedules, timestamp)
        log_to_buffer("💾 Дані по API-хешах збережено")

    except Exception as e:
        log_to_buffer(f"❌ Критична помилка: {e}")
    finally:
        send_log_to_channel()
        log_to_buffer("🏁 Завершення роботи скрипта")


if __name__ == "__main__":
    main()
