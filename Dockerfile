# syntax=docker/dockerfile:1
FROM node:24-slim AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# vite.config.ts writes to ../server/app/static, i.e. /src/server/app/static
RUN npm run build

# Pinned requirements come from uv.lock, so the image matches the tested environment.
FROM python:3.12-slim AS deps
RUN pip install --no-cache-dir uv
WORKDIR /src
COPY server/pyproject.toml server/uv.lock ./
RUN uv export --frozen --no-dev --no-hashes --no-emit-project -o requirements.txt

FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*
COPY --from=deps /src/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin remix && mkdir /data && chown remix /data
WORKDIR /app
# Layout matters: app/styles.py and providers/comfyui.py resolve /app/styles and /app/workflows relative to /app/app.
COPY server/app ./app
COPY server/styles ./styles
COPY server/workflows ./workflows
COPY --from=web /src/server/app/static ./app/static
ENV DATA_DIR=/data PYTHONUNBUFFERED=1
VOLUME /data
USER remix
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/healthz')"
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips=*"]
