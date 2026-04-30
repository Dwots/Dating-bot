FROM python:3.11-slim

WORKDIR /app

COPY admin/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/database.py /bot/database.py

COPY admin/ .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
