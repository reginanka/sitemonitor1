import requests
from bs4 import BeautifulSoup
import os
import hashlib
import json
from datetime import datetime
import pytz
from playwright.sync_api import sync_playwright
import sys
from io import BytesIO
from PIL import Image

def exception_hook(exctype, value, traceback):
    print(f"❌ Uncaught exception: {value}")
    import traceback as tb
    tb.print_exception(exctype, value, traceback)
    sys.exit(1)

sys.excepthook = exception_hook

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.environ.get('TELEGRAM_CHANNEL_ID')
TELEGRAM_LOG_CHANNEL_ID = os.environ.get('TELEGRAM_LOG_CHANNEL_ID')
URL = os.environ.get('URL')
SUBSCRIBE = os.environ.get('SUBSCRIBE')

UKRAINE_TZ = pytz.timezone('Europe/Kyiv')
log_messages = []

def get_ukraine_time():
    return datetime.now(pytz.utc).astimezone(UKRAINE_TZ)

def log(message):
    print(message)
    ukraine_time = get_ukraine_time()
    log_messages.append(f"{ukraine_time.strftime('%H:%M:%S')} - {message}")

def send_log_to_channel():
    if not TELEGRAM_LOG_CHANNEL_ID or not log_messages:
        return
    try:
        ukraine_time = get_ukraine_time()
        log_text = "📊 <b>ЛОГ ВИКОНАННЯ СКРИПТА</b>\n\n"
        log_text += "<pre>"
        log_text += "\n".join(log_messages)
        log_text += "</pre>"
        log_text += f"\n\n⏰ Завершено: {get_ukraine_time().strftime('%d.%m.%Y %H:%M:%S')} (Київський час)"
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

def get_schedule_content():
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1920, 'height': 3080})
            page.goto(URL, wait_until='networkidle', timeout=30000)
            page_content = page.content()
            browser.close()
            soup = BeautifulSoup(page_content, 'html.parser')
            for br in soup.find_all('br'):
                br.replace_with('\n')
            important_message = None
            update_date = None
            for elem in soup.find_all(['div', 'span', 'p', 'h2', 'h3','h4','h5']):
                text = elem.get_text(strip=False)
                if 'УВАГА' in text and 'ІНФОРМАЦІЯ' in text and important_message is None:
                    lines = [line.strip() for line in text.split('\n') if line.strip()]
                    important_message = '\n'.join(lines)
                    log(f"✅ Знайдено повідомлення УВАГА: {important_message[:100]}...")
                if 'Дата' in text and update_date is None:
                    lines = [line.strip() for line in text.split('\n') if line.strip()]
                    update_date = '\n'.join(lines)
                    log(f"✅ Знайдено дату оновлення: {update_date}")
            if not important_message:
                log("⚠️ Повідомлення УВАГА не знайдено")
            if not update_date:
                log("⚠️ Дата оновлення не знайдена")
            return important_message, update_date
    except Exception as e:
        log(f"❌ Помилка Playwright: {e}")
        return None, None

