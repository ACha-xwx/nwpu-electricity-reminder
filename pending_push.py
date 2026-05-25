import json
from datetime import datetime, timedelta
from pathlib import Path


PENDING_PUSH_FILENAME = "pending_qmsg_notifications.json"
MAX_PENDING_AGE = timedelta(days=2)
MAX_PENDING_ATTEMPTS = 12


def get_pending_push_path(base_dir):
    return Path(base_dir) / PENDING_PUSH_FILENAME


def load_pending_pushes(base_dir):
    path = get_pending_push_path(base_dir)
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def save_pending_pushes(base_dir, items):
    path = get_pending_push_path(base_dir)
    if not items:
        path.unlink(missing_ok=True)
        return

    path.write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def queue_pending_push(base_dir, message, push_config, source, error_message=""):
    path = get_pending_push_path(base_dir)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    items = load_pending_pushes(base_dir)

    provider = push_config.get("provider", "qmsg")
    target = push_config.get("qq") or push_config.get("target") or ""
    signature = f"{provider}|{target}|{message}"

    for item in items:
        if item.get("signature") == signature:
            item["source"] = source
            item["last_error"] = error_message
            item["updated_at"] = now
            save_pending_pushes(base_dir, items)
            return path, False

    items.append(
        {
            "signature": signature,
            "source": source,
            "message": message,
            "push_config": push_config,
            "created_at": now,
            "updated_at": now,
            "attempts": 0,
            "last_error": error_message,
        }
    )
    save_pending_pushes(base_dir, items)
    return path, True


def flush_pending_pushes(base_dir, send_target):
    now = datetime.now()
    pending_items = load_pending_pushes(base_dir)
    remaining_items = []
    delivered_count = 0
    dropped_count = 0

    for item in pending_items:
        created_at_raw = item.get("created_at")
        attempts = int(item.get("attempts", 0))

        created_at = None
        if created_at_raw:
            try:
                created_at = datetime.strptime(created_at_raw, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                created_at = None

        if created_at and now - created_at > MAX_PENDING_AGE:
            dropped_count += 1
            continue
        if attempts >= MAX_PENDING_ATTEMPTS:
            dropped_count += 1
            continue

        try:
            send_target(item["message"], item["push_config"])
            delivered_count += 1
        except Exception as exc:
            item["attempts"] = attempts + 1
            item["last_error"] = str(exc)
            item["updated_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
            remaining_items.append(item)

    save_pending_pushes(base_dir, remaining_items)
    return {
        "delivered": delivered_count,
        "remaining": len(remaining_items),
        "dropped": dropped_count,
        "path": str(get_pending_push_path(base_dir)),
    }
