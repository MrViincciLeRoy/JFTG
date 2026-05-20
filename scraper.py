import os, re, json, time, random, logging, asyncio, warnings
import pdfplumber, requests
from io import BytesIO
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

OUTPUT_DIR = Path("cases")
OUTPUT_DIR.mkdir(exist_ok=True)

TOR_PROXY  = "socks5://127.0.0.1:9050"   # Windows Tor Browser: port 9150
USE_TOR    = True

DORK_QUERIES = [
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


# ── Tor check ────────────────────────────────────────────────────────────────

def is_tor_running() -> bool:
    try:
        import socks  # noqa — confirms PySocks installed
        r = requests.get(
            "https://check.torproject.org/api/ip",
            proxies={"http": TOR_PROXY, "https": TOR_PROXY},
            timeout=10, verify=False,
        )
        data = r.json()
        if data.get("IsTor"):
            log.info(f"✓ Tor active — exit IP: {data.get('IP')}")
            return True
        log.warning("Tor proxy connected but not routing through Tor")
        return False
    except ModuleNotFoundError:
        log.error("PySocks not installed. Run: pip install requests[socks] PySocks")
        return False
    except Exception as e:
        log.warning(f"Tor check failed: {e}")
        return False


# ── Helpers ───────────────────────────────────────────────────────────────────

def already_scraped(url: str) -> bool:
    safe = re.sub(r"[^\w]", "_", url.split("/")[-1])
    return (OUTPUT_DIR / f"{safe}.json").exists()


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
    if m: case["case_number"] = m.group(1)

    for c in ["Gauteng Division, Pretoria", "Gauteng Local Division, Johannesburg",
               "Western Cape High Court", "KwaZulu-Natal High Court",
               "Eastern Cape High Court", "Supreme Court of Appeal"]:
        if c.lower() in text.lower(): case["court"] = c; break

    for p in ["Gauteng","Western Cape","KwaZulu-Natal","Eastern Cape",
               "Limpopo","Mpumalanga","Northern Cape","Free State","North West"]:
        if p.lower() in text.lower(): case["province"] = p; break

    m = re.search(r"\band\b\s*\n+([A-Z][A-Z\s]+?)\s+ACCUSED", text)
    if m: case["accused"] = m.group(1).strip()

    m = re.search(r"DATE[:\s]+(\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4})", text, re.I)
    if m: case["date"] = m.group(1)

    for ch in ["murder","rape","kidnapping","robbery","attempted murder",
                "assault","human trafficking","femicide","fraud"]:
        if ch in text.lower(): case["charges"].append(ch)

    if "found guilty" in text.lower(): case["verdict"] = "Guilty"
    elif re.search(r"acquitted|not guilty", text, re.I): case["verdict"] = "Not Guilty"

    for pat in [r"life imprisonment", r"\d+\s*years['\s]?\s*imprisonment"]:
        m = re.search(pat, text, re.I)
        if m: case["sentence"] = m.group(0).strip(); break

    case["summary"] = text[:1000].replace("\n", " ").strip()
    return case


def save_case(case: dict):
    safe = re.sub(r"[^\w]", "_", case.get("case_number") or case["url"].split("/")[-1])
    path = OUTPUT_DIR / f"{safe}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(case, f, ensure_ascii=False, indent=2)
    log.info(f"Saved → {path}")


# ── Search via DuckDuckGo HTML (no JS, no CAPTCHA) ───────────────────────────
# Google detects headless Chromium on CI IPs and serves a consent/bot page.
# DuckDuckGo's plain-HTML endpoint works reliably without JavaScript.

async def ddg_search(page, query: str, max_results: int = 15) -> list[str]:
    urls = []
    try:
        encoded = requests.utils.quote(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        log.info(f"DDG search: {url}")

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(random.randint(1500, 2500))

        # ── DEBUG: dump first 3000 chars of page so we can see what arrived ──
        content = await page.content()
        log.info(f"[DEBUG] Page title: {await page.title()!r}")
        log.info(f"[DEBUG] Page HTML snippet (first 3000 chars):\n{content[:3000]}")

        # DDG HTML result links are <a class="result__a" href="...">
        # The href is a redirect: /l/?uddg=ENCODED_REAL_URL&...
        links = await page.eval_on_selector_all(
            "a.result__a",
            """els => els.map(e => {
                let h = e.href;
                // unwrap DDG redirect /l/?uddg=...
                try {
                    const u = new URL(h);
                    const uddg = u.searchParams.get('uddg');
                    if (uddg) return decodeURIComponent(uddg);
                } catch(_) {}
                return h;
            })"""
        )

        log.info(f"[DEBUG] Raw links found ({len(links)}): {links[:10]}")

        for link in links:
            if "saflii.org" in link and link.endswith(".pdf") and link not in urls:
                log.info(f"Found: {link}")
                urls.append(link)
                if len(urls) >= max_results:
                    break

        if not urls:
            log.warning(f"No saflii PDF links found for query: {query!r}")

    except Exception as e:
        log.warning(f"DDG search failed for '{query}': {e}")

    return urls


# ── PDF download via Tor ──────────────────────────────────────────────────────

async def download_via_tor(url: str) -> bytes | None:
    def _fetch():
        try:
            r = requests.get(
                url,
                proxies={"http": TOR_PROXY, "https": TOR_PROXY},
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0",
                    "Accept": "application/pdf,*/*",
                    "Referer": "https://www.saflii.org/",
                },
                timeout=30, verify=False,
            )
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                log.info(f"✓ Tor download: {url} ({len(r.content)//1024}KB)")
                return r.content
            log.warning(f"Tor got HTTP {r.status_code} for {url}")
        except Exception as e:
            log.warning(f"Tor download error: {e}")
        return None
    return await asyncio.to_thread(_fetch)


async def download_via_browser(page, url: str) -> bytes | None:
    try:
        resp = await page.request.get(
            url,
            headers={"Accept": "application/pdf,*/*", "Referer": "https://www.saflii.org/"},
            timeout=30000,
        )
        if resp.status == 200:
            body = await resp.body()
            if body[:4] == b"%PDF":
                log.info(f"✓ Browser download: {url} ({len(body)//1024}KB)")
                return body
    except Exception as e:
        log.warning(f"Browser download error: {e}")
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

async def run_async(queries=None, max_per_query=15):
    queries = queries or DORK_QUERIES

    tor_ok = False
    if USE_TOR:
        log.info("Checking Tor...")
        tor_ok = is_tor_running()
        if not tor_ok:
            log.warning("Tor unavailable — will use direct browser for downloads")
            log.warning("Linux:   sudo apt install tor && sudo service tor start")
            log.warning("Windows: open Tor Browser, change TOR_PROXY port to 9150")

    all_urls: set[str] = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="en-ZA",
        )
        page = await ctx.new_page()
        await page.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )

        # ── Search ──
        log.info("=== Searching DuckDuckGo for SAFLII cases ===")
        for query in queries:
            found = await ddg_search(page, query, max_per_query)
            all_urls.update(found)
            log.info(f"Running total: {len(all_urls)} URLs")
            await asyncio.sleep(random.uniform(3, 6))

        log.info(f"Total unique PDFs: {len(all_urls)}")

        # ── Download + parse ──
        for url in sorted(all_urls):
            if already_scraped(url):
                log.info(f"Skip: {url}")
                continue

            pdf = await download_via_tor(url) if tor_ok else await download_via_browser(page, url)
            if not pdf:
                continue

            text = extract_pdf_text(pdf)
            if not text:
                log.warning(f"No text from {url}")
                continue

            case = parse_case(text, url)
            save_case(case)
            await asyncio.sleep(random.uniform(3, 7))

        await browser.close()

    log.info(f"Done. Cases in ./{OUTPUT_DIR}/")


def run(queries=None):
    asyncio.run(run_async(queries))


if __name__ == "__main__":
    run()