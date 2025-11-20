# main.py
import os
import re
import asyncio
import base64
import tempfile
import json
import time
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import httpx
import pandas as pd
import pdfplumber
import magic

# Playwright async
from playwright.async_api import async_playwright

# OCR
try:
    import pytesseract
    from PIL import Image, ImageOps, ImageFilter
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

load_dotenv()

QUIZ_SECRET = os.getenv("QUIZ_SECRET")
DEFAULT_EMAIL = os.getenv("QUIZ_EMAIL")
WORKER_TIMEOUT_SECONDS = int(os.getenv("WORKER_TIMEOUT_SECONDS", "170"))
ENABLE_OCR = os.getenv("ENABLE_OCR", "false").lower() in ("1", "true", "yes")

app = FastAPI(title="LLM Analysis Quiz Endpoint")

class WebhookPayload(BaseModel):
    email: Optional[str] = None
    secret: str
    url: str

@app.post("/webhook")
async def webhook(payload: WebhookPayload, background_tasks: BackgroundTasks):
    if not payload.secret or not payload.url:
        raise HTTPException(status_code=400, detail="Missing `secret` or `url`")
    if QUIZ_SECRET is None:
        raise HTTPException(status_code=500, detail="Server misconfigured: no QUIZ_SECRET set")
    if payload.secret != QUIZ_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")
    background_tasks.add_task(run_quiz_workflow, payload.email or DEFAULT_EMAIL, payload.secret, payload.url)
    return JSONResponse(status_code=200, content={"status": "accepted"})

async def run_quiz_workflow(email: str, secret: str, url: str):
    start_time = time.time()
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = await browser.new_context()
            page = await context.new_page()
            page.set_default_timeout(min(60000, (WORKER_TIMEOUT_SECONDS - 10) * 1000))
            await page.goto(url, wait_until="load")
            await asyncio.sleep(0.8)
            body_text = await page.evaluate("() => document.body.innerText")
            problem_text = extract_problem_text(page, body_text)
            submit_url = find_submit_url(page, body_text, problem_text)
            file_url = await find_download_link(page)
            file_bytes = None
            fname = None
            if file_url:
                file_bytes, fname = await download_file_bytes(file_url)
            # If page embeds base64 payloads (the sample uses atob), try to decode
            if not file_bytes:
                data_uri = re_search_data_uri(await page.content())
                if data_uri:
                    file_bytes, fname = decode_data_uri(data_uri, default_name="embedded.bin")
            # If OCR is enabled but no file, try to screenshot page area with relevant element
            if ENABLE_OCR and OCR_AVAILABLE and not file_bytes:
                # capture whole page screenshot for OCR heuristics
                img_bytes = await page.screenshot(full_page=True)
                file_bytes = img_bytes
                fname = "page_snapshot.png"
            # Solve heuristically
            answer_payload = None
            if problem_text:
                answer_payload = await heuristic_solve(problem_text, file_bytes, fname, page)
            elif file_bytes:
                answer_payload = await attempt_process_file_bytes(file_bytes, fname)
            else:
                answer_payload = {"problem_text": (problem_text or "")[:200]}
            if not submit_url:
                submit_url = await try_find_submit_from_scripts(page)
            if submit_url and answer_payload is not None:
                submit_body = {"email": email, "secret": secret, "url": url, "answer": answer_payload}
                async with httpx.AsyncClient(timeout=60) as client:
                    try:
                        resp = await client.post(submit_url, json=submit_body)
                        print("[submit] status:", resp.status_code, "text:", await safe_text(resp))
                    except Exception as e:
                        print("submit error:", e)
            else:
                print("No submit url or no answer")
            await browser.close()
    except Exception as e:
        print("run_quiz_workflow error:", e)
    finally:
        print("Worker finished in", time.time() - start_time, "s")

def extract_problem_text(page, body_text: str) -> str:
    try:
        el_text = asyncio.get_event_loop().run_until_complete(page.evaluate(
            "() => { let el = document.querySelector('#result, .result, #question, .question, #task, .task'); return el ? el.innerText : null }"))
        if el_text:
            return el_text
    except Exception:
        pass
    if body_text:
        m = re.search(r"(Q\d{2,4}\..+)", body_text, re.DOTALL)
        if m:
            return m.group(1)
        m2 = re.search(r"(Download[^\n\r]+[\s\S]+)", body_text, re.IGNORECASE)
        if m2:
            return m2.group(1)
    return body_text or ""

def find_submit_url(page, body_text: str, problem_text: str) -> Optional[str]:
    combined = (problem_text or "") + "\n" + (body_text or "")
    urls = re.findall(r"https?://[^\s'\"<>]+", combined)
    for u in urls:
        if "/submit" in u or "submit" in u:
            return u
    return None

async def find_download_link(page):
    try:
        anchors = await page.query_selector_all("a")
        for a in anchors:
            text = await a.inner_text()
            href = await a.get_attribute("href")
            if href:
                if "download" in (text or "").lower() or re.search(r"\.(csv|xlsx|xls|pdf|zip|png|jpg)$", href, re.I):
                    return href
        page_text = await page.evaluate("() => document.documentElement.innerHTML")
        m = re.search(r"https?://[^\"]+\.(csv|xlsx|xls|pdf|zip|png|jpg)", page_text, re.I)
        if m:
            return m.group(0)
    except Exception:
        pass
    return None

