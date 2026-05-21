import os
import sys
import base64
import requests
from pathlib import Path
from time import sleep

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from shorts.config import IMAGES_DIR

HF_TOKEN = os.environ.get("HF_TOKEN", "")
HF_IMAGE_URL = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell"

STYLE_PREFIX = (
    "Cinematic, dramatic, photorealistic, dark moody lighting, South African setting, "
    "9:16 vertical aspect, no text, no watermarks. Scene: "
)


def generate_images(story: dict, case: dict = None, output_dir: str = None) -> list[str]:
    if not HF_TOKEN:
        raise RuntimeError("HF_TOKEN is not set.")

    prompts = story.get("image_prompts", [])
    if not prompts:
        raise ValueError("No image_prompts found in story.")

    character_desc = ""
    if case:
        from shorts.stages.character import extract_character
        char = extract_character(story, case)
        character_desc = char["description"]
        print(f"      Character: {character_desc}")

    slug = story.get("title", "scene").replace(" ", "_")[:40]
    save_dir = Path(output_dir or IMAGES_DIR) / slug
    save_dir.mkdir(parents=True, exist_ok=True)

    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    saved_paths = []

    for i, prompt in enumerate(prompts):
        char_infix = f"Main character — {character_desc}. " if character_desc else ""
        full_prompt = STYLE_PREFIX + char_infix + prompt

        # retry loop for model loading / rate limit
        for attempt in range(5):
            response = requests.post(
                HF_IMAGE_URL,
                headers=headers,
                json={"inputs": full_prompt},
                timeout=120,
            )
            if response.status_code == 200:
                break
            body = response.text[:300]
            print(f"[IMG] attempt {attempt+1} status={response.status_code} {body}")
            if response.status_code == 503:
                # model loading, wait suggested time
                try:
                    wait = response.json().get("estimated_time", 20)
                except Exception:
                    wait = 20
                print(f"[IMG] model loading, waiting {wait}s...")
                sleep(wait)
            elif response.status_code == 429:
                print("[IMG] rate limited, waiting 30s...")
                sleep(30)
            else:
                response.raise_for_status()
        else:
            print(f"[IMG] scene {i+1} failed after 5 attempts, skipping.")
            continue

        img_path = save_dir / f"scene_{i + 1:02d}.png"
        img_path.write_bytes(response.content)
        saved_paths.append(str(img_path))
        print(f"[IMG] Saved scene {i + 1} → {img_path}")
        sleep(2)  # be polite to free tier

    return saved_paths