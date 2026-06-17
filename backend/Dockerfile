FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /data /config

COPY backend/ .

ENV PYTHONPATH=/app \
    DATABASE_URL=sqlite+pysqlite:////data/kyrgame.db \
    KYRGAME_RESET_ON_BOOT=0 \
    KYRGAME_SEED_IF_EMPTY=1 \
    KYRGAME_FORCE_HONOR_MODE=0 \
    KYRGAME_RUN_MIGRATIONS=1 \
    KYRGAME_CORS_ORIGINS=

EXPOSE 8000

CMD ["sh", "-c", "uvicorn kyrgame.webapp:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
