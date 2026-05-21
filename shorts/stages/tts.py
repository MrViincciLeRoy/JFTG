import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from shorts.config import AUDIO_DIR


def generate_audio(story: dict, output_path: str = None) -> str:
    try:
        from kokoro import KPipeline
    except ImportError:
        raise ImportError("Install kokoro: pip install kokoro>=0.9.4 soundfile")

    import soundfile as sf
    import numpy as np

    narration = story.get("narration", "")
    if not narration:
        raise ValueError("No narration found in story.")

    Path(AUDIO_DIR).mkdir(parents=True, exist_ok=True)

    if not output_path:
        slug = story.get("title", "audio").replace(" ", "_")[:40]
        output_path = str(Path(AUDIO_DIR) / f"{slug}.wav")

    pipeline = KPipeline(lang_code="a")

    audio_chunks = []
    for _, _, audio in pipeline(narration, voice="af_heart", speed=1.0):
        audio_chunks.append(audio)

    full_audio = np.concatenate(audio_chunks)
    sf.write(output_path, full_audio, 24000)

    print(f"[TTS] Audio saved → {output_path}")
    return output_path
