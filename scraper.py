import os
import re
import json
import time
import random
import logging
import asyncio
import pdfplumber
import requests
import warnings
warnings.filterwarnings("ignore")

from io import BytesIO
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

OUTPUT_DIR = Path("cases")
OUTPUT_DIR.mkdir(exist_ok=True)

# --- Config ---
TOR_PROXY = "socks5://127.0.0.1:9050"   # Tor SOCKS5 proxy (run: sudo service tor start)
USE_TOR = True                            # Set False to run without Tor

DORK_QUERIES = [
    'site:saflii.org "Gauteng" "murder" "accused" "convicted" filetype:pdf',
    'site:saflii.org "Western Cape" "murder" "life imprisonment" filetype:pdf',
    'site:saflii.org "KwaZulu-Natal" "murder" "accused" "sentenced" filetype:pdf',
    'site:saflii.org "Gauteng" "rape" "murder" "convicted" filetype:pdf',
    'site:saflii.org "premeditated murder" "Gauteng" filetype:pdf',
    'site:saflii.org "serial killer" "South Africa" "convicted" filetype:pdf',
    'site:saflii.org "Gauteng" "kidnapping" "murder" "life imprisonment" filetype:pdf',
    'site:saflii.org "Western Cape" "robbery" "murder" "gang" filetype:pdf',
    'site:saflii.org "femicide" "South Africa" "convicted" filetype:pdf',
]

DDG_ONION = "https://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion"
DDG_CLEAR  = "https://duckduckgo.com"


def is_tor_running() -> bool:
    try:
        r = requests.get(
            "https://check.torproject.org/api/ip",
            proxies={"http": TOR_PROXY, "https": TOR_PROXY},
            timeout=10,
            verify=False,
        )
        data = r.json()
        if data.get("IsTor"):
            log.info(f"Tor active — exit IP: {data.get('IP')}")
            return True
        log.warning("Tor proxy connected but not routing through Tor")
        return False
    except Exception as e:
        log.warning(f"Tor check failed: {e}")
        return False


def already_scraped(url: str) -> bool:
    safe = re.sub(r"[^\w]", "_", url.split("/")[-1])
    return (OUTPUT_DIR / f"{safe}.json").exists()


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    text = ""
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
    except Exception as e:
        log.warning(f"PDF extract error: {e}")
    return text.strip()


def parse_case(text: str, url: str) -> dict:
    case = {
        "url": url,
        "scraped_at": datetime.now().isoformat(),
        "case_number": "",
        "court": "",
        "date": "",
        "accused": "",
        "charges": [],
        "verdict": "",
        "sentence": "",
        "province": "",
        "full_text": text,
        "summary": "",
    }

    m = re.search(r"CASE\s*NO[:\.]?\s*([A-Z]{1,4}\d+/\d{4})", text, re.I)
    if m:
        case["case_number"] = m.group(1)

    for court in ["Gauteng Division, Pretoria", "Gauteng Local Division, Johannesburg",
                  "Western Cape High Court", "KwaZulu-Natal High Court",
                  "Eastern Cape High Court", "Supreme Court of Appeal",
                  "South Gauteng High Court"]:
        if court.lower() in text.lower():
            case["court"] = court
            break

    for prov in ["Gauteng", "Western Cape", "KwaZulu-Natal", "Eastern Cape",
                 "Limpopo", "Mpumalanga", "Northern Cape", "Free State", "North West"]:
        if prov.lower() in text.lower():
            case["province"] = prov
            break

    m = re.search(r"\band\b\s*\n+([A-Z][A-Z\s]+?)\s+ACCUSED", text)
    if m:
        case["accused"] = m.group(1).strip()

    m = re.search(r"DATE[:\s]+(\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4})", text, re.I)
    if m:
        case["date"] = m.group(1)

    for charge in ["murder", "rape", "kidnapping", "robbery", "attempted murder",
                   "assault", "human trafficking", "femicide", "fraud"]:
        if charge.lower() in text.lower():
            case["charges"].append(charge)

    if "found guilty" in text.lower():
        case["verdict"] = "Guilty"
    elif re.search(r"acquitted|not guilty", text, re.I):
        case["verdict"] = "Not Guilty"

    for pattern in [r"life imprisonment", r"(\d+)\s*years['\s]?\s*imprisonment",
                    r"sentenced to (\d+) years"]:
        m = re.search(pattern, text, re.I)
        if m:
            case["sentence"] = m.group(0).strip()
            break

    case["summary"] = text[:1000].replace("\n", " ").strip()
    return case


