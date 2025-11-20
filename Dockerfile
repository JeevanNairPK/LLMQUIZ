FROM python:3.11-slim

# Install system deps for Playwright, pdfplumber, tesseract, and image libs
RUN apt-get update && apt-get install -y \
    build-essential curl git wget \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libxkbcommon0 libgbm1 \
    libxcomposite1 libxdamage1 libxrandr2 libasound2 libpangocairo-1.0-0 \
    fonts-liberation libpangox-1.0-0 libssl-dev libxml2 libxslt1.1 \
    libjpeg62-turbo libfreetype6 libpng16-16 default-jre-headless \
    tesseract-ocr tesseract-ocr-eng --no-install-recommends \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install --with-deps

COPY . /app

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "120"]

