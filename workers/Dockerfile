FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# По умолчанию запускаем воркер
# beat — отдельная команда, запустим отдельным контейнером
CMD ["celery", "-A", "celery_app", "worker", "--loglevel=info", "-Q", "celery,notifications,ratings"]