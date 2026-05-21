import json
import re
import requests
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from shorts.config import HF_TOKEN, HF_API_URL

SYSTEM_PROMPT = (
    "You are a YouTube Shorts scriptwriter specialising in South African true crime. "
    "You write gripping, fast-paced narration scripts based on real court cases. "
    "Your tone is dramatic, clear, and engaging — like a true crime podcast for a young South African audience. "
    "Always respond with valid JSON only. No markdown, no code fences, no extra text."
)


def _build_prompt(case: dict) -> str:
    charges = ", ".join(case["charges"]) if case["charges"] else "unknown"
    accused = case["accused"] or "the accused"
    court = case["court"] or "a South African High Court"
    text_snippet = case["full_text"][:3500]

    return f"""Turn this South African court case into a YouTube Shorts script.

Case info:
- Accused: {accused}
- Court: {court}
- Province: {case["province"]}
- Charges: {charges}
- Verdict: {case["verdict"]}
- Sentence: {case["sentence"]}

Full case text:
{text_snippet}

Return ONLY this JSON — no extra text, no markdown:
{{
  "title": "short punchy video title, max 8 words",
  "hook": "1-2 sentences that grab attention in the first 3 seconds, start with something shocking",
  "background": "2-3 sentences covering who the people are and where this happened",
  "incident": "3-4 sentences describing exactly what happened",
  "climax": "2-3 sentences on the most dramatic turning point or twist in the case",
  "verdict": "2-3 sentences on what the court decided and the final sentence",
  "narration": "the full script stitched together, written to be read aloud in 60-90 seconds",
  "image_prompts": [
    "cinematic image prompt for the hook scene",
    "cinematic image prompt for the background scene",
    "cinematic image prompt for the incident scene",
    "cinematic image prompt for the climax scene",
    "cinematic image prompt for the verdict scene"
  ]
}}"""


def structure_story(case: dict) -> dict:
    if not HF_TOKEN:
        raise RuntimeError("HF_TOKEN is not set.")

    headers = {
        "Authorization": f"Bearer {HF_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "microsoft/Phi-3-mini-4k-instruct",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_prompt(case)},
        ],
        "max_tokens": 1500,
        "temperature": 0.75,
    }

    response = requests.post(HF_API_URL, headers=headers, json=payload, timeout=180)
    response.raise_for_status()

    raw = response.json()["choices"][0]["message"]["content"].strip()

    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"^```\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError(f"Could not parse JSON from Phi-3 response:\n{raw}")
