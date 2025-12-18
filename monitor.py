import os
import json
import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
PREVIOUS_FILE = DATA_DIR / "previous.json"
HASH_FILE = DATA_DIR / "last_hash.json"


def fetch_schedule(cherga_id: int, pidcherga_id: int) -> Tuple[List[Dict], bool]:
    """
    Тягне графік для однієї черги.
    Повертає (дані, is_error).
    """
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
            return data, False

        log_to_buffer(f"⚠️ Відповідь не список для {cherga_id}.{pidcherga_id}")
        return [], False

    except Exception as e:
        body = resp.text[:200] if resp is not None else ""
        log_to_buffer(
            f"❌ Помилка {cherga_id}.{pidcherga_id}: {e}. "
            f"Фрагмент відповіді: {body}"
        )
        return [], True


def fetch_all_schedules() -> Tuple[Dict[str, List[Dict]], Dict[str, bool]]:
    """Повертає (дані, словник помилок)."""
    all_schedules: Dict[str, List[Dict]] = {}
    has_error: Dict[str, bool] = {}
    log_to_buffer("📡 Завантажую графіки по всіх чергах...")

    for cherga_id, pidcherga_id in QUEUES:
        queue_key = f"{cherga_id}.{pidcherga_id}"
        schedule, is_error = fetch_schedule(cherga_id, pidcherga_id)
        all_schedules[queue_key] = schedule
        has_error[queue_key] = is_error
        error_note = " [помилка API]" if is_error else ""
        log_to_buffer(f"  ✓ {queue_key}: {len(schedule)} записів{error_note}")

    return all_schedules, has_error


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


def normalize_record(rec: Dict, cherga_id: int, pidcherga_id: int) -> Dict:
    """Нормалізація одного запису."""
    date = rec.get("date", "")
    span = rec.get("span", "")
    color = rec.get("color", "").strip().lower()
    return {
        "cherga": cherga_id,
        "pidcherga": pidcherga_id,
        "queue_key": f"{cherga_id}.{pidcherga_id}",
        "date": date,
        "span": span,
        "color": color,
    }


def build_state(
    raw_schedules: Dict[str, List[Dict]],
    has_error: Dict[str, bool],
) -> Tuple[
    Dict[str, List[Dict]],                    # norm_by_queue
    Dict[str, str],                           # main_hashes
    Dict[str, Dict[str, Dict[str, str]]]      # span_hashes[queue][date][span]
]:
    """
    Будує нормалізований стан з хешами по інтервалах.
    """
    norm_by_queue: Dict[str, List[Dict]] = {}
    main_hashes: Dict[str, str] = {}
    span_hashes: Dict[str, Dict[str, Dict[str, str]]] = {}

    for queue_key, schedule in raw_schedules.items():
        if has_error.get(queue_key, False):
            continue

        cherga_id, pidcherga_id = map(int, queue_key.split("."))
        norm_list: List[Dict] = []

        for rec in schedule:
            nrec = normalize_record(rec, cherga_id, pidcherga_id)
            norm_list.append(nrec)

        norm_list.sort(key=lambda r: (r["date"], r["span"]))
        norm_by_queue[queue_key] = norm_list

        # Головний хеш черги — від color кожного інтервалу
        main_hash_data = [{"date": r["date"], "span": r["span"], "color": r["color"]} for r in norm_list]
        main_hashes[queue_key] = calculate_hash(main_hash_data)

        # Хеші по кожному інтервалу
        sh: Dict[str, Dict[str, str]] = {}
        for rec in norm_list:
            d = rec["date"]
            span = rec["span"]
            if d not in sh:
                sh[d] = {}
            sh[d][span] = calculate_hash({"color": rec["color"]})
        
        span_hashes[queue_key] = sh

    return norm_by_queue, main_hashes, span_hashes


def load_last_state():
    """Завантажує хеші з last_hash.json + дані з previous.json"""
    hash_data = load_json(HASH_FILE)
    prev_norm = load_json(PREVIOUS_FILE)
    
    return {
        "timestamp": hash_data.get("timestamp"),
        "main_hashes": hash_data.get("main_hashes", {}),
        "span_hashes": hash_data.get("span_hashes", {}),
        "norm_by_queue": prev_norm,
    }


def save_state(
    main_hashes: Dict[str, str],
    span_hashes: Dict[str, Dict[str, Dict[str, str]]],
    timestamp: str
) -> None:
    """Зберігає тільки хеші в last_hash.json"""
    data = {
        "timestamp": timestamp,
        "main_hashes": main_hashes,
        "span_hashes": span_hashes,
    }
    save_json(data, HASH_FILE)

