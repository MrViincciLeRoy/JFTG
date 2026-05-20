# SAFLII Crime Case Scraper

Scrapes SA High Court murder/violent crime judgments from SAFLII. Uses DuckDuckGo for search and Tor for downloading PDFs (bypasses SAFLII's IP block).

## Setup

```bash
pip install playwright pdfplumber requests fake-useragent
playwright install chromium

# Install Tor (Linux/WSL)
sudo apt install tor
sudo service tor start
```

## Run

```bash
python scraper.py
```

Cases save to `./cases/` as JSON files.

## Why this combo?

| Task | Tool | Why |
|---|---|---|
| Search | DuckDuckGo | Google blocks Tor and rate-limits bots |
| Download PDFs | Tor SOCKS5 | SAFLII blocks datacenter IPs — Tor exit nodes bypass this |
| Fallback | Playwright browser | If Tor isn't running, uses your local browser session |

## Custom queries

Edit `DORK_QUERIES` in `scraper.py`:

```python
DORK_QUERIES = [
    'site:saflii.org "Western Cape" "serial killer" filetype:pdf',
    'site:saflii.org "femicide" "South Africa" "convicted" filetype:pdf',
]
```

## Tor on Windows

Install the Tor Browser, it runs a SOCKS5 proxy on port 9150 by default.
Change `TOR_PROXY` in scraper.py to: `socks5://127.0.0.1:9150`

## Output per case

```json
{
  "url": "...",
  "case_number": "CC47/2024",
  "court": "Gauteng Division, Pretoria",
  "accused": "PRINCE AMUKELANI MALULEKA",
  "charges": ["murder"],
  "verdict": "Guilty",
  "sentence": "life imprisonment",
  "province": "Gauteng",
  "summary": "...",
  "full_text": "..."
}
```
