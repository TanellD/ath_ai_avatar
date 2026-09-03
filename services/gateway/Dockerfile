# Контекст сборки — КОРЕНЬ репозитория (нужен packages/contracts).
#   docker build -f services/gateway/Dockerfile .

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Общие контракты ставим отдельным слоем — они меняются реже кода сервиса.
COPY packages/contracts /opt/packages/contracts
RUN pip install -e /opt/packages/contracts

# Зависимости ставим до кода, чтобы правка app/ не тянула переустановку.
# Пустой пакет-заглушка нужен только чтобы setuptools нашёл, что упаковывать.
COPY services/gateway/pyproject.toml ./pyproject.toml
RUN mkdir -p app && touch app/__init__.py && pip install -e .

COPY services/gateway/app ./app
COPY services/gateway/alembic.ini ./alembic.ini

# Данные (SQLite) живут в /data — bind-mount из ./data на хосте.
RUN mkdir -p /data

# ------------------------------------------------------------------ dev
FROM base AS dev
RUN pip install -e ".[dev]"
COPY services/gateway/tests ./tests
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ------------------------------------------------------------------ prod
FROM base AS prod
# Один воркер намеренно: живое состояние сессии и счётчик поколений лежат
# в памяти процесса. Второй воркер разъедет gen_id между соединениями —
# сначала Redis, потом масштабирование. См. docs/architecture.md.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
