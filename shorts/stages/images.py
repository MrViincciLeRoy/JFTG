import os
import sys
import base64
import requests
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from shorts.config import GEMINI_API_KEY, GEMINI_IMAGE_URL, IMAGES_DIR, VIDEO_WIDTH, VIDEO_HEIGHT

STYLE_PREFIX = (
    "Cinematic, dramatic, photorealistic, dark moody lighting, South African setting, "
    "9:16 vertical frame, no text, no watermarks. Scene: "
)


def generate_images(story: dict, case: dict = None, output_dir: str = None) -> list[str]:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set.")

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

    saved_paths = []

    for i, prompt in enumerate(prompts):
        char_infix = f"Main character — {character_desc}. " if character_desc else ""
        full_prompt = STYLE_PREFIX + char_infix + prompt

        payload = {
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        }

        url = f"{GEMINI_IMAGE_URL}?key={GEMINI_API_KEY}"
        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()

        data = response.json()
        parts = data["candidates"][0]["content"]["parts"]

        for part in parts:
            if "inlineData" in part:
                img_data = base64.b64decode(part["inlineData"]["data"])
                img_path = save_dir / f"scene_{i + 1:02d}.png"
                img_path.write_bytes(img_data)
                saved_paths.append(str(img_path))
                print(f"[IMG] Saved scene {i + 1} → {img_path}")
                break

    return saved_paths