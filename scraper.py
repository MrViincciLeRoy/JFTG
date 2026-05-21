import re, json, logging, warnings, os
from pathlib import Path
from datetime import datetime
from time import sleep
from random import uniform
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

OUTPUT_DIR = Path("cases")
OUTPUT_DIR.mkdir(exist_ok=True)

SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")
SERPAPI_URL = "https://serpapi.com/search"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.saflii.org/",
    "Accept": "text/html,application/xhtml+xml,*/*",
}

# Skip CDX entirely — just try these directly. Recent snapshots work best.
WAYBACK_TIMESTAMPS = ["20260101120000", "20250601120000", "20240601120000"]

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

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def serpapi_search(query, max_results=10):
    params = {
        "engine": "google", "q": query, "num": max_results,
        "gl": "za", "hl": "en", "api_key": SERPAPI_KEY,
    }
    try:
        r = SESSION.get(SERPAPI_URL, params=params, timeout=20)
        r.raise_for_status()
        results = r.json().get("organic_results", [])
        log.info(f"SerpAPI: {len(results)} results for {query!r}")
        urls = []
        for item in results:
            url = item.get("link", "")
            if "saflii.org" not in url:
                continue
            if url.endswith(".pdf"):
                url = url[:-4] + ".html"
            if url.endswith(".html"):
                urls.append(url)
        return urls
    except Exception as e:
        log.error(f"SerpAPI error: {e}")
        return []


def fetch_via_wayback(url):
    for ts in WAYBACK_TIMESTAMPS:
        try:
            wayback_url = f"https://web.archive.org/web/{ts}id_/{url}"
            r = SESSION.get(wayback_url, timeout=15)
            if r.status_code == 200 and len(r.text) > 500:
                log.info(f"Wayback ({ts}): {url}")
                return r.text
        except Exception:
            pass
    log.warning(f"No snapshot found: {url}")
    return None


def fetch_html(url):
    try:
        r = SESSION.get(url, timeout=12)
        if r.status_code == 200:
            log.info(f"Direct: {url}")
            return r.text
        log.warning(f"Direct {r.status_code}: {url}")
    except Exception as e:
        log.warning(f"Direct error ({e}): {url}")
    return fetch_via_wayback(url)


def parse_text_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    lines = [l for l in soup.get_text(separator="\n", strip=True).splitlines() if l.strip()]
    return "\n".join(lines)


def parse_case(text, url):
    case = {
        "url": url,
        "scraped_at": datetime.now().isoformat(),
        "case_number": "", "court": "", "date": "",
        "accused": "", "charges": [], "verdict": "",
        "sentence": "", "province": "",
        "full_text": text, "summary": "",
    }

    m = re.search(r"CASE\s*NO[:\.]?\s*([A-Z]{1,4}[\s\d]+/\d{4})", text, re.I)
    if m:
        case["case_number"] = m.group(1).strip()

    for c in [
        "Gauteng Division, Pretoria", "Gauteng Local Division, Johannesburg",
        "Western Cape High Court", "KwaZulu-Natal High Court",
        "Eastern Cape High Court", "Supreme Court of Appeal",
    ]:
        if c.lower() in text.lower():
            case["court"] = c
            break

    for p in ["Gauteng", "Western Cape", "KwaZulu-Natal", "Eastern Cape",
              "Limpopo", "Mpumalanga", "Northern Cape", "Free State", "North West"]:
        if p.lower() in text.lower():
            case["province"] = p
            break

    m = re.search(r"\band\b\s*\n+([A-Z][A-Z\s]+?)\s+ACCUSED", text)
    if m:
        case["accused"] = m.group(1).strip()

    m = re.search(r"DATE[:\s]+(\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4})", text, re.I)
    if m:
        case["date"] = m.group(1)

    for ch in ["murder", "rape", "kidnapping", "robbery", "attempted murder",
               "assault", "human trafficking", "femicide", "fraud"]:
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


def case_slug(url):
    return re.sub(r"[^\w]", "_", url.rstrip("/").split("/")[-1].replace(".html", ""))


def already_scraped(url):
    return (OUTPUT_DIR / f"{case_slug(url)}.json").exists()


def save_case(case, url):
    slug = re.sub(r"[^\w]", "_", case.get("case_number") or case_slug(url))
    path = OUTPUT_DIR / f"{slug}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(case, f, ensure_ascii=False, indent=2)
    log.info(f"Saved -> {path}")


def process_url(url):
    if already_scraped(url):
        log.info(f"Skip (cached): {url}")
        return
    html = fetch_html(url)
    if not html:
        return
    text = parse_text_from_html(html)
    if not text:
        return
    case = parse_case(text, url)
    save_case(case, url)
    sleep(uniform(1, 2))


def run():
    if not SERPAPI_KEY:
        raise RuntimeError("SERPAPI_KEY not set.")

    all_urls = set()
    for query in QUERIES:
        all_urls.update(serpapi_search(query))
        log.info(f"Total URLs so far: {len(all_urls)}")
        sleep(uniform(1, 2))

    to_fetch = [u for u in sorted(all_urls) if not already_scraped(u)]
    log.info(f"Unique cases to process: {len(to_fetch)}")

    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(process_url, url): url for url in to_fetch}
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                log.error(f"Error processing {futures[f]}: {e}")

    log.info(f"Done. Cases in ./{OUTPUT_DIR}/")


if __name__ == "__main__":
    run()