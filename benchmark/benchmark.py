import asyncio
import os
import time
import httpx
from statistics import median, quantiles
import sys

BOT_METRICS_URL = os.environ.get("BOT_METRICS_URL", "http://localhost:8001/metrics")
PROMETHEUS_QUERY_URL = os.environ.get(
    "PROMETHEUS_QUERY_URL", "http://localhost:9090/api/v1/query"
)
ITERATIONS = int(os.environ.get("BENCHMARK_ITERATIONS", "30"))
CONCURRENCY = int(os.environ.get("BENCHMARK_CONCURRENCY", "10"))
TIMEOUT = float(os.environ.get("BENCHMARK_TIMEOUT", "5"))


async def timed_get(client: httpx.AsyncClient, url: str, params: dict | None = None) -> tuple[float, int]:
    start_time = time.perf_counter()
    response = await client.get(url, params=params, timeout=TIMEOUT)
    duration = time.perf_counter() - start_time
    response.raise_for_status()
    return duration, response.status_code


async def run_load_test():
    print(f"Running benchmark with concurrency={CONCURRENCY}, iterations={ITERATIONS}")

    results = {
        "bot_metrics": [],
        "prometheus_health": [],
        "prometheus_query": [],
    }

    sem = asyncio.Semaphore(CONCURRENCY)

    async def worker():
        async with httpx.AsyncClient() as client:
            for _ in range(ITERATIONS):
                async with sem:
                    duration, _ = await timed_get(client, BOT_METRICS_URL)
                    results["bot_metrics"].append(duration)

                    duration, _ = await timed_get(
                        client,
                        PROMETHEUS_QUERY_URL,
                        params={"query": "bot_requests_total"},
                    )
                    results["prometheus_query"].append(duration)

                    duration, _ = await timed_get(client, "http://localhost:9090/-/healthy")
                    results["prometheus_health"].append(duration)

    start_time = time.perf_counter()
    await asyncio.gather(*[worker() for _ in range(CONCURRENCY)])
    total_time = time.perf_counter() - start_time

    print("\n" + "=" * 60)
    print("BENCHMARK RESULTS")
    print("=" * 60)
    print(f"Total time: {total_time:.2f}s")

    for name, latencies in results.items():
        if not latencies:
            continue
        total_requests = len(latencies)
        rps = total_requests / total_time
        p50 = median(latencies)
        p95 = quantiles(latencies, n=100)[94]
        p99 = quantiles(latencies, n=100)[98]
        print(f"\n{name}:")
        print(f"  requests: {total_requests}")
        print(f"  rps: {rps:.2f}")
        print(f"  p50: {p50 * 1000:.2f} ms")
        print(f"  p95: {p95 * 1000:.2f} ms")
        print(f"  p99: {p99 * 1000:.2f} ms")

    await check_prometheus_metrics()


async def check_prometheus_metrics():
    """
    Запрашиваем метрики из Prometheus чтобы проверить что всё работает
    """
    print("\nChecking Prometheus metrics...")
    
    async with httpx.AsyncClient() as client:
        try:
            # bot_requests_total
            response = await client.get(
                PROMETHEUS_QUERY_URL,
                params={"query": "bot_requests_total"}
            )
            data = response.json()
            
            if data["status"] == "success" and data["data"]["result"]:
                print("\nPrometheus metrics:")
                for metric in data["data"]["result"]:
                    handler = metric["metric"].get("handler", "unknown")
                    value = metric["value"][1]
                    print(f"  {handler}: {value}")
            else:
                print("No metrics found in Prometheus")
        
        except Exception as e:
            print(f"Prometheus query failed: {e}")


async def check_services_health():
    """
    Проверяем что все сервисы доступны перед тестом
    """
    print("Checking services...")
    
    services = {
        "Bot metrics": BOT_METRICS_URL,
        "Prometheus": "http://localhost:9090/-/healthy",
    }
    
    async with httpx.AsyncClient() as client:
        for name, url in services.items():
            try:
                response = await client.get(url, timeout=5)
                if response.status_code == 200:
                    print(f"  OK {name}")
                else:
                    print(f"  FAIL {name} (status {response.status_code})")
                    return False
            except Exception as e:
                print(f"  FAIL {name} ({e})")
                return False
    
    print("Services are available\n")
    return True


async def main():
    if not await check_services_health():
        print("\nSome services are unavailable. Start docker compose up")
        sys.exit(1)

    await run_load_test()
    print("\nBenchmark complete")


if __name__ == "__main__":
    asyncio.run(main())
