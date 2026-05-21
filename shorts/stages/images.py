import os
import sys
from pathlib import Path
from time import sleep

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from shorts.config import IMAGES_DIR

# Images use HF_TOKEN_2 exclusively — keeps it separate from LLM quota
HF_TOKEN_2 = os.environ.get("HF_TOKEN_2", "") or os.environ.get("HF_TOKEN", "")

STYLE_PREFIX = (
    "Cinematic, dramatic, photorealistic, dark moody lighting, South African setting, "
    "9:16 vertical aspect, no text, no watermarks. Scene: "
)


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
        print(f"      Character: {character_desc}")

    slug = story.get("title", "scene").replace(" ", "_")[:40]
    save_dir = Path(output_dir or IMAGES_DIR) / slug
    save_dir.mkdir(parents=True, exist_ok=True)

    saved_paths = []

    for i, prompt in enumerate(prompts):
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
                if "429" in msg or "rate" in msg.lower():
                    sleep(30)
                elif "503" in msg or "loading" in msg.lower():
                    sleep(20)
                else:
                    sleep(5)
        else:
            print(f"[IMG] scene {i+1} skipped after 4 attempts.")

    return saved_paths