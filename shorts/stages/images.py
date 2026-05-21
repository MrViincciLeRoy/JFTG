import os
import sys
from pathlib import Path
from time import sleep

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from shorts.config import IMAGES_DIR

HF_TOKENS = [
    t for t in [
        os.environ.get("HF_TOKEN", ""),
        os.environ.get("HF_TOKEN_2", ""),
    ] if t
]

STYLE_PREFIX = (
    "Cinematic, dramatic, photorealistic, dark moody lighting, South African setting, "
    "9:16 vertical aspect, no text, no watermarks. Scene: "
)


def _get_client(token: str):
    from huggingface_hub import InferenceClient
    return InferenceClient(provider="auto", api_key=token)


def generate_images(story: dict, case: dict = None, output_dir: str = None) -> list[str]:
    if not HF_TOKENS:
        raise RuntimeError("No HF_TOKEN or HF_TOKEN_2 set.")

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
        token = HF_TOKENS[i % len(HF_TOKENS)]
        client = _get_client(token)

        char_infix = f"Main character — {character_desc}. " if character_desc else ""
        full_prompt = STYLE_PREFIX + char_infix + prompt

        for attempt in range(4):
            try:
                image = client.text_to_image(
                    full_prompt,
                    model="black-forest-labs/FLUX.1-schnell",
                )
                img_path = save_dir / f"scene_{i + 1:02d}.png"
                image.save(str(img_path))
                saved_paths.append(str(img_path))
                print(f"[IMG] Saved scene {i + 1} → {img_path}")
                sleep(2)
                break
            except Exception as e:
                msg = str(e)
                print(f"[IMG] attempt {attempt+1} failed: {msg[:200]}")
                if "rate" in msg.lower() or "429" in msg:
                    sleep(30)
                elif "loading" in msg.lower() or "503" in msg:
                    sleep(20)
                else:
                    sleep(5)
        else:
            print(f"[IMG] scene {i+1} skipped after 4 attempts.")

    return saved_paths