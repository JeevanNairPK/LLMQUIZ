FROM mcr.microsoft.com/playwright/python:latest

WORKDIR /app

# Install libmagic for python-magic
RUN apt-get update && apt-get install -y --no-install-recommends libmagic1 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Playwright browsers are included in base image
COPY . /app

# Render requires binding to $PORT, not a fixed number
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