def save_case(case: dict):
    safe = re.sub(r"[^\w]", "_", case.get("case_number") or case["url"].split("/")[-1])
    path = OUTPUT_DIR / f"{safe}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(case, f, ensure_ascii=False, indent=2)
    log.info(f"Saved → {path}")


async def search_ddg(page, query: str, max_results: int = 15) -> list[str]:
    """Search DuckDuckGo (clearnet) via Playwright and collect SAFLII PDF URLs."""
    urls = []
    try:
        ddg_url = f"{DDG_CLEAR}/?q={query.replace(' ', '+')}&ia=web"
        await page.goto(ddg_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(random.randint(2000, 4000))

        links = await page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => e.href)"
        )
        for link in links:
            if "saflii.org" in link and link.endswith(".pdf") and link not in urls:
                urls.append(link)
                log.info(f"Found: {link}")
                if len(urls) >= max_results:
                    break
    except Exception as e:
        log.warning(f"DDG search failed: {e}")
    return urls


async def download_pdf_via_tor(url: str) -> bytes | None:
    """Download PDF through Tor SOCKS5 proxy using requests (sync, in thread)."""
    def _fetch():
        try:
            proxies = {"http": TOR_PROXY, "https": TOR_PROXY}
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; rv:109.0) "
                    "Gecko/20100101 Firefox/115.0"
                ),
                "Accept": "application/pdf,*/*",
                "Referer": "https://www.saflii.org/",
            }
            r = requests.get(url, headers=headers, proxies=proxies,
                             timeout=30, verify=False)
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                log.info(f"Downloaded via Tor: {url} ({len(r.content)//1024}KB)")
                return r.content
            else:
                log.warning(f"Tor download: HTTP {r.status_code} for {url}")
        except Exception as e:
            log.warning(f"Tor download failed {url}: {e}")
        return None

    return await asyncio.to_thread(_fetch)


async def download_pdf_browser(page, url: str) -> bytes | None:
    """Fallback: download PDF through Playwright browser session."""
    try:
        response = await page.request.get(
            url,
            headers={"Accept": "application/pdf,*/*", "Referer": "https://www.saflii.org/"},
            timeout=30000,
        )
        if response.status == 200:
            content = await response.body()
            if content[:4] == b"%PDF":
                log.info(f"Downloaded via browser: {url} ({len(content)//1024}KB)")
                return content
    except Exception as e:
        log.warning(f"Browser download failed {url}: {e}")
    return None


async def run_async(queries: list[str] = None, max_per_query: int = 15):
    queries = queries or DORK_QUERIES

    tor_ok = False
    if USE_TOR:
        log.info("Checking Tor connection...")
        tor_ok = is_tor_running()
        if tor_ok:
            log.info("Tor is active — SAFLII downloads will route through Tor")
        else:
            log.warning("Tor not available — falling back to direct browser download")
            log.warning("To enable Tor: sudo apt install tor && sudo service tor start")

    all_urls: set[str] = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-ZA",
        )
        page = await context.new_page()
        await page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        # --- Step 1: Search DuckDuckGo ---
        log.info("=== Searching DuckDuckGo for SAFLII cases ===")
        for query in queries:
            urls = await search_ddg(page, query, max_per_query)
            all_urls.update(urls)
            await asyncio.sleep(random.uniform(3, 7))

        log.info(f"Total unique PDFs found: {len(all_urls)}")

        # --- Step 2: Download each PDF ---
        for url in all_urls:
            if already_scraped(url):
                log.info(f"Skip (done): {url}")
                continue

            # Try Tor first, fall back to browser
            if tor_ok:
                pdf_bytes = await download_pdf_via_tor(url)
            else:
                pdf_bytes = await download_pdf_browser(page, url)

            if not pdf_bytes:
                log.warning(f"Could not download: {url}")
                continue

            text = extract_text_from_pdf(pdf_bytes)
            if not text:
                log.warning(f"Empty text: {url}")
                continue

            case = parse_case(text, url)
            save_case(case)

            await asyncio.sleep(random.uniform(3, 8))

        await browser.close()

    log.info(f"Done. All cases saved to ./{OUTPUT_DIR}/")


def run(queries: list[str] = None):
    asyncio.run(run_async(queries))


if __name__ == "__main__":
    run()
