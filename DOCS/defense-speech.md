# Текст для защиты: технологии, зачем нужны и где в коде


## PostgreSQL

Технология: PostgreSQL.

Зачем: основная реляционная база данных. Хранит пользователей, анкеты, настройки поиска, фото-метаданные, лайки, скипы, мэтчи, рейтинги и рефералов. Без PostgreSQL бот не мог бы сохранять состояние пользователей и анкет.

Где в коде:

- `docker-compose.yml` — сервис `postgres`;
- `bot/database.py` — SQLAlchemy-модели `User`, `Profile`, `Preference`, `Photo`, `Interaction`, `Match`, `Rating`, `Referral`;
- `bot/profile_service.py` — работа с пользователями, анкетами, фото и рефералами;
- `bot/matching_service.py` — чтение анкет, запись лайков/скипов/мэтчей;
- `admin/main.py` — чтение данных для админки.

## Redis

Технология: Redis.

Зачем: используется не только для Celery. Redis кэширует предварительно отранжированные анкеты, чтобы не делать тяжёлый SQL-запрос на каждый свайп. Также Redis хранит rate-limit счётчики пользователей и используется как backend Celery.

Где в коде:

- `docker-compose.yml` — сервис `redis`;
- `bot/matching_service.py` — `rpop`, `lpush`, `expire`, кэш `profiles_cache:{user_id}`;
- `bot/middleware.py` — rate-limit через `INCR` и `EXPIRE`;
- `workers/celery_app.py` — `backend=REDIS_URL` для Celery.

## Celery

Технология: Celery.

Зачем: фоновые задачи. Рейтинг пользователей пересчитывается не при каждом лайке/скипе, а периодически в фоне. Также Celery отправляет уведомление второму пользователю при мэтче.

Где в коде:

- `docker-compose.yml` — сервисы `celery_worker` и `celery_beat`;
- `workers/celery_app.py` — настройка Celery, очередей и расписания;
- `workers/tasks.py` — задачи `recalculate_ratings`, `notify_match`, `process_like`, `process_skip`;
- `workers/consumer.py` — запускает Celery-задачи после событий RabbitMQ.

## RabbitMQ

Технология: RabbitMQ.

Зачем: брокер сообщений для событий взаимодействия. Бот публикует события `like`, `skip`, `match`, а отдельный consumer читает их и запускает фоновые задачи. Самый полезный текущий сценарий — событие `match`, которое приводит к уведомлению второго пользователя.

Где в коде:

- `docker-compose.yml` — сервис `rabbitmq`;
- `bot/rabbitmq.py` — exchange `dating_events`, очереди `like`, `skip`, `match`, метод `publish`;
- `bot/handlers.py` — публикация `rabbitmq.publish("like")`, `rabbitmq.publish("skip")`, `rabbitmq.publish("match")`;
- `workers/consumer.py` — чтение очередей `match`, `like`, `skip`;
- `workers/tasks.py` — фоновые задачи, которые запускаются после событий.

## MinIO / S3

Технология: MinIO как S3-совместимое хранилище.

Зачем: хранение пользовательских фото. Фото не кладутся в PostgreSQL, чтобы не раздувать БД. В PostgreSQL хранится только `s3_key`, статус модерации и метаданные, а сам файл лежит в MinIO.

Где в коде:

- `docker-compose.yml` — сервис `minio`;
- `bot/minio_client.py` — загрузка, получение и удаление фото;
- `bot/handlers.py` — скачивание фото из Telegram и загрузка в MinIO;
- `bot/database.py` — модель `Photo`, поле `s3_key`;
- `admin/main.py` — превью фото через `s3_client.get_object`.

## Рейтинг

Технология: система рейтинга анкет.

Зачем: чтобы анкеты показывались не случайно, а по итоговому качеству/активности. Рейтинг состоит из `primary_score`, `behavioral_score` и `combined_score`. В подборе используется `combined_score`.

Где в коде:

- `bot/database.py` — таблица `ratings`;
- `workers/tasks.py` — расчёт `primary_score`, `behavioral_score`, `combined_score`;
- `workers/celery_app.py` — запуск пересчёта каждые 30 минут;
- `bot/matching_service.py` — сортировка анкет по `Rating.combined_score`;
- `admin/main.py` и `admin/templates/stats.html` — TOP-10 пользователей по рейтингу.

## SurrealDB

Технология: SurrealDB как графовая база взаимодействий.

Зачем: хранение графовых связей между пользователями: кто кого лайкнул или скипнул. Это удобно для проверки взаимного лайка и исключения уже обработанных анкет.

Где в коде:

- `docker-compose.yml` — сервис `surrealdb`;
- `bot/surreal.py` — подключение, `add_interaction`, `check_mutual_like`, `get_excluded_users`;
- `bot/matching_service.py` — запись лайков/скипов в SurrealDB и проверка взаимности;
- `bot/create_test_user.py` — создание тестовых лайков/скипов/мэтчей в SurrealDB.

## Prometheus

Технология: Prometheus.

Зачем: сбор метрик бота. Позволяет видеть количество запросов, cache hit/miss, публикации RabbitMQ-событий и время обработки.

Где в коде:

