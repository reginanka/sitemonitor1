import os
import json
import hashlib
import requests
from datetime import datetime
from pathlib import Path
import logging
from typing import Dict, List, Tuple, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

API_BASE_URL = os.getenv('API_BASE_URL')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')

QUEUES = [(i, j) for i in range(1, 7) for j in range(1, 3)]

DATA_DIR = Path('data')
IMAGES_DIR = Path('images')
DATA_DIR.mkdir(exist_ok=True)
IMAGES_DIR.mkdir(exist_ok=True)

CURRENT_FILE = DATA_DIR / 'current.json'
PREVIOUS_FILE = DATA_DIR / 'previous.json'
HISTORY_FILE = DATA_DIR / 'history.json'
HASH_FILE = DATA_DIR / 'last_hash.json'


def fetch_schedule(cherga_id: int, pidcherga_id: int) -> List[Dict]:
    """Завантажити графік для однієї черги"""
    try:
        params = {'cherga_id': cherga_id, 'pidcherga_id': pidcherga_id}
        response = requests.get(API_BASE_URL, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Помилка {cherga_id}.{pidcherga_id}: {e}")
        return []


def fetch_all_schedules() -> Dict[str, List[Dict]]:
    """Завантажити графіки всіх черг"""
    all_schedules = {}
    logger.info("📡 Завантажую графіки...")
    
    for cherga_id, pidcherga_id in QUEUES:
        queue_key = f"{cherga_id}.{pidcherga_id}"
        schedule = fetch_schedule(cherga_id, pidcherga_id)
        all_schedules[queue_key] = schedule
        logger.info(f"  ✓ {queue_key}: {len(schedule)} записів")
    
    return all_schedules


def parse_time_intervals(schedule: List[Dict]) -> Dict[str, List[Tuple[str, str]]]:
    """Парсити інтервали"""
    intervals_by_date = {}
    
    for entry in schedule:
        date = entry.get('date')
        span = entry.get('span')
        color = entry.get('color')
        
        if not all([date, span, color]):
            continue
        
        if date not in intervals_by_date:
            intervals_by_date[date] = {'red': [], 'white': []}
        
        start_time, end_time = span.split('-')
        intervals_by_date[date][color].append((start_time, end_time))
    
    merged_intervals = {}
    for date, colors in intervals_by_date.items():
        merged_intervals[date] = merge_intervals(colors['red'])
    
    return merged_intervals


def merge_intervals(intervals: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """Об'єднати суміжні інтервали"""
    if not intervals:
        return []
    
    intervals = sorted(intervals, key=lambda x: x[0])
    merged = [intervals[0]]
    
    for start, end in intervals[1:]:
        last_start, last_end = merged[-1]
        if start == last_end:
            merged[-1] = (last_start, end)
        else:
            merged.append((start, end))
    
    return merged


def calculate_duration(start: str, end: str) -> float:
    """Розрахувати тривалість в годинах"""
    start_h, start_m = map(int, start.split(':'))
    end_h, end_m = map(int, end.split(':'))
    
    start_mins = start_h * 60 + start_m
    end_mins = end_h * 60 + end_m
    
    if end_mins < start_mins:
        end_mins += 24 * 60
    
    duration_mins = end_mins - start_mins
    return duration_mins / 60


def get_day_name(date_str: str) -> str:
    """Отримати день тижня"""
    try:
        day, month, year = map(int, date_str.split('.'))
        date = datetime(year, month, day)
        days = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'нд']
        return days[date.weekday()]
    except:
        return "невідомо"


def compare_schedules(current: Dict[str, List[Dict]], previous: Dict[str, List[Dict]]) -> Dict:
    """Порівняти графіки"""
    changes = {}
    
    for queue_key, current_schedule in current.items():
        current_intervals = parse_time_intervals(current_schedule)
        previous_schedule = previous.get(queue_key, [])
        previous_intervals = parse_time_intervals(previous_schedule)
        
        queue_changes = {}
        all_dates = set(current_intervals.keys()) | set(previous_intervals.keys())
        
        for date in all_dates:
            current_times = set(current_intervals.get(date, []))
            previous_times = set(previous_intervals.get(date, []))
            
            added = list(current_times - previous_times)
            removed = list(previous_times - current_times)
            
            if added or removed:
                queue_changes[date] = {
                    'added': sorted(added),
                    'removed': sorted(removed)
                }
        
        if queue_changes:
            changes[queue_key] = queue_changes
    
    return changes


def format_message(changes: Dict, timestamp: str) -> Optional[str]:
    """Форматувати повідомлення"""
    if not changes:
        return None
    
    changed_queues = ', '.join(sorted(changes.keys()))
    message = f"Для груп {changed_queues} - оновлено графік вимкнення світла.\n\n"
    
    for queue_key in sorted(changes.keys()):
        queue_changes = changes[queue_key]
        message += f"за групою {queue_key}:\n"
        
        for date in sorted(queue_changes.keys()):
            day_changes = queue_changes[date]
            day_name = get_day_name(date)
            message += f"  {day_name}, {date}:\n"
            
            for start, end in sorted(day_changes['removed']):
                duration = calculate_duration(start, end)
                message += f"  ❌ {start} - {end} – на {duration:.0f} год\n"
            
            for start, end in sorted(day_changes['added']):
                duration = calculate_duration(start, end)
                message += f"  🔴 {start} - {end} – на {duration:.0f} год\n"
            
            message += "\n"
    
    message += f"Дата оновлення інформації - {timestamp}"
    
    return message


def save_json(data: Dict, filepath: Path):
    """Зберегти JSON"""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(filepath: Path) -> Dict:
    """Завантажити JSON"""
    if not filepath.exists():
        return {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}


def calculate_hash(data: Dict) -> str:
    """Розрахувати хеш"""
    json_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(json_str.encode()).hexdigest()


def load_last_hash() -> Dict:
    """Завантажити останній хеш"""
    return load_json(HASH_FILE)


def save_last_hash(schedules: Dict, timestamp: str):
    """Зберегти хеш"""
    hash_data = {
        'timestamp': timestamp,
        'schedules_hash': calculate_hash(schedules),
        'last_notification': timestamp,
        'queues': {
            queue_key: calculate_hash(schedule) 
            for queue_key, schedule in schedules.items()
        }
    }
    save_json(hash_data, HASH_FILE)


def save_to_history(changes: Dict, timestamp: str):
    """Зберегти в історію"""
    history = load_json(HISTORY_FILE)
    if not isinstance(history, list):
        history = []
    
    history.append({
        'timestamp': timestamp,
        'changes': changes
    })
    
    if len(history) > 100:
        history = history[-100:]
    
    save_json(history, HISTORY_FILE)


def main():
    """Основна функція"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"\n{'='*60}")
    logger.info(f"🚀 СТАРТ [{timestamp}]")
    logger.info(f"{'='*60}\n")
    
    try:
        logger.info("Крок 1: Завантаження графіків...")
        current_schedules = fetch_all_schedules()
        
        if not current_schedules:
            logger.error("❌ Не вдалось завантажити!")
            return
        
        logger.info("\nКрок 2: Перевірка хешу...")
        last_hash_data = load_last_hash()
        current_hash = calculate_hash(current_schedules)
        
        if current_hash == last_hash_data.get('schedules_hash'):
            logger.info("✅ Дані не змінилися.")
            return
        
        logger.info("⚠️  Дані змінилися!")
        
        logger.info("\nКрок 3: Завантаження попередніх...")
        previous_schedules = load_json(PREVIOUS_FILE)
        
        logger.info("\nКрок 4: Порівняння...")
        changes = compare_schedules(current_schedules, previous_schedules)
        
        if changes:
            logger.info(f"✓ Знайдено зміни в {len(changes)} чергах")
            
            logger.info("\nКрок 5: Форматування...")
            message = format_message(changes, timestamp)
            
            if message:
                logger.info(f"Повідомлення готово:\n{message}\n")
                
                logger.info("Крок 6: Збереження історії...")
                save_to_history(changes, timestamp)
                
                logger.info("\nКрок 7: Генерація картинки...")
                image_path = None
                try:
                    from image_generator import generate_image
                    image_path = generate_image(changes, timestamp)
                    logger.info(f"✓ Картинка: {image_path}")
                except Exception as e:
                    logger.warning(f"⚠️  Помилка картинки: {e}")
                
                logger.info("\nКрок 8: Telegram...")
                try:
                    from telegram_handler import send_notification
                    send_notification(message, image_path)
                    logger.info("✓ Telegram OK")
                except Exception as e:
                    logger.error(f"❌ Telegram: {e}")
        else:
            logger.info("✓ Змін не знайдено")
        
        logger.info("\nКрок 9: Збереження...")
        save_json(current_schedules, CURRENT_FILE)
        save_json(current_schedules, PREVIOUS_FILE)
        save_last_hash(current_schedules, timestamp)
        
        logger.info("\n" + "="*60)
        logger.info("✅ ГОТОВО")
        logger.info("="*60 + "\n")
        
    except Exception as e:
        logger.error(f"❌ ПОМИЛКА: {e}", exc_info=True)


if __name__ == '__main__':
    main()
