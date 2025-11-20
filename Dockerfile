# Use the Playwright Python image (includes browsers)
FROM mcr.microsoft.com/playwright/python:latest

WORKDIR /app

# Install libmagic (for python-magic) and keep image small
RUN apt-get update \
 && apt-get install -y --no-install-recommends libmagic1 file \
 && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy app source
COPY . /app

# Ensure PORT env var is used by the server
ENV PORT=8000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
