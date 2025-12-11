import requests
import json
import os
import hashlib
import pytz
import sys
from datetime import datetime
from collections import defaultdict

# ============= КОНФІГУРАЦІЯ =============
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
        self.changes = []
        self.log_messages = []
    
    def log(self, message):
        """Логування з часовою міткою"""
        print(message)
        ukraine_time = datetime.now(pytz.utc).astimezone(UKRAINE_TZ)
        self.log_messages.append(f"{ukraine_time.strftime('%H:%M:%S')} - {message}")
    
    def send_log_to_telegram(self):
        if not TELEGRAM_LOG_CHANNEL_ID or not TELEGRAM_BOT_TOKEN:
            return
        
        if not self.log_messages:
            return
        
        try:
            ukraine_time = datetime.now(pytz.utc).astimezone(UKRAINE_TZ)
            log_text = "📊 <b>ЛОГ МОНІТОРИНГУ ВСІХ ЧЕРГ</b>\n\n"
            log_text += "<pre>"
            log_text += "\n".join(self.log_messages)
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
                print("✅ Лог відправлено у лог-канал")
            else:
                print(f"❌ Помилка відправки логу: {response.text}")
        except Exception as e:
            print(f"❌ Помилка відправки логу: {e}")
    
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
            
            message = "🔔 <b>ОНОВЛЕННЯ ГРАФІКУ ВІДКЛЮЧЕНЬ</b>\n\n"
            message += "⚠️ <b>ВИЯВЛЕНІ ЗМІНИ:</b>\n"
            
            total_changes = sum(len(v) for v in changed_queues.values())
            message += f"\n📊 Усього змін: {total_changes}\n"
            message += "━" * 40 + "\n\n"
            
            # Группувати по РЕМ
            for rem, addresses in list(changed_queues.items())[:10]:
                message += f"<b>🏘️ {rem}</b>\n"
                for addr_info in addresses[:5]:
                    message += f"  • {addr_info['address']}\n"
                if len(addresses) > 5:
