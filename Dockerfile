FROM python:3.11-slim

WORKDIR /app

# Install system deps for lxml
RUN apt-get update && apt-get install -y \
    gcc \
    libxml2-dev \
    libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run injects PORT env var — must use it
ENV PORT=8040
EXPOSE 8040

CMD uvicorn api.main:app --host 0.0.0.0 --port ${PORT}