import os
import re
import asyncio
import base64
import tempfile
import json
import time
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

import httpx
import pandas as pd
import pdfplumber
import magic

# Playwright async API
from playwright.async_api import async_playwright

# OCR support
try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

# Load environment variables
load_dotenv()

QUIZ_SECRET = os.getenv("QUIZ_SECRET")
DEFAULT_EMAIL = os.getenv("QUIZ_EMAIL")
WORKER_TIMEOUT_SECONDS = int(os.getenv("WORKER_TIMEOUT_SECONDS", "170"))
ENABLE_OCR = os.getenv("ENABLE_OCR", "false").lower() in ("1", "true", "yes")

app = FastAPI(title="LLM Analysis Quiz Endpoint")


# -------------------------------------------------------------------
# PAYLOAD MODEL
# -------------------------------------------------------------------
class WebhookPayload(BaseModel):
    email: Optional[str] = None
    secret: str
    url: str


# -------------------------------------------------------------------
# WEBHOOK ENDPOINT
# -------------------------------------------------------------------
@app.post("/webhook")
async def webhook(payload: WebhookPayload, background_tasks: BackgroundTasks):
    if not payload.secret or not payload.url:
        raise HTTPException(status_code=400, detail="Missing `secret` or `url`")

    if QUIZ_SECRET is None:
        raise HTTPException(status_code=500, detail="QUIZ_SECRET not configured")

    if payload.secret != QUIZ_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")

    # Start solver in background
    background_tasks.add_task(
        run_quiz_workflow,
        payload.email or DEFAULT_EMAIL,
        payload.secret,
        payload.url
    )

    return JSONResponse({"status": "accepted"}, status_code=200)


# -------------------------------------------------------------------
# MAIN WORKFLOW
# -------------------------------------------------------------------
async def run_quiz_workflow(email, secret, url):
    start = time.time()
    print(f"[worker] Started for URL: {url}")

    try:
        # Special case: if url is a local path (like your screenshot)
        if url.startswith("/") and os.path.exists(url):
            print("[worker] Local file detected:", url)
            with open(url, "rb") as f:
                content = f.read()
            answer = await attempt_process_file_bytes(content, os.path.basename(url))
            print("[worker] Local-file answer:", answer)
            return

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = await browser.new_context()
            page = await context.new_page()
            page.set_default_timeout((WORKER_TIMEOUT_SECONDS - 10) * 1000)

            await page.goto(url, wait_until="load")
            await asyncio.sleep(1)

            body_text = await page.evaluate("() => document.body.innerText")
            problem_text = extract_problem(body_text)

            submit_url = find_submit_url(body_text)

            # Detect downloadable files
            file_url = await find_download_link(page)
            file_bytes = None
            fname = None

            if file_url:
                file_bytes, fname = await download_file_bytes(file_url)

            if ENABLE_OCR and OCR_AVAILABLE and not file_bytes:
                img = await page.screenshot(full_page=True)
                file_bytes = img
                fname = "page_snapshot.png"

            # Solve the question
            answer = None

            if problem_text:
                answer = await heuristic_solve(problem_text, file_bytes, fname, page)
            elif file_bytes:
                answer = await attempt_process_file_bytes(file_bytes, fname)
            else:
                answer = {"problem_text": problem_text[:200]}

            # If no submit URL found, attempt scanning scripts
            if not submit_url:
                submit_url = await try_find_submit_from_scripts(page)

            if submit_url and answer is not None:
                submit_body = {
                    "email": email,
                    "secret": secret,
                    "url": url,
                    "answer": answer
                }

                async with httpx.AsyncClient(timeout=60) as client:
                    try:
                        r = await client.post(submit_url, json=submit_body)
                        print("[submit] Status:", r.status_code)
                        print("[submit] Body:", r.text)
                    except Exception as e:
                        print("[submit] Error:", e)

            await browser.close()

    except Exception as e:
        print("[worker] Error:", e)

    finally:
        print(f"[worker] Finished in {time.time() - start:.1f}s")


