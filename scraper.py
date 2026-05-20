import re, json, logging, warnings
import pdfplumber, requests
from io import BytesIO
from pathlib import Path
from datetime import datetime
from time import sleep
from random import uniform

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

OUTPUT_DIR = Path("cases")
OUTPUT_DIR.mkdir(exist_ok=True)

BRAVE_API_KEY = None  # set via env: BRAVE_API_KEY
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

QUERIES = [
    'site:saflii.org "Gauteng" "murder" "accused" "convicted" filetype:pdf',
    'site:saflii.org "Western Cape" "murder" "life imprisonment" filetype:pdf',
    'site:saflii.org "KwaZulu-Natal" "murder" "convicted" filetype:pdf',
    'site:saflii.org "premeditated murder" "Gauteng" filetype:pdf',
    'site:saflii.org "serial killer" "South Africa" "convicted" filetype:pdf',
    'site:saflii.org "Gauteng" "kidnapping" "murder" filetype:pdf',
    'site:saflii.org "Western Cape" "robbery" "murder" filetype:pdf',
    'site:saflii.org "femicide" "South Africa" "convicted" filetype:pdf',
    'site:saflii.org "rape" "murder" "Gauteng" "life imprisonment" filetype:pdf',
]


# ── Search ────────────────────────────────────────────────────────────────────

def brave_search(query: str, api_key: str, max_results: int = 20) -> list[str]:
    """Return saflii.org PDF URLs matching the query via Brave Search API."""
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }
    params = {
        "q": query,
        "count": max_results,
        "search_lang": "en",
        "country": "ZA",
        "safesearch": "off",
    }
    try:
        r = requests.get(BRAVE_SEARCH_URL, headers=headers, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()

        results = data.get("web", {}).get("results", [])
        log.info(f"Brave returned {len(results)} results for: {query!r}")

        urls = []
        for item in results:
            url = item.get("url", "")
            if "saflii.org" in url and url.endswith(".pdf"):
                log.info(f"  Found PDF: {url}")
                urls.append(url)

        if not urls:
            # Log titles so we can see what DID come back
            for item in results[:5]:
                log.info(f"  [non-match] {item.get('url','')!r} — {item.get('title','')!r}")

        return urls

    except requests.HTTPError as e:
        log.error(f"Brave API HTTP error: {e.response.status_code} — {e.response.text[:200]}")
    except Exception as e:
        log.error(f"Brave search error: {e}")
    return []


# ── PDF download ──────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.saflii.org/",
    "Accept": "application/pdf,*/*",
}


def download_pdf(url: str) -> bytes | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30, verify=False)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            log.info(f"✓ Downloaded {url} ({len(r.content)//1024} KB)")
            return r.content
        log.warning(f"Download failed: HTTP {r.status_code} for {url}")
    except Exception as e:
        log.warning(f"Download error for {url}: {e}")
    return None


# ── PDF parsing ───────────────────────────────────────────────────────────────

def extract_pdf_text(pdf_bytes: bytes) -> str:
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
        "case_number": "", "court": "", "date": "",
        "accused": "", "charges": [], "verdict": "",
        "sentence": "", "province": "",
        "full_text": text, "summary": "",
    }

    m = re.search(r"CASE\s*NO[:\.]?\s*([A-Z]{1,4}\d+/\d{4})", text, re.I)
    if m:
        case["case_number"] = m.group(1)

    for c in [
        "Gauteng Division, Pretoria",
        "Gauteng Local Division, Johannesburg",
        "Western Cape High Court",
        "KwaZulu-Natal High Court",
        "Eastern Cape High Court",
        "Supreme Court of Appeal",
    ]:
        if c.lower() in text.lower():
            case["court"] = c
            break

    for p in [
        "Gauteng", "Western Cape", "KwaZulu-Natal", "Eastern Cape",
        "Limpopo", "Mpumalanga", "Northern Cape", "Free State", "North West",
    ]:
        if p.lower() in text.lower():
            case["province"] = p
            break

    m = re.search(r"\band\b\s*\n+([A-Z][A-Z\s]+?)\s+ACCUSED", text)
    if m:
        case["accused"] = m.group(1).strip()

    m = re.search(r"DATE[:\s]+(\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4})", text, re.I)
    if m:
        case["date"] = m.group(1)

    for ch in [
        "murder", "rape", "kidnapping", "robbery", "attempted murder",
        "assault", "human trafficking", "femicide", "fraud",
    ]:
        if ch in text.lower():
            case["charges"].append(ch)

    if "found guilty" in text.lower():
        case["verdict"] = "Guilty"
    elif re.search(r"acquitted|not guilty", text, re.I):
        case["verdict"] = "Not Guilty"

    for pat in [r"life imprisonment", r"\d+\s*years['\s]?\s*imprisonment"]:
        m = re.search(pat, text, re.I)
        if m:
            case["sentence"] = m.group(0).strip()
            break

    case["summary"] = text[:1000].replace("\n", " ").strip()
    return case


def already_scraped(url: str) -> bool:
    safe = re.sub(r"[^\w]", "_", url.split("/")[-1])
    return (OUTPUT_DIR / f"{safe}.json").exists()


def save_case(case: dict):
    safe = re.sub(r"[^\w]", "_", case.get("case_number") or case["url"].split("/")[-1])
    path = OUTPUT_DIR / f"{safe}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(case, f, ensure_ascii=False, indent=2)
    log.info(f"Saved → {path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def run(queries=None):
    import os
    api_key = BRAVE_API_KEY or os.environ.get("BRAVE_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "BRAVE_API_KEY not set. "
            "Get a free key at https://api.search.brave.com — 2,000 queries/month free."
        )

    queries = queries or QUERIES
    all_urls: set[str] = set()

    # ── Search ──
    log.info("=== Searching via Brave Search API ===")
    for query in queries:
        found = brave_search(query, api_key)
        all_urls.update(found)
        log.info(f"Running total: {len(all_urls)} URLs")
        sleep(uniform(1, 2))  # stay well within rate limits

    log.info(f"Total unique PDFs found: {len(all_urls)}")

    # ── Download + parse ──
    for url in sorted(all_urls):
        if already_scraped(url):
            log.info(f"Skip (already scraped): {url}")
            continue

        pdf = download_pdf(url)
        if not pdf:
            continue

        text = extract_pdf_text(pdf)
        if not text:
            log.warning(f"No text extracted from {url}")
            continue

        case = parse_case(text, url)
        save_case(case)
        sleep(uniform(2, 4))

    log.info(f"Done. Cases saved to ./{OUTPUT_DIR}/")


if __name__ == "__main__":
    run()