# Собираем фронтенд отдельной стадией — в финальном образе Node не нужен,
# только собранная статика (api/main.py раздаёт webapp/dist напрямую).
FROM node:20-slim AS webapp-build
WORKDIR /app/webapp
COPY webapp/package*.json ./
RUN npm install
COPY webapp/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY api/ ./api/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY --from=webapp-build /app/webapp/dist ./webapp/dist

EXPOSE 8000
CMD alembic upgrade head && uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}
