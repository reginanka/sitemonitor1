import logging
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

IMAGES_DIR = Path('images')
IMAGES_DIR.mkdir(exist_ok=True)

COLOR_RED = '#FF4444'
COLOR_REMOVED = '#AAAAAA'
COLOR_GREEN = '#44FF44'
COLOR_BG = '#1E1E2E'
COLOR_TEXT = '#FFFFFF'
COLOR_TITLE = '#00FF88'
COLOR_DATE = '#FFD700'

FONT_SIZE_TITLE = 28
FONT_SIZE_NORMAL = 16
FONT_SIZE_SMALL = 14


def get_duration_hours(start: str, end: str) -> float:
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


def load_font(size: int) -> ImageFont.FreeTypeFont:
    """Завантажити шрифт"""
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except:
        try:
            return ImageFont.truetype("C:\\Windows\\Fonts\\arial.ttf", size)
        except:
            return ImageFont.load_default()


def generate_image(changes: Dict, timestamp: str) -> Path:
    """
    Генерувати картинку зі змінами графіків
    """
    logger.info("🖼️  Генеруємо картинку...")
    
    lines = []
    
    changed_queues = ', '.join(sorted(changes.keys()))
    lines.append(f"Для груп {changed_queues} - оновлено графік")
    lines.append("")
    
    for queue_key in sorted(changes.keys()):
        queue_changes = changes[queue_key]
        lines.append(f"Група {queue_key}:")
        lines.append("")
        
        for date in sorted(queue_changes.keys()):
            day_changes = queue_changes[date]
            day_name = get_day_name(date)
            lines.append(f"  {day_name}, {date}:")
            
            for start, end in sorted(day_changes['removed']):
                duration = get_duration_hours(start, end)
                lines.append(f"    ❌ {start} - {end} ({duration:.0f} год)")
            
            for start, end in sorted(day_changes['added']):
                duration = get_duration_hours(start, end)
                lines.append(f"    🔴 {start} - {end} ({duration:.0f} год)")
            
            lines.append("")
    
    lines.append(f"Оновлено: {timestamp}")
    
    img_width = 800
    line_height = 32
    padding = 40
    total_height = len(lines) * line_height + padding * 2
    
    img = Image.new('RGB', (img_width, total_height), color=COLOR_BG)
    draw = ImageDraw.Draw(img)
    
    font_title = load_font(FONT_SIZE_TITLE)
    font_normal = load_font(FONT_SIZE_NORMAL)
    font_small = load_font(FONT_SIZE_SMALL)
    
    y = padding
    for i, line in enumerate(lines):
        color = COLOR_TEXT
        font = font_normal
        
        if i == 0:
            color = COLOR_TITLE
            font = font_title
        elif 'Оновлено' in line:
            color = COLOR_DATE
            font = font_small
        elif '❌' in line:
            color = COLOR_REMOVED
        
        draw.text((padding, y), line, fill=color, font=font)
        y += line_height
    
    filename = f"schedule_changes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    filepath = IMAGES_DIR / filename
    img.save(filepath)
    
    logger.info(f"✓ Картинка збережена: {filepath}")
    return filepath
