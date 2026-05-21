import os
import sys
import json
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from shorts.config import VIDEOS_DIR, VIDEO_WIDTH, VIDEO_HEIGHT


def _get_audio_duration(audio_path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", audio_path],
        capture_output=True, text=True, check=True
    )
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


def assemble_video(image_paths: list[str], audio_path: str, story: dict, output_path: str = None) -> str:
    if not image_paths:
        raise ValueError("No images provided.")
    if not Path(audio_path).exists():
        raise FileNotFoundError(f"Audio not found: {audio_path}")

    Path(VIDEOS_DIR).mkdir(parents=True, exist_ok=True)

    slug = story.get("title", "video").replace(" ", "_")[:40]
    if not output_path:
        output_path = str(Path(VIDEOS_DIR) / f"{slug}.mp4")

    total_duration = _get_audio_duration(audio_path)
    per_image = total_duration / len(image_paths)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for img_path in image_paths:
            abs_path = str(Path(img_path).resolve())
            f.write(f"file '{abs_path}'\n")
            f.write(f"duration {per_image:.3f}\n")
        f.write(f"file '{str(Path(image_paths[-1]).resolve())}'\n")
        concat_file = f.name

    scale_filter = (
        f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,"
        f"zoompan=z='min(zoom+0.0015,1.5)':d={int(per_image * 25)}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps=25"
    )

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_file,
        "-i", audio_path,
        "-vf", scale_filter,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        "-pix_fmt", "yuv420p",
        output_path,
    ]

    subprocess.run(cmd, check=True)
    Path(concat_file).unlink(missing_ok=True)

    print(f"[VIDEO] Saved → {output_path}")
    return output_path
