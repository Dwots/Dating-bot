import argparse
import random
import time
import statistics
import requests

BASE_URL = "http://127.0.0.1:5000"

PROFILES = {
    "read-heavy": 0.8,
    "balanced": 0.5,
    "write-heavy": 0.2,
}


def reset_app():
    requests.post(f"{BASE_URL}/reset", timeout=5)


def get_metrics():
    response = requests.get(f"{BASE_URL}/metrics", timeout=5)
    response.raise_for_status()
    return response.json()


def send_read(item_id):
    response = requests.get(f"{BASE_URL}/item/{item_id}", timeout=5)
    response.raise_for_status()


def send_write(item_id, value):
    response = requests.post(
        f"{BASE_URL}/item/{item_id}",
        json={"value": value},
        timeout=5,
    )
    response.raise_for_status()


def run_test(profile, requests_count, items_count):
    read_probability = PROFILES[profile]

    reset_app()

    latencies_ms = []
    errors = 0

    start = time.perf_counter()

    for i in range(requests_count):
        item_id = random.randint(1, items_count)
        is_read = random.random() < read_probability

        req_start = time.perf_counter()

        try:
            if is_read:
                send_read(item_id)
            else:
                send_write(item_id, f"updated_{profile}_{i}")
        except Exception:
            errors += 1

        req_end = time.perf_counter()
        latencies_ms.append((req_end - req_start) * 1000)

    end = time.perf_counter()

    duration_sec = end - start
    throughput = requests_count / duration_sec
    avg_latency = statistics.mean(latencies_ms)

    # Даем write-back немного времени на фоновую запись.
    time.sleep(3)

    app_metrics = get_metrics()

    result = {
        "profile": profile,
        "requests": requests_count,
        "duration_sec": round(duration_sec, 3),
        "throughput_req_sec": round(throughput, 2),
        "avg_latency_ms": round(avg_latency, 2),
        "errors": errors,
        "db_reads": app_metrics["db_reads"],
        "db_writes": app_metrics["db_writes"],
        "cache_hits": app_metrics["cache_hits"],
        "cache_misses": app_metrics["cache_misses"],
        "cache_hit_rate": app_metrics["cache_hit_rate"],
        "write_back_pending": app_metrics.get("write_back_pending", 0),
        "write_back_flushes": app_metrics.get("write_back_flushes", 0),
        "write_back_items_flushed": app_metrics.get("write_back_items_flushed", 0),
    }

    return result


def print_result(result):
    print("\n" + "=" * 70)
    print(f"Profile: {result['profile']}")
    print("=" * 70)
    print(f"Requests:              {result['requests']}")
    print(f"Duration, sec:         {result['duration_sec']}")
    print(f"Throughput, req/sec:   {result['throughput_req_sec']}")
    print(f"Avg latency, ms:       {result['avg_latency_ms']}")
    print(f"Errors:                {result['errors']}")
    print(f"DB reads:              {result['db_reads']}")
    print(f"DB writes:             {result['db_writes']}")
    print(f"Cache hits:            {result['cache_hits']}")
    print(f"Cache misses:          {result['cache_misses']}")
    print(f"Cache hit rate:        {result['cache_hit_rate']}")
    print(f"Write-back pending:    {result['write_back_pending']}")
    print(f"Write-back flushes:    {result['write_back_flushes']}")
    print(f"Write-back flushed:    {result['write_back_items_flushed']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=PROFILES.keys(), required=True)
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--items", type=int, default=1000)
    args = parser.parse_args()

    result = run_test(args.profile, args.requests, args.items)
    print_result(result)


if __name__ == "__main__":
    main()
