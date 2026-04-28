# Практика: сравнение типов кеширования

Учебный проект для сравнения трех стратегий кеширования:

- Lazy Loading / Cache-Aside / Write-Around
- Write-Through
- Write-Back

Состав системы:

- `load_generator.py` — генератор нагрузки;
- `app.py` — приложение на Flask;
- `Redis` — кеш;
- `SQLite` — база данных.

## 1. Установка

Нужен Python 3.10+ и Docker.

```bash
pip install -r requirements.txt
docker compose up -d redis
```

## 2. Инициализация БД

```bash
python init_db.py
```

Будет создан файл `data.db` с одинаковым набором данных.

## 3. Запуск приложения

В одном терминале:

```bash
CACHE_STRATEGY=lazy python app.py
```

Возможные стратегии:

```bash
CACHE_STRATEGY=lazy
CACHE_STRATEGY=write-through
CACHE_STRATEGY=write-back
```

На Windows PowerShell:

```powershell
$env:CACHE_STRATEGY="lazy"; python app.py
```

## 4. Запуск тестов

Во втором терминале:

```bash
python load_generator.py --profile read-heavy --requests 1000
python load_generator.py --profile balanced --requests 1000
python load_generator.py --profile write-heavy --requests 1000
```

Профили:

- `read-heavy` = 80% read / 20% write
- `balanced` = 50% read / 50% write
- `write-heavy` = 20% read / 80% write

## 5. Быстрый запуск всех тестов

```bash
python run_all_tests.py
```

Он сам запустит приложение для каждой стратегии и выполнит три профиля нагрузки.

## 6. Где смотреть метрики

После теста генератор выводит:

- throughput, req/sec;
- average latency, ms;
- DB reads;
- DB writes;
- cache hit rate;
- для Write-Back дополнительно: сколько записей ожидает сброса в БД.


