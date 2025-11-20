# LLMQUIZ - LLM Analysis Quiz Endpoint

This repository implements the webhook endpoint and a headless solver required for the **LLM Analysis Quiz**.  
It validates incoming POSTs (secret), renders JavaScript quiz pages with Playwright, downloads/reads attached files (CSV/XLSX/PDF/images), optionally OCRs scanned content, computes answers using heuristics, and submits them to the quiz-provided submit endpoint.

---

## Repository structure

LLMQUIZ/
├── main.py # FastAPI server + solver logic (Playwright, pdfplumber, pytesseract)
├── requirements.txt
├── Dockerfile
├── .env.example
├── .gitignore
├── render.yaml
├── README.md
└── LICENSE

yaml
Copy code

---

## Required environment variables (set in Render / your host)

- `QUIZ_SECRET` — the secret string provided in the Google Form (e.g. `viscabarca`)
- `QUIZ_EMAIL` — default email used when submitting answers (e.g. `23f2005148@ds.study.iitm.ac.in`)
- `WORKER_TIMEOUT_SECONDS` — worker timeout in seconds (default `170`)
- `ENABLE_OCR` — `true` or `false` (enable Tesseract OCR for scanned documents)

> **Do not** commit a real `.env` file to GitHub. Use Render's environment variable settings for production.

---

## Deploy on Render (short how-to)

1. Create a public service on Render, choose **Docker** and connect the `LLMQUIZ` repo.
2. Set environment variables (Render dashboard → Environment → Environment Variables):
   - `QUIZ_SECRET=viscabarca`
   - `QUIZ_EMAIL=23f2005148@ds.study.iitm.ac.in`
   - `WORKER_TIMEOUT_SECONDS=170`
   - `ENABLE_OCR=true`
3. Deploy. Render will build the Docker image using the provided `Dockerfile`.

---

## Local test (optional)

You can build and run the container locally to test:

```bash
# build
docker build -t llmquiz:local .

# run (use a local .env file; do NOT commit it)
docker run --env-file .env -p 8000:8000 llmquiz:local
Test the webhook (this example uses the official demo URL):

bash
Copy code
curl -X POST "http://localhost:8000/webhook
