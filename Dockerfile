FROM python:3.13-slim

WORKDIR /app

# Postgres client libs (psycopg2 потребує) + curl для healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first — кешується між білдами якщо requirements не мінялись
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the backend (frontend build і tests не потрібні в run-image)
COPY app/ ./app/
COPY .env.example ./

# Fly.io / Render підставляють PORT динамічно; локально дефолт 8000.
ENV PORT=8000
EXPOSE 8000

# shell-form щоб $PORT розкрилось у runtime
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