- `docker-compose.yml` — сервис `prometheus`;
- `prometheus.yml` — target `bot:8001`;
- `bot/metrics.py` — объявление метрик;
- `bot/main.py` — `start_metrics_server(port=8001)`;
- `bot/handlers.py` — `REQUESTS_TOTAL`, `CACHE_HITS`, `CACHE_MISSES`, `REQUEST_DURATION`;
- `bot/rabbitmq.py` — `RABBITMQ_PUBLISHED`.

## Grafana

Технология: Grafana.

Зачем: визуализация метрик Prometheus. Нужна, чтобы не смотреть сырые метрики руками, а видеть графики и панели.

Где в коде:

- `docker-compose.yml` — сервис `grafana`;
- `grafana_dashboard.json` — dashboard с панелями запросов, cache hit rate, RabbitMQ-событий и p95 latency.

## Structlog / JSON-логирование

Технология: structlog.

Зачем: структурированные JSON-логи с service name, timestamp, уровнем, файлом и строкой. Это удобнее обычных `print`, потому что логи можно фильтровать по сервису и событию.

Где в коде:

- `bot/logger.py` — настройка structlog;
- `bot/main.py` — логирование старта и подключений;
- `bot/handlers.py` — логи пользовательских сценариев и ошибок;
- `bot/matching_service.py` — логи cache hit/miss;
- `bot/rabbitmq.py` — логи публикации событий.

## FastAPI Admin

Технология: FastAPI-админка.

Зачем: управление ботом и модерация. Через админку можно смотреть статистику, пользователей, банить/разбанивать, модерировать фото и смотреть TOP рейтинга.

Где в коде:

- `docker-compose.yml` — сервис `admin`;
- `admin/main.py` — routes админки;
- `admin/templates/index.html` — главная статистика;
- `admin/templates/users.html` — список пользователей и бан/разбан;
- `admin/templates/moderation_photos.html` — модерация фото;
- `admin/templates/stats.html` — подробная статистика и TOP рейтинга.

## Фото-модерация

Технология: ручная модерация пользовательских фото.

Зачем: dating-боту нужна проверка пользовательского контента. Новые фото получают статус `PENDING` и не показываются другим пользователям, пока админ не поставит `APPROVED`.

Где в коде:

- `bot/database.py` — `ModerationStatus`, модель `Photo`;
- `bot/profile_service.py` — добавление pending-фото и подсчёт approved/pending;
- `bot/handlers.py` — загрузка фото пользователем;
- `admin/main.py` — `approve_photo`, `reject_photo`;
- `admin/templates/moderation_photos.html` — интерфейс модерации.

## Rate limit

Технология: rate-limit middleware.

Зачем: защита от спама кнопками и сообщениями. Ограничивает пользователя 30 update за 60 секунд.

Где в коде:

- `bot/middleware.py` — `RateLimitMiddleware`;
- `bot/main.py` — подключение `dp.update.middleware(RateLimitMiddleware(redis_client))`;
- Redis — хранение счётчиков `user:{id}:requests`.

## GitHub Actions CI

Технология: GitHub Actions.

Зачем: автоматическая проверка проекта при push/pull request. Проверяет стиль, синтаксис, docker compose и сборку образов.

Где в коде:

- `.github/workflows/ci.yml` — весь CI pipeline.

## Docker Compose

Технология: Docker Compose.

Зачем: локальное разворачивание всей системы одной командой. Проект состоит из многих сервисов, вручную запускать их неудобно и легко ошибиться.

Где в коде:

- `docker-compose.yml` — все сервисы, порты, env, volumes, healthcheck;
- `bot/Dockerfile` — образ бота;
- `admin/Dockerfile` — образ админки;
- `workers/Dockerfile` — образ worker/consumer;
- `benchmark/Dockerfile` — образ benchmark.

## Benchmark

Технология: собственный benchmark-скрипт.

Зачем: простая проверка производительности endpoint-ов метрик и Prometheus. Показывает RPS, p50, p95, p99.

Где в коде:

- `benchmark/benchmark.py` — логика benchmark;
- `benchmark/Dockerfile` — запуск benchmark;
- `docker-compose.yml` — сервис `benchmark` с profile `test`.

## Реферальная система

Технология: referral links.

Зачем: дополнительный фактор в комбинированном рейтинге. Пользователь может пригласить друга, и это учитывается как `referral_bonus`.

Где в коде:

- `bot/database.py` — таблица `referrals`;
- `bot/handlers.py` — генерация ссылки `t.me/...?...start=ref_...`;
- `bot/profile_service.py` — `process_referral`, `count_referrals`;
- `workers/tasks.py` — `referral_bonus` в формуле `combined_score`.

## Telegram Bot API / aiogram

Технология: aiogram и Telegram Bot API.

Зачем: основной пользовательский интерфейс проекта. Пользователь работает с ботом через Telegram: регистрация, анкета, фото, поиск, лайки, скипы, мэтчи.

Где в коде:

- `bot/main.py` — создание `Bot`, `Dispatcher`, polling;
- `bot/handlers.py` — все Telegram handlers и FSM;
- `bot/keyboards.py` — inline-кнопки;
- `bot/config.py` — `BOT_TOKEN` и proxy.

