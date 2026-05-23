# =============================================================================
# Backend image — FastAPI + ARQ worker share this image.
# Includes Playwright Chromium (~120MB) for HTML→PDF rendering.
# =============================================================================
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

# System deps: Playwright Chromium runtime + libpq + build tooling (incl. cmake
# for llama-cpp-python which builds from source on ARM)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg git \
    libpq5 libpq-dev gcc g++ cmake \
    libopenblas-dev libomp-dev \
    fonts-noto fonts-noto-cjk fonts-noto-color-emoji \
    libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
# Build llama.cpp with OpenBLAS for ARM CPU acceleration
ENV CMAKE_ARGS="-DGGML_BLAS=ON -DGGML_BLAS_VENDOR=OpenBLAS"
RUN pip install --upgrade pip && pip install -e . && \
    playwright install --with-deps chromium

COPY . .

# Default to API. docker-compose overrides command for the worker container.
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
