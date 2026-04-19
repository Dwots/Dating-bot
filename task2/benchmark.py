"""
Запуск:
  pip install pika redis
  docker-compose up -d
  python benchmark.py

Что делает:
  - прогоняет тесты для RabbitMQ и Redis
  - разные размеры сообщений: 128B, 1KB, 10KB, 100KB
  - разные нагрузки: 1000, 5000, 10000 msg/s
  - считает: скорость, latency avg/p95/max, потери
  - печатает итоговую таблицу
"""

import time
import json
import threading
import pika
import redis

QUEUE = "bench"

SIZES = [128, 1024, 10240, 102400]
RATES = [1000, 5000, 10000]
DURATION = 20


class ConsumerStats:
    def __init__(self):
        self.received = 0
        self.latencies = []   # список задержек в мс
        self.done = False     # флаг остановки


def redis_consumer(stats: ConsumerStats):
    r = redis.Redis(host='localhost', port=6379)
    while not stats.done or r.llen(QUEUE) > 0:
        result = r.blpop(QUEUE, timeout=1)
        if result:
            _, body = result
            msg = json.loads(body)
            # считаем задержку от момента отправки до получения
            latency_ms = (time.time() - msg["ts"]) * 1000
            stats.latencies.append(latency_ms)
            stats.received += 1


def rabbit_consumer(stats: ConsumerStats):
    conn = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
    ch = conn.channel()
    ch.queue_declare(queue=QUEUE)
    ch.basic_qos(prefetch_count=200)

    def callback(ch, method, props, body):
        msg = json.loads(body)
        latency_ms = (time.time() - msg["ts"]) * 1000
        stats.latencies.append(latency_ms)
        stats.received += 1
        ch.basic_ack(delivery_tag=method.delivery_tag)

    ch.basic_consume(queue=QUEUE, on_message_callback=callback)

    # крутим цикл пока producer не закончил И очередь не пуста
    while not stats.done or ch.get_waiting_message_count() is None:
        conn.process_data_events(time_limit=0.1)
        if stats.done:
            # проверяем что в очереди ничего нет
            q = ch.queue_declare(queue=QUEUE, passive=True)
            if q.method.message_count == 0:
                break

    conn.close()



def run_test(broker: str, msg_size: int, target_rate: int) -> dict:
    payload = "x" * msg_size       # payload нужного размера
    interval = 1.0 / target_rate   # пауза между сообщениями для throttling
    stats = ConsumerStats()

    # Запускаем consumer в отдельном потоке
    consumer_fn = redis_consumer if broker == "redis" else rabbit_consumer
    t = threading.Thread(target=consumer_fn, args=(stats,), daemon=True)
    t.start()

    # Подключаем producer
    if broker == "redis":
        conn = redis.Redis(host='localhost', port=6379)
    else:
        pika_conn = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
        ch = pika_conn.channel()
        ch.queue_declare(queue=QUEUE)

    sent = 0
    errors = 0
    deadline = time.time() + DURATION

    while time.time() < deadline:
        loop_start = time.time()

        # Сообщение: timestamp нужен для расчёта latency в consumer
        msg = json.dumps({"ts": time.time(), "data": payload})

        try:
            if broker == "redis":
                conn.rpush(QUEUE, msg)
            else:
                ch.basic_publish(exchange='', routing_key=QUEUE, body=msg)
            sent += 1
        except Exception:
            errors += 1

        # Throttling: ждём остаток интервала
        spent = time.time() - loop_start
        wait = interval - spent
        if wait > 0:
            time.sleep(wait)

    # Закрываем producer
    if broker != "redis":
        pika_conn.close()

    # Говорим consumer что producer закончил и ждём его
    stats.done = True
    t.join(timeout=15)

    # Считаем метрики
    lats = sorted(stats.latencies)
    avg_lat = sum(lats) / len(lats) if lats else 0
    p95_lat = lats[int(len(lats) * 0.95)] if lats else 0
    max_lat = lats[-1] if lats else 0
    loss = sent - stats.received
    loss_pct = round(loss / sent * 100, 1) if sent > 0 else 0

    return {
        "broker":   broker,
        "size":     msg_size,
        "rate":     target_rate,
        "sent":     sent,
        "received": stats.received,
        "loss_pct": loss_pct,
        "avg_ms":   round(avg_lat, 1),
        "p95_ms":   round(p95_lat, 1),
        "max_ms":   round(max_lat, 1),
        "real_rate": round(sent / DURATION),
    }



def clear_queues():
    try:
        r = redis.Redis(host='localhost', port=6379)
        r.delete(QUEUE)
    except Exception:
        pass
    try:
        conn = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
        ch = conn.channel()
        ch.queue_purge(QUEUE)
        conn.close()
    except Exception:
        pass


def print_table(results: list):
    header = (f"{'BROKER':<10} {'SIZE':>7} {'TARGET':>7} {'REAL':>7} "
              f"{'SENT':>7} {'RECV':>7} {'LOSS%':>6} "
              f"{'AVG ms':>8} {'P95 ms':>8} {'MAX ms':>8}")
    sep = "─" * len(header)

    print(f"\n{sep}")
    print(header)
    print(sep)

    prev_broker = None
    for r in results:
        # Разделитель между брокерами
        if prev_broker and r["broker"] != prev_broker:
            print(sep)
        prev_broker = r["broker"]

        size_str = (f"{r['size']}B" if r['size'] < 1024
                    else f"{r['size']//1024}KB")

        # Помечаем строки где начинается деградация
        flag = " ← деградация" if r["loss_pct"] > 5 or r["p95_ms"] > 100 else ""

        print(f"{r['broker']:<10} {size_str:>7} {r['rate']:>7} {r['real_rate']:>7} "
              f"{r['sent']:>7} {r['received']:>7} {r['loss_pct']:>6} "
              f"{r['avg_ms']:>8} {r['p95_ms']:>8} {r['max_ms']:>8}{flag}")

    print(sep)


if __name__ == "__main__":
    results = []

    total = len(["redis", "rabbitmq"]) * len(SIZES) * len(RATES)
    current = 0

    for broker in ["redis", "rabbitmq"]:
        for size in SIZES:
            for rate in RATES:
                current += 1
                size_str = f"{size}B" if size < 1024 else f"{size//1024}KB"
                print(f"\n[{current}/{total}] {broker} | {size_str} | {rate} msg/s ...")

                clear_queues()
                # time.sleep(2)  # небольшая пауза между тестами

                result = run_test(broker, size, rate)
                results.append(result)

                print(f"  sent={result['sent']} recv={result['received']} "
                      f"loss={result['loss_pct']}% "
                      f"avg={result['avg_ms']}ms p95={result['p95_ms']}ms")

    print_table(results)