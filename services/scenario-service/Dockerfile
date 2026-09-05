# Контекст сборки — КОРЕНЬ репозитория (нужен packages/contracts).
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY packages/contracts /opt/packages/contracts
RUN pip install -e /opt/packages/contracts

COPY services/scenario-service/pyproject.toml ./pyproject.toml
RUN mkdir -p app && touch app/__init__.py && pip install -e .

COPY services/scenario-service/app ./app

RUN mkdir -p /data

FROM base AS dev
RUN pip install -e ".[dev]"
COPY services/scenario-service/tests ./tests
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8050", "--reload"]

FROM base AS prod
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8050"]
