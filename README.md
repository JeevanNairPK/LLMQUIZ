# LLMQUIZ

Endpoint + headless solver for the "LLM Analysis Quiz" project.
This repository contains a FastAPI service that:
- verifies secrets from incoming POSTs,
- uses Playwright to render JS quiz pages,
- downloads files and performs extraction (CSV/XLSX/PDF),
- supports OCR (Tesseract) for scanned PDFs and images,
- posts answers to the quiz submit URL.

## Quick setup (Docker / Render-ready)

1. Copy this repo to GitHub (repo name: `LLMQUIZ`).
2. Create Render web service (Docker) or run locally with Docker.
3. Set environment variables:
   - `QUIZ_SECRET` (your secret) — REQUIRED. Example: `viscabarca`
   - `QUIZ_EMAIL` (default email for submissions) — REQUIRED. Example: `23f2005148@ds.study.iitm.ac.in`
   - `WORKER_TIMEOUT_SECONDS` (optional, default 170)
4. Deploy.

## Local run (Docker)
```bash
docker build -t llmquiz .
docker run -e QUIZ_SECRET=viscabarca -e QUIZ_EMAIL=23f2005148@ds.study.iitm.ac.in -p 8000:8000 llmquiz
# then POST to /webhook