# -------------------------------------------------------------------
# PARSING & EXTRACTION UTILITIES
# -------------------------------------------------------------------
def extract_problem(body_text: str):
    if not body_text:
        return ""
    # Try typical patterns ("Q123.", "Download...", etc.)
    m = re.search(r"(Q\d{2,4}\..+)", body_text, re.DOTALL)
    if m:
        return m.group(1)
    m2 = re.search(r"(Download[^\n]+)", body_text)
    if m2:
        return m2.group(1)
    return body_text


def find_submit_url(text):
    if not text:
        return None
    urls = re.findall(r"https?://[^\s'\"<>]+", text)
    for u in urls:
        if "submit" in u:
            return u
    return None


async def find_download_link(page):
    try:
        anchors = await page.query_selector_all("a")
        for a in anchors:
            href = await a.get_attribute("href")
            if href and re.search(r"\.(csv|xlsx|xls|pdf|png|jpg|zip)$", href, re.I):
                return href
    except:
        pass
    return None


async def download_file_bytes(url):
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url)
        r.raise_for_status()
        fname = url.split("/")[-1]
        return r.content, fname


# -------------------------------------------------------------------
# FILE PROCESSING
# -------------------------------------------------------------------
async def attempt_process_file_bytes(file_bytes, filename):
    mime = magic.from_buffer(file_bytes, mime=True)
    fname_lower = filename.lower()

    # OCR case
    if ENABLE_OCR and OCR_AVAILABLE and ("image" in mime or fname_lower.endswith((".png", ".jpg"))):
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tf:
                tf.write(file_bytes)
                tf.flush()
                text = pytesseract.image_to_string(Image.open(tf.name))
                return {"ocr_text": text.strip()[:2000]}
        except:
            pass

    # PDF case
    if "pdf" in mime or fname_lower.endswith(".pdf"):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tf:
            tf.write(file_bytes)
            tf.flush()
            with pdfplumber.open(tf.name) as pdf:
                if len(pdf.pages) >= 2:
                    table = pdf.pages[1].extract_tables()
                    if table:
                        df = pd.DataFrame(table[0][1:], columns=table[0][0])
                        if "value" in [c.lower() for c in df.columns]:
                            col = [c for c in df.columns if c.lower() == "value"][0]
                            df[col] = pd.to_numeric(df[col], errors="ignore")
                            return float(df[col].sum())

    # CSV
    if "csv" in mime or fname_lower.endswith(".csv"):
        df = pd.read_csv(tempfile.NamedTemporaryFile(delete=False).name)
        return df.sum(numeric_only=True).to_dict()

    # Excel
    if fname_lower.endswith((".xlsx", ".xls")):
        df = pd.read_excel(tempfile.NamedTemporaryFile(delete=False).name)
        return df.sum(numeric_only=True).to_dict()

    return None


# -------------------------------------------------------------------
# HEURISTIC SOLVER
# -------------------------------------------------------------------
async def heuristic_solve(text, file_bytes, fname, page):
    low = text.lower()

    if "sum of" in low and "value" in low:
        if file_bytes:
            return await attempt_process_file_bytes(file_bytes, fname)

    # Simple arithmetic
    m = re.search(r"what is ([0-9\.\-\+\*\/\s]+)\?", low)
    if m:
        expr = m.group(1)
        try:
            return float(eval(expr))
        except:
            pass

    # Boolean questions
    if "true or false" in low:
        if "true" in low:
            return True
        return False

    # File fallback
    if file_bytes:
        return await attempt_process_file_bytes(file_bytes, fname)

    return {"problem_text": text[:200]}


# -------------------------------------------------------------------
# SCRAPER FALLBACK
# -------------------------------------------------------------------
async def try_find_submit_from_scripts(page):
    html = await page.content()
    m = re.search(r"https?://[^\s\"']+/submit[^\s\"']*", html)
    if m:
        return m.group(0)
    return None
