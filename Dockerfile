# Single-service image: Next.js frontend and FastAPI backend in one container, so the app fits
# Render's free plan (one always-on service) and the browser never waits on a second sleeping service.
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci || npm install
COPY frontend/ .
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 INSIGHTFORGE_DATA_DIR=/app/data NODE_ENV=production \
    BACKEND_URL=http://127.0.0.1:8000 HOSTNAME=0.0.0.0
COPY --from=web /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
RUN python scripts/init_db.py
COPY --from=web /web/.next/standalone /web
COPY --from=web /web/.next/static /web/.next/static
COPY start.sh /start.sh
EXPOSE 10000
CMD ["sh", "/start.sh"]
