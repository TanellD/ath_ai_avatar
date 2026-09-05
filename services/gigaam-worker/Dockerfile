FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# GigaAM leaves torch optional. Install an explicit CPU build so pip does not
# pull a multi-gigabyte CUDA runtime into the CPU benchmark image.
RUN pip install --index-url https://download.pytorch.org/whl/cpu \
    torch==2.10.0+cpu torchaudio==2.10.0+cpu

COPY services/gigaam-worker/pyproject.toml ./pyproject.toml
RUN mkdir -p app && touch app/__init__.py && pip install -e .

COPY services/gigaam-worker/app ./app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8020"]
