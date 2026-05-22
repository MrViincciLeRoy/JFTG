import os
import sys
from pathlib import Path
from time import sleep

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from shorts.config import IMAGES_DIR

HF_TOKEN_2 = os.environ.get("HF_TOKEN_2", "") or os.environ.get("HF_TOKEN", "")
PEXELS_KEY = os.environ.get("PEXELS_API_KEY", "")

STYLE_PREFIX = (
    "Cinematic, dramatic, photorealistic, dark moody lighting, South African setting, "
    "9:16 vertical aspect, no text, no watermarks. Scene: "
)


def _fetch_stock_fallback(query: str, save_path: Path) -> bool:
    if not PEXELS_KEY:
        return False
    try:
        import requests
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": PEXELS_KEY},
            params={"query": query[:100], "per_page": 1, "orientation": "portrait"},
            timeout=15,
        )
        r.raise_for_status()
        photos = r.json().get("photos", [])
        if not photos:
            return False
        img_url = photos[0]["src"]["large2x"]
        img_r = requests.get(img_url, stream=True, timeout=30)
        img_r.raise_for_status()
        with open(save_path, "wb") as f:
            for chunk in img_r.iter_content(8192):
                f.write(chunk)
        return True
    except Exception:
        return False


def generate_images(story: dict, case: dict = None, output_dir: str = None) -> list[str]:
    if not HF_TOKEN_2:
        raise RuntimeError("HF_TOKEN_2 not set.")

    from huggingface_hub import InferenceClient
    client = InferenceClient(provider="auto", api_key=HF_TOKEN_2)

    prompts = story.get("image_prompts", [])
    if not prompts:
        raise ValueError("No image_prompts in story.")

    character_desc = ""
    if case:
        from shorts.stages.character import extract_character
        char = extract_character(story, case)
        character_desc = char["description"]

    slug = story.get("title", "scene").replace(" ", "_")[:40]
    save_dir = Path(output_dir or IMAGES_DIR) / slug
    save_dir.mkdir(parents=True, exist_ok=True)

    saved_paths = []

    for i, prompt in enumerate(prompts):
        char_infix = f"Main character — {character_desc}. " if character_desc else ""
        full_prompt = STYLE_PREFIX + char_infix + prompt
        img_path = save_dir / f"scene_{i + 1:02d}.png"
        generated = False

        for attempt in range(4):
            try:
                image = client.text_to_image(
                    full_prompt,
                    model="black-forest-labs/FLUX.1-schnell",
                )
                image.save(str(img_path))
                saved_paths.append(str(img_path))
                print(f"[IMG] Scene {i + 1} saved → {img_path}")
                generated = True
                sleep(2)
                break
            except Exception as e:
                msg = str(e)
                if "429" in msg or "rate" in msg.lower():
                    sleep(30)
                elif "503" in msg or "loading" in msg.lower():
                    sleep(20)
                else:
                    sleep(5)

        if not generated:
            # Silent fallback: grab a stock image instead
            fallback_path = save_dir / f"scene_{i + 1:02d}_fallback.jpg"
            query = prompt[:80].split(",")[0].strip()
            if _fetch_stock_fallback(query, fallback_path):
                saved_paths.append(str(fallback_path))
                print(f"[IMG] Scene {i + 1} → stock fallback used")
            else:
                print(f"[IMG] Scene {i + 1} → skipped (no fallback available)")

    return saved_paths