def parse_span(span: str) -> Tuple[str, str]:
    """0000-0030 або 00:00-00:30 -> (00:00, 00:30)"""
    if not span or "-" not in span:
        return ("", "")
    start, end = span.split("-")
    # Якщо вже є двокрапка, повертаємо як є
    if ":" in start:
        return start, end
    return f"{start[:2]}:{start[2:]}", f"{end[:2]}:{end[2:]}"

def group_spans(spans_changes: List[Dict]) -> List[Dict]:
    """Групує сусідні інтервали з однаковим типом зміни."""
    result: List[Dict] = []
    current: Optional[Dict] = None

    for item in sorted(spans_changes, key=lambda x: x["span"]):
        start_time, end_time = parse_span(item["span"])
        if not current:
            current = {
                "start": start_time,
                "end": end_time,
                "change": item["change"],
            }
        else:
            if current["change"] == item["change"] and current["end"] == start_time:
                current["end"] = end_time
            else:
                result.append(current)
                current = {
                    "start": start_time,
                    "end": end_time,
                    "change": item["change"],
                }

    if current:
        result.append(current)
    return result


def build_diff(
    norm_by_queue: Dict[str, List[Dict]],
    main_hashes: Dict[str, str],
    span_hashes: Dict[str, Dict[str, Dict[str, str]]],
    last_state: Dict,
) -> Dict:
    last_main = last_state.get("main_hashes", {})
    last_span = last_state.get("span_hashes", {})
    last_norm = last_state.get("norm_by_queue", {})

    diff = {
        "queues": [],
        "per_queue": {},
    }

    for queue_key, cur_main_hash in main_hashes.items():
        old_main_hash = last_main.get(queue_key)
        
        if old_main_hash is None:
            log_to_buffer(f"ℹ️ Перший запуск для {queue_key}, пропускаємо")
            continue
        
        if old_main_hash == cur_main_hash:
            continue

        # Є зміни — шукаємо деталі
        log_to_buffer(f"🔍 Аналізую зміни для {queue_key}")
        cur_sh = span_hashes.get(queue_key, {})
        old_sh = last_span.get(queue_key, {})
        
        if not old_sh:
            log_to_buffer(f"ℹ️ Немає попередніх span_hashes для {queue_key}, пропускаємо")
            continue

        new_dates = sorted(d for d in cur_sh.keys() if d not in old_sh)
        if new_dates:
            log_to_buffer(f"  📅 Нові дати: {new_dates}")
        
        changed_dates = {}

        cur_items = norm_by_queue.get(queue_key, [])
        old_items_list = last_norm.get(queue_key, [])

        for d in cur_sh.keys():
            if d in new_dates:
                continue
            
            # Порівнюємо хеші інтервалів для цієї дати
            cur_spans = cur_sh.get(d, {})
            old_spans = old_sh.get(d, {})
            
            changes_for_date = []
            
            for span, cur_span_hash in cur_spans.items():
                old_span_hash = old_spans.get(span)
                if old_span_hash == cur_span_hash:
                    continue
                
                # Хеш інтервалу змінився
                log_to_buffer(f"  🔄 Інтервал {span} дата {d}: хеш змінився")
                
                # Знаходимо старий і новий запис
                new_rec = next((r for r in cur_items if r["date"] == d and r["span"] == span), None)
                old_rec = next((r for r in old_items_list if r["date"] == d and r["span"] == span), None)
                
                if new_rec and old_rec:
                    log_to_buffer(f"    Старий: color={old_rec['color']}, Новий: color={new_rec['color']}")
                    if new_rec["color"] != old_rec["color"]:
                        change = "added" if new_rec["color"] == "red" else "removed"
                        changes_for_date.append({"span": span, "change": change})
                        log_to_buffer(f"    ✅ Зміна: {change}")
                else:
                    log_to_buffer(f"    ⚠️ Не знайдено запис: new_rec={bool(new_rec)}, old_rec={bool(old_rec)}")

            if changes_for_date:
                grouped = group_spans(changes_for_date)
                changed_dates[d] = grouped
                log_to_buffer(f"  ✅ Для дати {d} знайдено {len(changes_for_date)} змін")

        if new_dates or changed_dates:
            diff["queues"].append(queue_key)
            diff["per_queue"][queue_key] = {
                "new_dates": new_dates,
                "changed_dates": changed_dates,
            }
            log_to_buffer(f"✅ Додано {queue_key} до diff")
        else:
            log_to_buffer(f"⚠️ Хеш змінився для {queue_key}, але конкретні зміни не виявлені")

    return diff


