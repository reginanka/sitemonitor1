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
URL = os.environ.get('URL')
SUBSCRIBE = os.environ.get('SUBSCRIBE')

QUEUES = [(i, j) for i in range(1, 7) for j in range(1, 2 + 1)]

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

CURRENT_FILE = DATA_DIR / "current.json"
HASH_FILE = DATA_DIR / "last_hash.json"


def fetch_schedule(cherga_id: int, pidcherga_id: int) -> List[Dict]:
    resp: Optional[requests.Response] = None
    try:
        params = {"cherga_id": cherga_id, "pidcherga_id": pidcherga_id}
        resp = requests.get(API_BASE_URL, params=params, timeout=10)
        resp.raise_for_status()

        text = resp.text.strip()

        if text.startswith("[") and text.endswith("]"):
            data = json.loads(text)
        else:
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


def extract_hashes(schedules: Dict[str, List[Dict]]) -> Dict[str, str]:
    """Витягує хеши для кожної черги"""
    hashes = {}
    for queue_key, schedule in schedules.items():
        hashes[queue_key] = calculate_hash(schedule)
    return hashes


def load_last_hashes() -> Dict[str, str]:
    hash_data = load_json(HASH_FILE)
    return hash_data.get("queues", {})


def save_hashes(hashes: Dict[str, str], timestamp: str) -> None:
    hash_data = {
        "timestamp": timestamp,
        "queues": hashes,
    }
    save_json(hash_data, HASH_FILE)


def get_changed_queues(
    current_hashes: Dict[str, str], last_hashes: Dict[str, str]
) -> List[str]:
    """Порівнює поточні хеши з попередніми"""
    changed = []
    for queue_key, current_hash in current_hashes.items():
        last_hash = last_hashes.get(queue_key)
        if last_hash is None:
            # Перший запуск для цієї черги
            log_to_buffer(f"ℹ️ Перший запуск для {queue_key}")
        elif current_hash != last_hash:
            # Є зміни!
            changed.append(queue_key)
            log_to_buffer(f"🔄 Зміна в {queue_key}: {last_hash[:8]}... → {current_hash[:8]}...")
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
        # 1. Завантажити графіки з API
        current_schedules = fetch_all_schedules()
        if not current_schedules:
            log_to_buffer("❌ Не вдалось завантажити жоден графік")
            return

        # 2. Зберегти поточні графіки в data/current.json
        save_json(current_schedules, CURRENT_FILE)
        log_to_buffer("💾 Графіки збережено в data/current.json")

        # 3. Витягти хеші поточних графіків
        current_hashes = extract_hashes(current_schedules)
        log_to_buffer(f"🔐 Витягнено хеші для {len(current_hashes)} черг")

        # 4. Завантажити попередні хеші
        last_hashes = load_last_hashes()
        log_to_buffer(f"📋 Завантажено попередні хеші для {len(last_hashes)} черг")

        # 5. Порівняти хеші і знайти змінені черги
        changed_queues = get_changed_queues(current_hashes, last_hashes)

        if not changed_queues:
            log_to_buffer("✅ Дані по всіх чергах не змінилися")
            # Все одно оновити timestamp
            save_hashes(current_hashes, timestamp)
            return

        log_to_buffer(f"🔔 Зміни виявлено для: {', '.join(changed_queues)}")

        # 6. Отримати текст і дату з сайту
        message_content, date_content = get_schedule_content()
        if not message_content:
            log_to_buffer("❌ Не вдалося отримати важливе повідомлення з сайту")
            return

        # 7. Скріншот із сайту
        screenshot_path, screenshot_hash = take_screenshot_between_elements()
        if not screenshot_path:
            log_to_buffer("❌ Не вдалося створити скріншот")

        # 8. Формування повідомлення для каналу
        queues_str = format_queues(changed_queues)
        final_message = (
            f"Для {queues_str} 🔔 ОНОВЛЕННЯ ГРАФІКА ВІДКЛЮЧЕНЬ\n\n"
            f"{message_content}\n\n"
            f"🔗 Переглянути графік на сайті\n{URL}\n\n"
        )
        if date_content:
            final_message += f"{date_content}\n\n"
        final_message += f"⚡ ПІДПИСАТИСЯ ⚡\n{SUBSCRIBE}"

        # 9. Відправити в Telegram
        from pathlib import Path as _Path

        img_path = _Path(screenshot_path) if screenshot_path else None
        ok = send_notification(final_message, img_path)
        if ok:
            log_to_buffer("✅ Повідомлення з оновленням відправлено в канал")
        else:
            log_to_buffer("❌ Помилка надсилання повідомлення в канал")

        # 10. Оновити хеші в data/last_hash.json
        save_hashes(current_hashes, timestamp)
        log_to_buffer("💾 Хеші оновлено в data/last_hash.json")

    except Exception as e:
        log_to_buffer(f"❌ Критична помилка: {e}")
    finally:
        send_log_to_channel()
        log_to_buffer("🏁 Завершення роботи скрипта")


if __name__ == "__main__":
    main()
