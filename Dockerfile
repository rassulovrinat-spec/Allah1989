FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -m appuser \
    && mkdir -p /app/static/uploads /app/data \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000
CMD ["python3", "-m", "uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