async def download_file_bytes(url: str):
    async with httpx.AsyncClient(timeout=60) as client:
        try:
            r = await client.get(url)
            r.raise_for_status()
            cd = r.headers.get("content-disposition", "")
            fname = None
            m = re.search(r'filename="?([^"]+)"?', cd)
            if m:
                fname = m.group(1)
            else:
                fname = os.path.basename(url.split("?")[0])
            return r.content, fname or "downloaded.bin"
        except Exception as e:
            print("download error", e)
            return None, None

def re_search_data_uri(text: str):
    m = re.search(r"(data:([-\w/+.]+)?;base64,[A-Za-z0-9+/=]+)", text)
    return m.group(1) if m else None

def decode_data_uri(data_uri: str, default_name="data.bin"):
    header, b64 = data_uri.split(",", 1)
    content = base64.b64decode(b64)
    m = re.match(r"data:([^;]+);base64", header)
    ext = ""
    if m:
        mime = m.group(1)
        ext = guess_ext_from_mime(mime)
    name = default_name
    if ext:
        name = default_name.rsplit(".",1)[0] + "." + ext
    return content, name

def guess_ext_from_mime(mime: str):
    if "/" in mime:
        return mime.split("/")[-1]
    return ""

async def attempt_process_file_bytes(file_bytes: bytes, filename: str):
    mime = magic.from_buffer(file_bytes, mime=True)
    lower = (filename or "").lower()
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1] or "") as tf:
            tf.write(file_bytes)
            tf.flush()
            temp_path = tf.name
        if ENABLE_OCR and OCR_AVAILABLE and (lower.endswith(".png") or lower.endswith(".jpg") or "image" in mime):
            try:
                text = pytesseract.image_to_string(Image.open(temp_path))
                return {"ocr_text": text.strip()[:2000]}
            except Exception as e:
                print("ocr failed", e)
        if "pdf" in mime or lower.endswith(".pdf"):
            try:
                with pdfplumber.open(temp_path) as pdf:
                    if len(pdf.pages) >= 2:
                        p = pdf.pages[1]
                        tables = p.extract_tables()
                        if tables and len(tables) > 0:
                            df = pd.DataFrame(tables[0][1:], columns=tables[0][0])
                            if "value" in map(str.lower, df.columns):
                                col = [c for c in df.columns if c.lower() == "value"][0]
                                df[col] = pd.to_numeric(df[col], errors="coerce")
                                s = float(df[col].sum(skipna=True))
                                return s
            except Exception as e:
                print("pdf parse error", e)
        if "csv" in mime or lower.endswith(".csv"):
            df = pd.read_csv(temp_path)
            if "value" in map(str.lower, df.columns):
                col = [c for c in df.columns if c.lower() == "value"][0]
                return float(df[col].sum())
            nums = df.select_dtypes(include='number')
            if not nums.empty:
                return float(nums.iloc[:,0].sum())
        if "excel" in mime or lower.endswith(".xlsx") or lower.endswith(".xls"):
            df = pd.read_excel(temp_path)
            if "value" in map(str.lower, df.columns):
                col = [c for c in df.columns if c.lower() == "value"][0]
                return float(df[col].sum())
            nums = df.select_dtypes(include='number')
            if not nums.empty:
                return float(nums.iloc[:,0].sum())
    except Exception as e:
        print("attempt_process_file_bytes error:", e)
    finally:
        try:
            if temp_path:
                os.unlink(temp_path)
        except Exception:
            pass
    return None

async def heuristic_solve(problem_text: str, file_bytes: bytes, filename: str, page):
    text = (problem_text or "").strip()
    low = text.lower()
    if "sum of" in low and "value" in low and "page 2" in low:
        if file_bytes:
            v = await attempt_process_file_bytes(file_bytes, filename or "file")
            if v is not None:
                return v
        link = await find_download_link(page)
        if link:
            bts, fname = await download_file_bytes(link)
            if bts:
                v = await attempt_process_file_bytes(bts, fname)
                if v is not None:
                    return v
    m = re.search(r"what is ([0-9\.\-\+\*\/\s]+)\?", low)
    if m:
        expr = m.group(1)
        if re.match(r"^[0-9\.\-\+\*\/\s]+$", expr):
            try:
                return float(eval(expr))
            except Exception:
                pass
    if "true or false" in low or "is the following true" in low:
        if "true" in low or "yes" in low:
            return True
        return False
    if file_bytes:
        v = await attempt_process_file_bytes(file_bytes, filename or "file")
        if v is not None:
            return v
    return {"problem_text": problem_text[:200]}

async def try_find_submit_from_scripts(page):
    try:
        html = await page.content()
        m = re.search(r"https?://[^\s'\"<>]+/submit[^\s'\"<>]*", html)
        if m:
            return m.group(0)
        forms = await page.query_selector_all("form")
        for f in forms:
            action = await f.get_attribute("action")
            if action and action.startswith("http"):
                return action
    except Exception as e:
        print("try_find_submit_from_scripts error", e)
    return None

async def safe_text(response):
    try:
        return response.text
    except:
        return "<unreadable>"

