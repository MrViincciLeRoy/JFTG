import json
from pathlib import Path


def extract(json_path: str) -> dict:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    charges = data.get("charges", [])
    sentence = data.get("sentence", "").replace("\n", " ").strip()
    full_text = data.get("full_text", "").strip()

    if not full_text:
        raise ValueError(f"No full_text found in {json_path}")

    return {
        "source_file": str(Path(json_path).name),
        "url": data.get("url", ""),
        "case_number": data.get("case_number", ""),
        "court": data.get("court", ""),
        "accused": data.get("accused", ""),
        "charges": charges,
        "verdict": data.get("verdict", ""),
        "sentence": sentence,
        "province": data.get("province", ""),
        "full_text": full_text,
    }
