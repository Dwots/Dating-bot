# Полная проверка бота

Этот файл нужен для ручной проверки проекта перед демонстрацией: от чистого пересоздания Docker-окружения до заполнения базы тестовыми анкетами и проверки основных функций.

## 0. Что понадобится

- Заполненный `.env` с `BOT_TOKEN`.
- Telegram-аккаунт, с которого можно открыть бота через `/start`.
- Твой `telegram_id`. Его можно увидеть в логах после `/start` или узнать через любого Telegram user info бота.

Полезные адреса:

- Бот: в Telegram.
- Админка: http://localhost:8080
- MinIO: http://localhost:9001, логин `minioadmin`, пароль `minioadmin`
- RabbitMQ: http://localhost:15672, логин `guest`, пароль `guest`
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000, логин `admin`, пароль `admin`

## 1. Полное пересоздание окружения

Осторожно: команда с `-v` удаляет Docker volumes проекта. Будут удалены профили, фото в MinIO, Redis/RabbitMQ/Grafana/Prometheus данные и SurrealDB-граф.

```bash
docker compose down -v
docker compose up -d --build
```

Проверить, что сервисы поднялись:

```bash
docker compose ps
docker compose logs --tail=80 bot
docker compose logs --tail=80 surrealdb
```

Ожидаемый результат:

- `postgres`, `redis`, `rabbitmq`, `minio`, `surrealdb` имеют статус `healthy`.
- `bot`, `admin`, `celery_worker`, `celery_beat`, `match_consumer`, `prometheus`, `grafana` находятся в `Up`.
- В логах бота есть `SurrealDB connected`, `bot_starting`, `Start polling`.
- В логах SurrealDB есть `Started surrealkv kvs store` и `Started web server`.

Предупреждение RabbitMQ про `global_qos is deprecated` не считается ошибкой запуска.

## 2. Проверка пустого состояния

Открыть бота и отправить:

```text
/start
```

Ожидаемый результат:

- Бот отвечает главным меню.
- Если анкеты нет, предлагает заполнить профиль.
- В логах нет traceback.

Админка:

```text
http://localhost:8080
```

Ожидаемый результат:

- Главная страница открывается.
- `/moderation/photos` открывается без `404`.

## 3. Заполнение своей анкеты

В Telegram пройти создание анкеты:

- имя;
- возраст;
- пол;
- город;
- описание;
- интересы;
- загрузить 1-5 фото.

Если фото загружено обычным пользователем, оно должно попасть на ручную модерацию и не отображаться в профиле до одобрения.

Открыть:

```text
http://localhost:8080/moderation/photos
```

Одобрить фото.

Ожидаемый результат:

- После одобрения фото появляется в анкете.
- Если фото не одобрено, оно не показывается в профиле и в просмотре анкет.
- Старые одобренные фото продолжают работать, даже если добавлены новые pending-фото.

## 4. Создание тестовых пользователей

Вместо ручного создания многих людей можно использовать скрипт:

```bash
docker compose exec bot python create_test_user.py --photos 5 --gender female --city Москва
docker compose exec bot python create_test_user.py --photos 4 --gender male --city Москва
docker compose exec bot python create_test_user.py --photos 3 --gender female --city Санкт-Петербург
```

Ожидаемый результат:

- Скрипт выводит `Created test user`.
- У каждого пользователя есть `telegram_id`, `username`, имя и количество approved-фото.
- В MinIO появляются объекты в bucket `profiles`.
- Эти анкеты могут попадаться в просмотре анкет.

## 5. Создание тестового лайка, скипа и мэтча

В командах ниже замени `YOUR_TELEGRAM_ID` на свой настоящий Telegram ID.

Создать пользователя, который лайкнул тебя:

```bash
docker compose exec bot python create_test_user.py \
  --target-telegram-id YOUR_TELEGRAM_ID \
  --action like \
  --photos 5 \
  --gender female
```

Создать пользователя, который уже в мэтче с тобой:

```bash
docker compose exec bot python create_test_user.py \
  --target-telegram-id YOUR_TELEGRAM_ID \
  --action match \
  --photos 5 \
  --gender female
```

Создать пользователя, который скипнул тебя:

```bash
docker compose exec bot python create_test_user.py \
  --target-telegram-id YOUR_TELEGRAM_ID \
  --action skip \
  --photos 3 \
  --gender male
```

Как проверить скип:
```bash
docker compose exec postgres psql -U postgres -d dating_bot -c "
  select
    i.created_at,
    skipped.id as skipped_user_id,
    skipped.telegram_id,
    skipped.username,
    p.name,
    p.age,
    p.city
  from interactions i
  join users actor on actor.id = i.from_user_id
  join users skipped on skipped.id = i.to_user_id
  left join profiles p on p.user_id = skipped.id
  where i.action = 'skip'
    and actor.telegram_id = 5497326447
  order by i.created_at desc;
  "
```

Ожидаемый результат:

