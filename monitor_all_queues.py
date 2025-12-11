import requests
import json
import os
import hashlib
import pytz
from datetime import datetime
from collections import defaultdict

API_BASE_URL = os.environ.get('API_BASE_URL')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.environ.get('TELEGRAM_CHANNEL_ID')
TELEGRAM_LOG_CHANNEL_ID = os.environ.get('TELEGRAM_LOG_CHANNEL_ID')
SUBSCRIBE = os.environ.get('SUBSCRIBE')

UKRAINE_TZ = pytz.timezone('Europe/Kyiv')


class MultiQueueMonitor:
    def __init__(self):
        self.queues_file = 'all_queues.json'
        self.last_hash_file = 'last_multi_hash.json'
        self.log_messages = []

    def log(self, message):
        print(message)
        ukraine_time = datetime.now(pytz.utc).astimezone(UKRAINE_TZ)
        self.log_messages.append(f"{ukraine_time.strftime('%H:%M:%S')} - {message}")

    def validate_config(self):
        errors = []

        if not API_BASE_URL:
            errors.append("❌ API_BASE_URL не встановлено")

        if not TELEGRAM_BOT_TOKEN:
            errors.append("❌ TELEGRAM_BOT_TOKEN не встановлено")

        if not TELEGRAM_CHANNEL_ID:
            errors.append("❌ TELEGRAM_CHANNEL_ID не встановлено")

        if errors:
            for error in errors:
                self.log(error)
            return False

        self.log("✅ Конфігурація встановлена коректно")
        return True

    def send_log_to_telegram(self):
        if not TELEGRAM_LOG_CHANNEL_ID or not TELEGRAM_BOT_TOKEN:
            return

        if not self.log_messages:
            return

        try:
            ukraine_time = datetime.now(pytz.utc).astimezone(UKRAINE_TZ)

            log_text = "📊 ЛОГ МОНІТОРИНГУ ВСІХ ЧЕРГ\n\n"
            log_text += "\n".join(self.log_messages[-50:])
            log_text += (
                f"\n\n⏰ Завершено: "
                f"{ukraine_time.strftime('%d.%m.%Y %H:%M:%S')} (Київський час)"
            )

            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {
                "chat_id": TELEGRAM_LOG_CHANNEL_ID,
                "text": log_text,
                "parse_mode": "HTML",
            }

            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                self.log("✅ Лог відправлено у лог-канал")
            else:
                self.log(f"❌ Помилка відправки логу: {response.status_code}")
        except Exception as e:
            self.log(f"❌ Помилка відправки логу: {e}")

    def load_all_queues(self):
        if not os.path.exists(self.queues_file):
            self.log(f"❌ Файл {self.queues_file} не знайдено")
            return []

        try:
            with open(self.queues_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.log(f"✅ Завантажено {len(data)} записів із {self.queues_file}")
            return data
        except Exception as e:
            self.log(f"❌ Помилка читання {self.queues_file}: {e}")
            return []

    def load_last_hash(self):
        if not os.path.exists(self.last_hash_file):
            self.log("ℹ️ Файл з попереднім хешем не знайдено, буде створено новий")
            return None

        try:
            with open(self.last_hash_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data
        except Exception as e:
            self.log(f"❌ Помилка читання {self.last_hash_file}: {e}")
            return None

    def save_last_hash(self, hash_data):
        try:
            with open(self.last_hash_file, 'w', encoding='utf-8') as f:
                json.dump(hash_data, f, ensure_ascii=False, indent=2)
            self.log(f"💾 Оновлено {self.last_hash_file}")
        except Exception as e:
            self.log(f"❌ Помилка запису {self.last_hash_file}: {e}")

    def get_current_queues_state(self, all_queues):
        grouped = defaultdict(list)
        for item in all_queues:
            key = (
                item.get("queue_id"),
                item.get("subqueue_id"),
                item.get("rem_id"),
                item.get("city_id"),
            )
            grouped[key].append(item)
        return grouped

    def compute_hash(self, grouped_state):
        try:
            normalized = []
            for key in sorted(grouped_state.keys()):
                records = grouped_state[key]
                normalized.append(
                    {
                        "key": key,
                        "count": len(records),
                    }
                )

            raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
            return hashlib.md5(raw.encode('utf-8')).hexdigest()
        except Exception as e:
            self.log(f"❌ Помилка обчислення хешу: {e}")
            return None

    def build_change_message(self, diff_info):
        message_lines = ["🔔 ОНОВЛЕННЯ ЧЕРГ", ""]
        message_lines.append("Виявлено зміни в конфігурації черг.")
        message_lines.append("")
        message_lines.append("Деталі можна переглянути в оновлених даних.")
        return "\n".join(message_lines)

    def send_to_telegram(self, changed_queues):
        if not TELEGRAM_CHANNEL_ID or not TELEGRAM_BOT_TOKEN:
            self.log("⚠️ TELEGRAM_CHANNEL_ID або TELEGRAM_BOT_TOKEN не встановлені")
            return False

        if not changed_queues:
            self.log("✅ Змін не виявлено, сповіщення не відправляються")
            return True

        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            message = self.build_change_message(changed_queues)

            data = {
                "chat_id": TELEGRAM_CHANNEL_ID,
                "text": message,
                "parse_mode": "HTML",
