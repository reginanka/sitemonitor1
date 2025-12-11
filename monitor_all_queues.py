import requests
import json
import os
import hashlib
import pytz
import sys
from datetime import datetime
from collections import defaultdict

# ============= КОНФІГУРАЦІЯ З SECRETS =============
API_BASE_URL = os.environ.get('API_BASE_URL', 'https://www.ztoe.com.ua/gpv/api/')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.environ.get('TELEGRAM_CHANNEL_ID')
TELEGRAM_LOG_CHANNEL_ID = os.environ.get('TELEGRAM_LOG_CHANNEL_ID')
SUBSCRIBE = os.environ.get('SUBSCRIBE')

UKRAINE_TZ = pytz.timezone('Europe/Kyiv')

class MultiQueueMonitor:
    def __init__(self):
        self.queues_file = 'all_queues.json'
        self.last_hash_file = 'last_multi_hash.json'
        self.changes = []
        self.log_messages = []
    
    def log(self, message):
        """Логування з часовою міткою"""
        print(message)
        ukraine_time = datetime.now(pytz.utc).astimezone(UKRAINE_TZ)
        self.log_messages.append(f"{ukraine_time.strftime('%H:%M:%S')} - {message}")
    
    def validate_config(self):
        """Перевірити конфігурацію"""
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
        """Відправити журнал логів у Telegram лог-канал"""
        if not TELEGRAM_LOG_CHANNEL_ID or not TELEGRAM_BOT_TOKEN:
            return
        
        if not self.log_messages:
            return
        
        try:
            ukraine_time = datetime.now(pytz.utc).astimezone(UKRAINE_TZ)
            log_text = "📊 <b>ЛОГ МОНІТОРИНГУ ВСІХ ЧЕРГ</b>\n\n"
            log_text += "<pre>"
            log_text += "\n".join(self.log_messages[-50:])  # Останні 50 рядків
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
        """Відправити сповіщення про зміни у Telegram"""
        if not TELEGRAM_CHANNEL_ID or not TELEGRAM_BOT_TOKEN:
            self.log("⚠️ TELEGRAM_CHANNEL_ID або TELEGRAM_BOT_TOKEN не встановлені")
            return False
        
        if not changed_queues:
            self.log("✅ Змін не виявлено, сповіщення не відправляються")
            return True
        
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            
            message = "🔔 <b>ОНОВЛЕННЯ ГРАФІКУ ВІДКЛЮЧЕНЬ:</b>\n\n"
            
            total_changes = sum(len(v) for v in changed_queues.values())
            message += f"\n📊 Усього змін: {total_changes}\n"
            message += "━" * 40 + "\n\n"
            
            # Группувати по РЕМ (максимум 10)
            for rem_idx, (rem, addresses) in enumerate(list(changed_queues.items())[:10], 1):
                message += f"<b>🏘️ {rem}</b>\n"
                
                # Максимум 5 адрес на РЕМ
                for addr_info in addresses[:5]:
                    # Скоротити довгі адреси
                    address = addr_info['address'][:60] + "..." if len(addr_info['address']) > 60 else addr_info['address']
                    message += f"  • {address}\n"
                
                # Якщо більше ніж 5
                if len(addresses) > 5:
                    message += f"  ... та ще {len(addresses) - 5} адрес\n"
                
                message += "\n"
            
            # Якщо більше ніж 10 РЕМів
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
        """Завантажити список всіх черг"""
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
        """Отримати графік для однієї черги з повторами"""
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
            except requests.exceptions.Timeout:
                if attempt < retries - 1:
                    continue
                return None
            except Exception:
                return None
        return None
    
    def check_all_queues(self, queues):
        """Перевірити всі чергі на зміни"""
        self.log("=" * 70)
        self.log("🔍 МОНІТОРИНГ ВСІХ ЧЕРГ (API)")
        self.log("=" * 70)
        self.log(f"📍 Усього черг для перевірки: {len(queues)}\n")
        
        changed_queues = defaultdict(list)
        total_checked = 0
        total_changed = 0
        total_errors = 0
        
        # Завантажити попередні хеші
        last_hashes = self.load_last_hashes()
        
        for idx, queue in enumerate(queues, 1):
            queue_id = queue['queue_id']
            subqueue_id = queue['subqueue_id']
            address = queue['full_address']
            rem_name = queue['rem_name']
            
            total_checked += 1
            
            # Отримати поточний графік
            schedule = self.get_schedule(queue_id, subqueue_id)
            
            if schedule:
                # Генерувати хеш
                schedule_str = json.dumps(schedule, ensure_ascii=False, sort_keys=True)
                current_hash = hashlib.md5(schedule_str.encode('utf-8')).hexdigest()
                
                # Ключ для зберігання
                key = f"{queue_id}_{subqueue_id}"
                last_hash = last_hashes.get(key)
                
                # Перевірити на зміни
                if last_hash and last_hash != current_hash:
                    total_changed += 1
                    self.log(f"🔔 ЗМІНИ: {address}")
                    changed_queues[rem_name].append({
                        'address': address,
                        'queue_id': queue_id,
                        'subqueue_id': subqueue_id
                    })
                
                # Оновити хеш (новий або змінений)
                last_hashes[key] = current_hash
            else:
                total_errors += 1
            
            # Прогрес кожні 100 черг
            if total_checked % 100 == 0:
                self.log(f"✓ Перевірено {total_checked}/{len(queues)} черг ({total_changed} змін, {total_errors} помилок)")
        
        # Зберегти нові хеші
        self.save_last_hashes(last_hashes)
        
        self.log("\n" + "=" * 70)
        self.log(f"✅ ЗАВЕРШЕНО:")
        self.log(f"   • Перевірено: {total_checked}/{len(queues)} черг")
        self.log(f"   • Змін виявлено: {total_changed}")
        self.log(f"   • Помилок: {total_errors}")
        self.log("=" * 70)
        
        return changed_queues
    
    def load_last_hashes(self):
        """Завантажити попередні хеші"""
        try:
            with open(self.last_hash_file, 'r', encoding='utf-8') as f:
                hashes = json.load(f)
                self.log(f"📝 Завантажено {len(hashes)} попередніх хешів")
                return hashes
        except:
            self.log("⚠️ Попередніх хешів не знайдено (перший запуск)")
            return {}
    
    def save_last_hashes(self, hashes):
        """Зберегти хеші"""
        with open(self.last_hash_file, 'w', encoding='utf-8') as f:
            json.dump(hashes, f, indent=2)
        self.log(f"💾 Хеші збережено ({len(hashes)} записів)")
    
    def run(self):
        """Запустити повний моніторинг"""
        try:
            # Валідація конфігурації
            if not self.validate_config():
                return
            
            # Завантажити чергу
            queues = self.load_queues()
            if not queues:
                return
            
            # Перевірити всі чергу
            changed_queues = self.check_all_queues(queues)
            
            # Відправити сповіщення
            self.send_to_telegram(changed_queues)
            
        except Exception as e:
            self.log(f"❌ Критична помилка: {e}")
        finally:
            # Завжди відправити логи
            self.send_log_to_telegram()

if __name__ == '__main__':
    monitor = MultiQueueMonitor()
    monitor.run()
