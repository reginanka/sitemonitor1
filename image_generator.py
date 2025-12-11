import logging
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import json
from typing import Dict

logger = logging.getLogger(__name__)

IMAGES_DIR = Path('images')
IMAGES_DIR.mkdir(exist_ok=True)

# Кольори
COLOR_RED = '#FF4444'
COLOR_REMOVED = '#AAAAAA'
COLOR_GREEN = '#44FF44'
COLOR_BG = '#1E1E2E'  # Темний фон
COLOR_TEXT = '#FFFFFF'
COLOR_TITLE = '#00FF88'
COLOR_DATE = '#FFD700'

# Шрифти
FONT_SIZE_TITLE = 28
FONT_SIZE_NORMAL = 16
FONT_SIZE_SMALL = 14


def generate_image(changes: Dict, timestamp: str) -> Path:
    """
    Генерувати картинку зі змінами графіків
    """
    logger.info("🖼️  Генеруємо картинку...")
    
    # Підготовка тексту
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
            lines.append(f"  {date}:")
            
            # Видалені
            for start, end in sorted(day_changes['removed']):
                lines.append(f"    ❌ {start} - {end}")
            
            # Додані
            for start, end in sorted(day_changes['added']):
                lines.append(f"    🔴 {start} - {end}")
            
            lines.append("")
    
    lines.append(f"Оновлено: {timestamp}")
    
    # Розрахувати розмір картинки
    img_width = 600
    line_height = 28
    padding = 30
    total_height = len(lines) * line_height + padding * 2
    
    # Створити картинку
    img = Image.new('RGB', (img_width, total_height), color=COLOR_BG)
    draw = ImageDraw.Draw(img)
    
    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", FONT_SIZE_TITLE)
        font_normal = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", FONT_SIZE_NORMAL)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", FONT_SIZE_SMALL)
    except:
        # Fallback на стандартні шрифти
        font_title = ImageFont.load_default()
        font_normal = ImageFont.load_default()
        font_small = ImageFont.load_default()
    
    # Малювати текст
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
        
        draw.text((padding, y), line, fill=color, font=font)
        y += line_height
    
    # Зберегти
    filename = f"schedule_changes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    filepath = IMAGES_DIR / filename
    img.save(filepath)
    
    logger.info(f"✓ Картинка збережена: {filepath}")
    return filepath