def take_screenshot_between_elements():
    try:
        log("📸 Створюю скріншот проміжку між елементами...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1920, 'height': 3080})
            page.goto(URL, wait_until='networkidle', timeout=30000)
            date_element = page.locator("text=/Дата оновлення інформації/").first
            end_element = page.locator("text=/робіт/").last
            if date_element.count() == 0:
                log("❌ Не знайдено елемент 'Дата оновлення інформації'")
                browser.close()
                return None, None
            if end_element.count() == 0:
                log("⚠️ Не знайдено слово 'робіт', буде використано висоту всієї сторінки!")
            date_box = date_element.bounding_box()
            end_box = end_element.bounding_box() if end_element.count() > 0 else None
            if not date_box:
                log("❌ Не вдалося отримати координати 'Дата оновлення інформації'")
                browser.close()
                return None, None
            x = 0
            width = 1920
            start_y = date_box['y'] + date_box['height']
            full_screenshot = page.screenshot()
            browser.close()
            image = Image.open(BytesIO(full_screenshot))
            if end_box:
                end_y = end_box['y'] + end_box['height'] + 5
                log(f"📐 Обрізка до слова 'робіт': y={start_y}-{end_y}")
            else:
                end_y = image.height
                log("📐 Обрізка на всю висоту сторінки (робіт не знайдено)")
            height = end_y - start_y
            if height <= 0:
                log("❌ Некоректна висота області для скріншота")
                return None, None
            cropped_image = image.crop((x, start_y, x + width, end_y))
            cropped_image.save('screenshot.png')
            screenshot_hash = hashlib.md5(cropped_image.tobytes()).hexdigest()
            log(f"✅ Скріншот створено. Хеш: {screenshot_hash}")
            return 'screenshot.png', screenshot_hash
    except Exception as e:
        log(f"❌ Помилка створення скріншоту: {e}")
        return None, None

def get_last_data():
    try:
        with open('last_hash.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data
    except:
        log("⚠️ last_hash.json не знайдено (перший запуск)")
        return None

def save_data(message_content, date_content, screenshot_hash):
    hash_message = hashlib.md5(message_content.encode('utf-8')).hexdigest() if message_content else None
    with open('last_hash.json', 'w', encoding='utf-8') as f:
        json.dump({
            'hash_message': hash_message,
            'content_message': message_content,
            'content_date': date_content,
            'screenshot_hash': screenshot_hash,
            'timestamp': datetime.now().isoformat()
        }, f, indent=2, ensure_ascii=False)
    log(f"💾 Дані збережено. Хеш повідомлення: {hash_message}, Хеш скріншота: {screenshot_hash}")

def send_to_channel(message_content, date_content, screenshot_path=None):
    try:
        if screenshot_path and os.path.exists(screenshot_path):
            photo_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
            full_message = f"🔔 ОНОВЛЕННЯ ГРАФІКА ВІДКЛЮЧЕНЬ\n\n"
            full_message += message_content
            full_message += f'\n\n<a href="{URL}">🔗 Переглянути графік на сайті </a>\n\n'
            
            if date_content:
                full_message += f"{date_content}"
            
            if SUBSCRIBE:
                full_message += f'\n\n<a href="{SUBSCRIBE}">⚡ ПІДПИСАТИСЯ ⚡</a>'
            else:
                log("⚠️ SUBSCRIBE не встановлено в змінних оточення!")
            
            with open(screenshot_path, 'rb') as photo:
                files = {'photo': photo}
                data = {
                    'chat_id': TELEGRAM_CHANNEL_ID,
                    'caption': full_message,
                    'parse_mode': 'HTML'
                }
                response = requests.post(photo_url, files=files, data=data, timeout=30)
                if response.status_code == 200:
                    log("✅ Повідомлення відправлено у канал")
                    return True
                else:
                    log(f"❌ Помилка відправки: {response.text}")
                    return False
        else:
            log("⚠️ Скріншот не знайдено")
            return False
    except Exception as e:
        log(f"❌ Помилка відправки: {e}")
        return False

def main():
    log("=" * 50)
    log("🔍 МОНІТОРИНГ ГРАФІКА ВІДКЛЮЧЕНЬ")
    log("=" * 50)
    try:
        message_content, date_content = get_schedule_content()
        if not message_content:
            log("❌ Не вдалося отримати важливе повідомлення")
            return
        screenshot_path, screenshot_hash = take_screenshot_between_elements()
        if not screenshot_path or not screenshot_hash:
            log("❌ Не вдалося створити скріншот або отримати його хеш")
            return
        last_data = get_last_data()
        last_screenshot_hash = last_data.get('screenshot_hash') if last_data else None
        log(f"🔑 Поточний хеш скріншота: {screenshot_hash}")
        log(f"🔑 Попередній хеш скріншота: {last_screenshot_hash}")
        if last_screenshot_hash == screenshot_hash:
            log("✅ Змін у ТАБЛИЦІ ГРАФІКУ немає. Завершення.")
            save_data(message_content, date_content, screenshot_hash)
            return
        log("🔔 ВИЯВЛЕНІ ЗМІНИ У ТАБЛИЦІ ГРАФІКУ!")
        if send_to_channel(message_content, date_content, screenshot_path):
            save_data(message_content, date_content, screenshot_hash)
            log("✅ Успішно! Оновлення відправлено")
        else:
            log("❌ Не вдалося відправити оновлення")
    except Exception as e:
        log(f"❌ Критична помилка: {e}")
    finally:
        send_log_to_channel()

if __name__ == '__main__':
    main()
