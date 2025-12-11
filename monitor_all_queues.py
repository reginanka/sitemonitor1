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
            log_text = "📊 <b>ЛОГ МОНІТОРИНГУ ВСІХ ЧЕРГ</b>\n\n"
            log_text += "<pre>"
            log_text += "\n".join(self.log_messages[-50:])
            log_text += "</pre>"
            log_text += f"\n\n⏰ Завершено: {ukraine_time.strftime('%d.%m.%Y %H:%M:%S')} (Київський час)"
            
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {
                'chat_id': TELEGRAM_LOG_CHANNEL_ID,
                'text': log_text,
                'parse_mode': 'HTML'
            }
            
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                self.log("✅ Лог відправлено у лог-канал")
            else:
                self.log(f"❌ Помилка відправки логу: {response.status_code}")
        except Exception as e:
            self.log(f"❌ Помилка відправки логу: {e}")
    
    def send_to_telegram(self, changed_queues):
        if not TELEGRAM_CHANNEL_ID or not TELEGRAM_BOT_TOKEN:
            self.log("⚠️ TELEGRAM_CHANNEL_ID або TELEGRAM_BOT_TOKEN не встановлені")
            return False
        
        if not changed_queues:
            self.log("✅ Змін не виявлено, сповіщення не відправляються")
            return True
        
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            
            message = "🔔 <b>ОНОВЛЕННЯ ГРАФІКУ ВІДКЛЮЧЕНЬ</b>\n\n"
            
            total_changes = sum(len(v) for v in changed_queues.values())
            message += f"\n📊 Усього змін: {total_changes}\n"
            message += "━" * 40 + "\n\n"
            
            for rem_idx, (rem, addresses) in enumerate(list(changed_queues.items())[:10], 1):
                message += f"<b>🏘️ {rem}</b>\n"
                
                for addr_info in addresses[:5]:
                    address = addr_info['address'][:60] + "..." if len(addr_info['address']) > 60 else addr_info['address']
                    message += f"  • {address}\n"
                
                if len(addresses) > 5:
                    message += f"  ... та ще {len(addresses) - 5} адрес\n"
                
                message += "\n"
            
            if len(changed_queues) > 10:
                remaining_rems = len(changed_queues) - 10
                message += f"... та ще {remaining_rems} районів\n\n"
            
            if SUBSCRIBE:
                message += f'\n<a href="{SUBSCRIBE}">⚡ ПІДПИСАТИСЯ ⚡</a>'
            
            data = {
                'chat_id': TELEGRAM_CHANNEL_ID,
                'text': message,
                'parse_mode': 'HTML'
            }
            
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                self.log(f"✅ Сповіщення про {total_changes} змін відправлено")
                return True
            else:
                self.log(f"❌ Помилка відправки: {response.status_code}")
                return False
        except Exception as e:
            self.log(f"❌ Помилка відправки сповіщення: {e}")
            return False
    
    def load_queues(self):
        try:
            with open(self.queues_file, 'r', encoding='utf-8') as f:
                queues = json.load(f)
                self.log(f"✅ Завантажено {len(queues)} черг з {self.queues_file}")
                return queues
        except FileNotFoundError:
            self.log(f"❌ Файл {self.queues_file} не знайдено")
            self.log("💡 Спочатку запусти: python export_all_queues.py")
            return []
    
    def get_schedule(self, queue_id, subqueue_id, retries=3):
        for attempt in range(retries):
            try:
                params = {
                    'cherga_id': queue_id,
                    'pidcherga_id': subqueue_id
                }
                response = requests.get(
                    f"{API_BASE_URL}api-schedule.php",
                    params=params,
                    timeout=10
                )
                response.raise_for_status()
                return response.json()
            except:
                if attempt < retries - 1:
                    continue
                return None
        return None
    
    def check_all_queues(self, queues):
        self.log("=" * 70)
        self.log("🔍 МОНІТОРИНГ ВСІХ ЧЕРГ (API)")
        self.log("=" *
