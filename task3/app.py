import os
import json
import time
import sqlite3
import threading
from flask import Flask, request, jsonify
import redis

DB_PATH = os.getenv("DB_PATH", "data.db")
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
CACHE_STRATEGY = os.getenv("CACHE_STRATEGY", "lazy").lower()

WRITE_BACK_FLUSH_INTERVAL = float(os.getenv("WRITE_BACK_FLUSH_INTERVAL", "2"))
WRITE_BACK_BATCH_SIZE = int(os.getenv("WRITE_BACK_BATCH_SIZE", "100"))

app = Flask(__name__)

cache = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=True,
)

metrics = {
    "strategy": CACHE_STRATEGY,
    "requests": 0,
    "reads": 0,
    "writes": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "db_reads": 0,
    "db_writes": 0,
    "write_back_flushes": 0,
    "write_back_items_flushed": 0,
    "write_back_pending": 0,
}

metrics_lock = threading.Lock()


def inc(name, value=1):
    with metrics_lock:
        metrics[name] += value


def set_metric(name, value):
    with metrics_lock:
        metrics[name] = value


def get_db_connection():
    return sqlite3.connect(DB_PATH)


def db_get_item(item_id: int):
    inc("db_reads")

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT value FROM items WHERE id = ?", (item_id,))
    row = cur.fetchone()
    conn.close()

    if row is None:
        return None

    return {"id": item_id, "value": row[0]}


def db_write_item(item_id: int, value: str):
    inc("db_writes")

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO items (id, value) VALUES (?, ?) "
        "ON CONFLICT(id) DO UPDATE SET value = excluded.value",
        (item_id, value),
    )
    conn.commit()
    conn.close()


def cache_key(item_id: int):
    return f"item:{item_id}"


def cache_get_item(item_id: int):
    raw = cache.get(cache_key(item_id))

    if raw is None:
        inc("cache_misses")
        return None

    inc("cache_hits")
    return json.loads(raw)


def cache_set_item(item_id: int, value: str):
    item = {"id": item_id, "value": value}
    cache.set(cache_key(item_id), json.dumps(item))


def write_back_queue_key():
    return "write_back_queue"


def write_back_put(item_id: int, value: str):
    record = json.dumps({"id": item_id, "value": value})
    cache.rpush(write_back_queue_key(), record)
    set_metric("write_back_pending", cache.llen(write_back_queue_key()))


def write_back_flush_loop():
    while True:
        time.sleep(WRITE_BACK_FLUSH_INTERVAL)

        if CACHE_STRATEGY != "write-back":
            continue

        flushed = 0

        while flushed < WRITE_BACK_BATCH_SIZE:
            raw = cache.lpop(write_back_queue_key())

            if raw is None:
                break

            item = json.loads(raw)
            db_write_item(item["id"], item["value"])
            flushed += 1

        if flushed > 0:
            inc("write_back_flushes")
            inc("write_back_items_flushed", flushed)

        set_metric("write_back_pending", cache.llen(write_back_queue_key()))


@app.before_request
def before_request():
    inc("requests")


@app.route("/item/<int:item_id>", methods=["GET"])
def get_item(item_id):
    inc("reads")

    # Во всех стратегиях чтение сначала идет через кеш.
    item = cache_get_item(item_id)

    if item is not None:
        return jsonify(item)

    # Если в кеше нет, читаем из БД и кладем в кеш.
    item = db_get_item(item_id)

    if item is None:
        return jsonify({"error": "not found"}), 404

    cache_set_item(item_id, item["value"])
    return jsonify(item)


@app.route("/item/<int:item_id>", methods=["POST"])
def update_item(item_id):
    inc("writes")

    body = request.get_json(force=True)
    value = body.get("value")

    if value is None:
        return jsonify({"error": "value is required"}), 400

    if CACHE_STRATEGY == "lazy":
        # Lazy / Cache-Aside / Write-Around:
        # запись сразу в БД, кеш очищается для этого ключа.
        db_write_item(item_id, value)
        cache.delete(cache_key(item_id))

    elif CACHE_STRATEGY == "write-through":
        # Write-Through:
        # запись сразу и в БД, и в кеш.
        db_write_item(item_id, value)
        cache_set_item(item_id, value)

    elif CACHE_STRATEGY == "write-back":
        # Write-Back:
        # запись сначала в кеш, а в БД позже фоновым потоком.
        cache_set_item(item_id, value)
        write_back_put(item_id, value)

    else:
        return jsonify({"error": f"unknown strategy: {CACHE_STRATEGY}"}), 500

    return jsonify({"id": item_id, "value": value, "strategy": CACHE_STRATEGY})


@app.route("/metrics", methods=["GET"])
def get_metrics():
    with metrics_lock:
        result = dict(metrics)

    total_cache_requests = result["cache_hits"] + result["cache_misses"]
    if total_cache_requests == 0:
        result["cache_hit_rate"] = 0
    else:
        result["cache_hit_rate"] = round(result["cache_hits"] / total_cache_requests, 4)

    if CACHE_STRATEGY == "write-back":
        result["write_back_pending"] = cache.llen(write_back_queue_key())

    return jsonify(result)


@app.route("/reset", methods=["POST"])
def reset():
    cache.flushdb()

    with metrics_lock:
        for key in metrics:
            if key == "strategy":
                metrics[key] = CACHE_STRATEGY
            else:
                metrics[key] = 0

    return jsonify({"status": "reset", "strategy": CACHE_STRATEGY})


if __name__ == "__main__":
    print("=" * 60)
    print(f"Starting app with CACHE_STRATEGY={CACHE_STRATEGY}")
    print("Available strategies: lazy, write-through, write-back")
    print("=" * 60)

    flush_thread = threading.Thread(target=write_back_flush_loop, daemon=True)
    flush_thread.start()

    app.run(host="127.0.0.1", port=5000, debug=False)
