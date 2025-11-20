FROM mcr.microsoft.com/playwright/python:latest

WORKDIR /app

# Install system deps needed for python-magic (optional)
RUN apt-get update && \
    apt-get install -y --no-install-recommends libmagic1 && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (Chromium, Firefox, WebKit)
RUN python -m playwright install --with-deps

COPY . /app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
