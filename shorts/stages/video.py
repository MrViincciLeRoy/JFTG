import os
import sys
import json
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from shorts.config import VIDEOS_DIR, VIDEO_WIDTH, VIDEO_HEIGHT

MAX_IMAGE_DURATION = 3.0  # hard cap per image
MIN_IMAGE_DURATION = 1.5  # minimum so it's not too flashy
FPS = 25


def _get_audio_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def _scale_filter(extra: str = "") -> str:
    base = (
        f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,fps={FPS}"
    )
    return base + ("," + extra if extra else "")


def _collect_images(image_paths: list[str], stock_media: dict | None) -> list[str]:
    """
    Collect all image paths in scene order.
    If stock_media provided: use per-scene photos (which already include AI images).
    Otherwise fall back to image_paths.
    Only .jpg/.jpeg/.png — no videos.
    """
    valid_exts = {".jpg", ".jpeg", ".png", ".webp"}
    images = []

    if stock_media:
        for scene_key in sorted(stock_media.keys()):
            for p in stock_media[scene_key].get("photos", []):
                if Path(p).exists() and Path(p).suffix.lower() in valid_exts:
                    images.append(p)
    else:
        for p in image_paths:
            if Path(p).exists() and Path(p).suffix.lower() in valid_exts:
                images.append(p)

    return images


def _calculate_duration_per_image(num_images: int, audio_duration: float) -> float:
    """
    Distribute audio evenly across images.
    Result is clamped between MIN_IMAGE_DURATION and MAX_IMAGE_DURATION.
    If images * MAX would overshoot audio, we reduce.
    If images * MIN would undershoot audio, we'll loop images (handled in assemble).
    """
    if num_images == 0:
        return MAX_IMAGE_DURATION
    even = audio_duration / num_images
    return max(MIN_IMAGE_DURATION, min(MAX_IMAGE_DURATION, even))


def _render_image_segment(src: str, dur: float, out: str):
    frames = max(1, int(dur * FPS))
    zoom_step = 0.0006
    vf = _scale_filter(
        f"zoompan=z='min(zoom+{zoom_step},1.25)':d={frames}:"
        f"s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={FPS}"
    )
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-t", str(dur),
        "-i", src,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-an",
        "-pix_fmt", "yuv420p",
        out,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _write_concat(segment_paths: list[str], tmp_dir: str) -> str:
    txt = os.path.join(tmp_dir, "concat.txt")
    with open(txt, "w") as f:
        for p in segment_paths:
            f.write(f"file '{p}'\n")
    return txt


def _concat_and_mux(concat_txt: str, audio_path: str, audio_duration: float, output_path: str):
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_txt,
        "-i", audio_path,
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(audio_duration),
        "-pix_fmt", "yuv420p",
        output_path,
    ]
    subprocess.run(cmd, check=True)


def assemble_video(
    image_paths: list[str],
    audio_path: str,
    story: dict,
    stock_media: dict = None,
    output_path: str = None,
) -> str:
    if not Path(audio_path).exists():
        raise FileNotFoundError(f"Audio not found: {audio_path}")

    Path(VIDEOS_DIR).mkdir(parents=True, exist_ok=True)
    slug = story.get("title", "video").replace(" ", "_")[:40]
    if not output_path:
        output_path = str(Path(VIDEOS_DIR) / f"{slug}.mp4")

    audio_duration = _get_audio_duration(audio_path)
    print(f"[VIDEO] Audio duration: {audio_duration:.2f}s")

    images = _collect_images(image_paths, stock_media)
    if not images:
        raise ValueError("No images found to assemble.")

    dur_per_image = _calculate_duration_per_image(len(images), audio_duration)
    total_visual = dur_per_image * len(images)
    print(f"[VIDEO] {len(images)} images @ {dur_per_image:.2f}s each = {total_visual:.2f}s visual")

    # If images don't cover the full audio, loop them (cycling through all, not repeating one)
    final_images = images[:]
    while dur_per_image * len(final_images) < audio_duration:
        final_images = final_images + images

    # Trim to just enough images to cover audio
    needed = int(audio_duration / dur_per_image) + 1
    final_images = final_images[:needed]

    print(f"[VIDEO] Rendering {len(final_images)} image segments...")

    with tempfile.TemporaryDirectory() as tmp:
        segments = []
        for i, src in enumerate(final_images):
            # Last image might need trimming so we don't overshoot audio
            remaining = audio_duration - i * dur_per_image
            actual_dur = min(dur_per_image, remaining)
            if actual_dur <= 0:
                break
            out = os.path.join(tmp, f"seg_{i:04d}.mp4")
            _render_image_segment(src, actual_dur, out)
            segments.append(out)
            if (i + 1) % 5 == 0:
                print(f"         {i + 1}/{len(final_images)} done")

        concat_txt = _write_concat(segments, tmp)
        _concat_and_mux(concat_txt, audio_path, audio_duration, output_path)

    print(f"[VIDEO] Saved → {output_path}")
    return output_path