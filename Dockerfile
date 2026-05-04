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

# Required so src.adar.* and domains.arcl.* imports resolve
ENV PYTHONPATH=/app

EXPOSE 8020

CMD ["python", "api/main.py"]