- `like` записывает лайк от seed-пользователя к тебе.
- `match` создает взаимный лайк и активный мэтч.
- `skip` добавляет skip-взаимодействие.
- В SurrealDB и PostgreSQL не должно быть рассинхронизации, из-за которой уже обработанные анкеты снова бесконечно показываются.

## 6. Проверка просмотра анкет

В боте открыть просмотр анкет.

Проверить:

- анкеты показываются с главной фотографией;
- если у чужой анкеты несколько фото, можно листать фото;
- кнопки лайка и скипа работают;
- после лайка/скипа эта же анкета не должна сразу снова попадаться;
- если случился мэтч, появляется уведомление;
- в `Мои мэтчи` показывается имя и Telegram username/ссылка, куда писать.

Ожидаемый результат:

- Нет `MultipleResultsFound`.
- Нет повторного показа уже лайкнутой/скипнутой анкеты в обычном сценарии.
- Уведомление о мэтче не ломает навигацию.

## 7. Проверка раздела своих фотографий

В своей анкете открыть раздел `Фотографии`.

Проверить:

- отображается список/просмотр своих фото;
- можно переключаться между фото;
- можно удалить фото;
- можно сделать другое фото главным;
- после выбора главного фото кнопка `главное` пропадает у текущего главного фото и появляется у остальных;
- в `Моя анкета` не должно быть тяжелого пересоздания фото, потому что фото вынесены в отдельный раздел.

Ожидаемый результат:

- Главное фото меняется.
- Удаленное фото больше не показывается.
- Если удалить главное фото, другое approved-фото становится главным или профиль остается без фото, если фото больше нет.

## 8. Проверка ручной модерации фото

Загрузить новое фото обычным пользователем.

Проверить:

- до модерации фото не видно в анкете;
- фото появилось в админке `/moderation/photos`;
- `Approve` делает фото видимым;
- `Reject` не показывает фото в профиле;
- отклоненное фото не должно попадать в просмотр чужих анкет.

Ожидаемый результат:

- Статусы работают: `PENDING`, `APPROVED`, `REJECTED`.
- В профиле используются только approved-фото.

## 9. Проверка персистентности SurrealDB

Создать хотя бы один лайк или мэтч, затем перезапустить только SurrealDB и бота:

```bash
docker compose restart surrealdb bot
```

Проверить:

```bash
docker compose ps surrealdb bot
docker compose logs --tail=60 surrealdb
docker compose logs --tail=60 bot
```

Ожидаемый результат:

- `surrealdb` снова `healthy`.
- В логах SurrealDB есть загрузка `/data/database`.
- Бот пишет `SurrealDB connected`.
- Ранее обработанные лайки/скипы/мэтчи не исчезли после рестарта.

## 10. Проверка сервисов и метрик

Проверить метрики бота:

```text
http://localhost:8001/metrics
```

Проверить Prometheus:

```text
http://localhost:9090
```

Проверить Grafana:

```text
http://localhost:3000
```

Ожидаемый результат:

- `/metrics` открывается.
- Prometheus видит target бота.
- Grafana открывается.

## 11. Benchmark

Запустить benchmark-профиль:

```bash
docker compose --profile test up --build benchmark
```

Ожидаемый результат:

- benchmark запускается и завершается без падения контейнеров основного приложения;
- если benchmark показывает плохие значения, это не всегда blocker для демонстрации, но нужно записать результат в задачи на улучшение.

## 12. Быстрая проверка логов

После всех действий проверить ошибки:

```bash
docker compose logs --tail=200 bot
docker compose logs --tail=200 admin
docker compose logs --tail=200 celery_worker
docker compose logs --tail=200 match_consumer
docker compose logs --tail=200 surrealdb
```

Не должно быть:

- Python traceback;
- `MultipleResultsFound`;
- ошибок сравнения `character varying = moderationstatus`;
- бесконечного рестарта `dating_bot`;
- `socket.gaierror: Name or service not known` для `surrealdb`;
- `404` на `/moderation/photos`.

Допустимые предупреждения:

- RabbitMQ `global_qos is deprecated`;
- SurrealDB warning про подключение без явно указанного protocol format, если бот при этом работает.

## 13. Минимальный сценарий демонстрации

Если времени мало, достаточно пройти этот сценарий:

1. `docker compose down -v`
2. `docker compose up -d --build`
3. `/start` в Telegram и создать свою анкету.
4. Загрузить фото.
5. Одобрить фото в `http://localhost:8080/moderation/photos`.
6. Создать 3-5 seed-анкет через `create_test_user.py`.
7. Создать один seed-match через `--action match`.
8. В боте показать:
   - `Моя анкета`;
   - `Фотографии`;
   - просмотр анкет;
   - лайк/скип;
   - `Мои мэтчи`;
   - админку модерации;
   - MinIO bucket с фото;
   - метрики `/metrics`.

Если все пункты проходят без traceback в логах, бот готов к показу.
