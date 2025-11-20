# Dockerfile — use exact tag (no leading "v")
FROM mcr.microsoft.com/playwright/python:1.56.0-jammy

WORKDIR /app

# install python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# ensure browsers are installed (safe even if image already has them)
RUN python -m playwright install --with-deps

COPY . /app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
