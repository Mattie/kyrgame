FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app \
    DATABASE_URL=sqlite+pysqlite:////data/kyrgame.db \
    KYRGAME_RESET_ON_BOOT=0 \
    KYRGAME_CORS_ORIGINS=

EXPOSE 8000

CMD ["sh", "-c", "uvicorn kyrgame.webapp:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