def build_notification_text(diff: Dict, url: str, subscribe: str, update_str: str) -> str:
    queues = sorted(diff["queues"])
    any_new = False
    any_changed = False
    
    # Спочатку перевіряємо типи змін
    for q in queues:
        info = diff["per_queue"].get(q, {})
        if info.get("new_dates"):
            any_new = True
        if info.get("changed_dates"):
            any_changed = True
    
    # Формуємо заголовок
    if any_changed and any_new:
        title = f"Для черг {', '.join(queues)} 🔔 ОНОВЛЕННЯ ГРАФІКА ВІДКЛЮЧЕНЬ + доданий графік на завтра!"
    elif any_changed:
        title = f"Для черг {', '.join(queues)} 🔔 ОНОВЛЕННЯ ГРАФІКА ВІДКЛЮЧЕНЬ"
    elif any_new:
        title = "🔔Додано новий графік на завтра!"
    else:
        title = ""
    
    parts: List[str] = []
    if title:
        parts.append(title)
        parts.append("⬇️⬇️⬇️")
    
    # Групуємо зміни по чергах
    queue_blocks: List[str] = []
    for q in queues:
        info = diff["per_queue"].get(q, {})
        queue_lines: List[str] = []
        
        # Додаємо всі зміни для цієї черги
        for d, ranges in sorted(info.get("changed_dates", {}).items()):
            for r in ranges:
                action = "🪫додали відключення ❌" if r["change"] == "added" else "🔋скасували відключення💡"
                queue_lines.append(f" {d} {r['start']}-{r['end']} {action}")
        
        # Якщо є зміни для черги, додаємо блок
        if queue_lines:
            queue_block = f"▶️ Черга {q}:\n" + "\n".join(queue_lines)
            queue_blocks.append(queue_block)
    
    if queue_blocks:
        parts.append("\n\n".join(queue_blocks))
    
    parts.append(f'<a href="{URL}">🔗 Переглянути графік на сайті </a>')
    
    if update_str:
        parts.append(update_str)
    
    parts.append(f'<a href="{SUBSCRIBE}">⚡ ПІДПИСАТИСЯ ⚡</a>')
    
    return "\n\n".join(parts)



def main():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_to_buffer("=" * 60)
    log_to_buffer(f"🚀 СТАРТ [{timestamp}]")
    log_to_buffer("=" * 60)

    try:
        # 1. Завантажити графіки з API
        current_schedules, has_error = fetch_all_schedules()
        if not current_schedules:
            log_to_buffer("❌ Не вдалось завантажити жоден графік")
            return

        # 2. Побудувати поточний стан
        norm_by_queue, current_main_hashes, current_span_hashes = build_state(
            current_schedules, has_error
        )
        log_to_buffer(f"🔐 Витягнено хеші для {len(current_main_hashes)} черг")

        # 3. Зберегти поточні нормалізовані дані
        # Спочатку копіюємо current → previous
        if CURRENT_FILE.exists():
            shutil.copy(CURRENT_FILE, PREVIOUS_FILE)
            log_to_buffer("📋 Попередній current.json скопійовано в previous.json")
        
        save_json(norm_by_queue, CURRENT_FILE)
        log_to_buffer("💾 Нормалізовані дані збережено в data/current.json")

        # 4. Завантажити попередній стан
        last_state = load_last_state()
        log_to_buffer("📋 Завантажено попередній стан")

        # 5. Побудувати diff
        diff = build_diff(norm_by_queue, current_main_hashes, current_span_hashes, last_state)

        if not diff["queues"]:
            log_to_buffer("✅ Дані по всіх чергах не змінилися")
            save_state(current_main_hashes, current_span_hashes, timestamp)
            return

        log_to_buffer(f"🔔 Зміни виявлено для: {', '.join(diff['queues'])}")

        # 6. Отримати дату оновлення з сайту
        _, date_content = get_schedule_content()

        # 7. Скріншот із сайту
        screenshot_path, screenshot_hash = take_screenshot_between_elements()
        if not screenshot_path:
            log_to_buffer("⚠️ Не вдалося створити скріншот")

        # 8. Формування повідомлення
        final_message = build_notification_text(
            diff,
            URL,
            SUBSCRIBE,
            date_content or "",
        )
 
        # 9. Відправити в Telegram
        from pathlib import Path as _Path
        img_path = _Path(screenshot_path) if screenshot_path else None
        ok = send_notification(final_message, img_path)
        if ok:
            log_to_buffer("✅ Повідомлення з оновленням відправлено в канал")
        else:
            log_to_buffer("❌ Помилка надсилання повідомлення в канал")

        # 10. Оновити тільки хеші
        save_state(current_main_hashes, current_span_hashes, timestamp)
        log_to_buffer("💾 Хеші оновлено в data/last_hash.json")

    except Exception as e:
        log_to_buffer(f"❌ Критична помилка: {e}")
    finally:
        send_log_to_channel()
        log_to_buffer("🏁 Завершення роботи скрипта")


if __name__ == "__main__":
    main()
