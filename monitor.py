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
        log_to_buffer(f" ✓ {queue_key}: {len(schedule)} записів{error_note}")

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
    Dict[str, List[Dict]], # norm_by_queue
    Dict[str, str], # main_hashes
    Dict[str, Dict[str, Dict[str, str]]] # span_hashes[queue][date][span]
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
        main_hash
