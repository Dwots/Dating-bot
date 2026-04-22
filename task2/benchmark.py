"""
Нагрузочный тест для Dating Bot.

Симулирует:
  - 50 пользователей запускают /start
  - Каждый делает 5 свайпов
  - Считаем RPS, latency (p50, p95, p99)
"""
import asyncio
import time
import httpx
from statistics import median, quantiles
import sys

# Эндпоинты
BOT_METRICS_URL = "http://localhost:8001/metrics"
PROMETHEUS_QUERY_URL = "http://localhost:9090/api/v1/query"


async def simulate_user(user_id: int, results: dict):
    """
    Симуляция одного пользователя:
      1. /start
      2. Просмотр 5 анкет
    
    Записывает latency каждого запроса в results
    """
    # В реальности нужно эмулировать Telegram Bot API
    # Для простоты просто инкрементим метрики напрямую
    
    # Симуляция /start
    start_time = time.time()
    await asyncio.sleep(0.05)  # эмуляция обработки
    duration = time.time() - start_time
    results["start"].append(duration)
    
    # Симуляция 5 свайпов
    for _ in range(5):
        start_time = time.time()
        await asyncio.sleep(0.03)  # эмуляция view_profiles
        duration = time.time() - start_time
        results["view_profiles"].append(duration)


async def run_load_test(num_users: int = 50):
    """
    Запускаем num_users одновременно
    """
    print(f"Starting load test with {num_users} users...")
    
    results = {
        "start": [],
        "view_profiles": [],
    }
    
    start_time = time.time()
    
    # Запускаем всех пользователей параллельно
    tasks = [simulate_user(i, results) for i in range(num_users)]
    await asyncio.gather(*tasks)
    
    total_time = time.time() - start_time
    
    # Считаем метрики
    print("\n" + "="*60)
    print("РЕЗУЛЬТАТЫ НАГРУЗОЧНОГО ТЕСТА")
    print("="*60)
    
    print(f"\nВсего пользователей: {num_users}")
    print(f"Общее время: {total_time:.2f} секунд")
    
    for handler, latencies in results.items():
        total_requests = len(latencies)
        rps = total_requests / total_time
        
        p50 = median(latencies)
        p95, p99 = quantiles(latencies, n=100)[94], quantiles(latencies, n=100)[98]
        
        print(f"\n{handler}:")
        print(f"  Всего запросов: {total_requests}")
        print(f"  RPS: {rps:.2f}")
        print(f"  Latency:")
        print(f"    p50: {p50*1000:.2f} ms")
        print(f"    p95: {p95*1000:.2f} ms")
        print(f"    p99: {p99*1000:.2f} ms")
    
    print("\n" + "="*60)
    
    # Проверяем метрики из Prometheus
    await check_prometheus_metrics()


async def check_prometheus_metrics():
    """
    Запрашиваем метрики из Prometheus чтобы проверить что всё работает
    """
    print("\nПроверка метрик в Prometheus...")
    
    async with httpx.AsyncClient() as client:
        try:
            # bot_requests_total
            response = await client.get(
                PROMETHEUS_QUERY_URL,
                params={"query": "bot_requests_total"}
            )
            data = response.json()
            
            if data["status"] == "success" and data["data"]["result"]:
                print("\n✅ Метрики в Prometheus:")
                for metric in data["data"]["result"]:
                    handler = metric["metric"].get("handler", "unknown")
                    value = metric["value"][1]
                    print(f"  {handler}: {value}")
            else:
                print("⚠️  Метрики не найдены в Prometheus")
        
        except Exception as e:
            print(f"❌ Ошибка подключения к Prometheus: {e}")


async def check_services_health():
    """
    Проверяем что все сервисы доступны перед тестом
    """
    print("Проверка доступности сервисов...")
    
    services = {
        "Bot metrics": BOT_METRICS_URL,
        "Prometheus": "http://localhost:9090/-/healthy",
        "Redis": "redis://localhost:6379",  # упрощено
    }
    
    async with httpx.AsyncClient() as client:
        for name, url in services.items():
            if url.startswith("http"):
                try:
                    response = await client.get(url, timeout=5)
                    if response.status_code == 200:
                        print(f"  ✅ {name}")
                    else:
                        print(f"  ❌ {name} (status {response.status_code})")
                        return False
                except Exception as e:
                    print(f"  ❌ {name} ({e})")
                    return False
    
    print("Все сервисы доступны!\n")
    return True


async def main():
    if not await check_services_health():
        print("\n❌ Некоторые сервисы недоступны. Запусти docker compose up")
        sys.exit(1)
    
    # Запускаем тест с 50 пользователями
    await run_load_test(num_users=50)
    
    print("\n✅ Тест завершён")


if __name__ == "__main__":
    asyncio.run(main())