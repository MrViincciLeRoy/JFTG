import os
import re
import sys
import random
import shutil
from pathlib import Path
from time import sleep

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from shorts.config import IMAGES_DIR

PEXELS_KEY = os.environ.get("PEXELS_API_KEY", "")
PEXELS_HEADERS = {"Authorization": PEXELS_KEY}

REQUEST_DELAY = 3.5


def _simplify_prompt(prompt: str) -> str:
    noise = [
        r"^a dark and gritty\s+", r"^a map of\s+", r"^a reenactment of\s+",
        r"^a dramatic\s+", r"^a somber\s+", r"^cinematic[,\s]+",
        r"^dramatic[,\s]+", r"^photorealistic[,\s]+",
        r"\s+with a gunshot sound effect$", r"\s+with actors and special effects$",
        r"\s+with the judge banging his gavel$",
        r"\s+with .+ sitting in the corner.+$",
        r"\s+marking the location of the crime$",
        r"\s+south african setting.*$",
        r"\s+9:16 vertical aspect.*$",
        r"\s+no text.*$",
    ]
    result = prompt.lower().strip()
    for pat in noise:
        result = re.sub(pat, "", result, flags=re.I).strip()
    result = result.rstrip(".,;:")
    return result.strip() or prompt[:40]


def _get_photos(query: str, per_page: int = 3) -> list[str]:
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers=PEXELS_HEADERS,
            params={"query": query, "per_page": per_page, "orientation": "portrait"},
            timeout=15,
        )
        r.raise_for_status()
        return [p["src"]["large2x"] for p in r.json().get("photos", [])]
    except Exception as e:
        print(f"[STOCK] Photo fetch failed ({query}): {e}")
        return []


def _download(url: str, path: Path) -> bool:
    try:
        r = requests.get(url, stream=True, timeout=30)
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"[STOCK] Download failed: {e}")
        return False


def fetch_stock_for_story(story: dict, ai_image_paths: list[str], output_dir: str = None) -> dict:
    if not PEXELS_KEY:
        raise RuntimeError("PEXELS_API_KEY not set.")

    prompts = story.get("image_prompts", [])
    slug = story.get("title", "story").replace(" ", "_")[:40]
    base_dir = Path(output_dir or IMAGES_DIR) / slug / "stock"
    base_dir.mkdir(parents=True, exist_ok=True)

    result = {}

    for i, prompt in enumerate(prompts):
        scene_key = f"scene_{i + 1}"
        scene_dir = base_dir / scene_key
        scene_dir.mkdir(exist_ok=True)

        query = _simplify_prompt(prompt)
        print(f"[STOCK] {scene_key}: '{query}'")

        sleep(REQUEST_DELAY)
        photo_urls = _get_photos(query, per_page=3)
        photo_paths = []
        for j, url in enumerate(photo_urls):
            p = scene_dir / f"stock_photo_{j + 1}.jpg"
            if _download(url, p):
                photo_paths.append(str(p))
                print(f"         Photo {j + 1} saved")

        # Insert AI image at a random slot among the stock photos
        if i < len(ai_image_paths) and ai_image_paths[i]:
            ai_src = Path(ai_image_paths[i])
            if ai_src.exists():
                ai_dst = scene_dir / f"ai_scene_{i + 1:02d}.png"
                shutil.copy2(str(ai_src), str(ai_dst))
                insert_at = random.randint(0, len(photo_paths))
                photo_paths.insert(insert_at, str(ai_dst))
                print(f"         AI image inserted at slot {insert_at + 1}/{len(photo_paths)}")

        result[scene_key] = {
            "query": query,
            "photos": photo_paths,
        }

    return result