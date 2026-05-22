import os
import sys
import json
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from shorts.config import VIDEOS_DIR, VIDEO_WIDTH, VIDEO_HEIGHT

PHOTO_DURATION = 2.5  # seconds per still image
FPS = 25


def _get_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def _is_video(path: str) -> bool:
    return Path(path).suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".avi"}


def _scale_filter(extra: str = "") -> str:
    base = (
        f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,fps={FPS}"
    )
    return base + ("," + extra if extra else "")


def assemble_video(
    image_paths: list[str],
    audio_path: str,
    story: dict,
    stock_media: dict = None,
    output_path: str = None,
) -> str:
    """
    Assemble final video from a mix of photos and video clips.

    If stock_media is provided (from stage 45), it uses per-scene structure:
      stock_media = {
        "scene_1": {"photos": [...], "videos": [...]},
        ...
      }
    Each scene plays its video clips (real duration) then its photos (PHOTO_DURATION each).
    The whole thing is trimmed to audio length.

    If stock_media is not provided, falls back to image_paths only (original behaviour).
    """
    if not Path(audio_path).exists():
        raise FileNotFoundError(f"Audio not found: {audio_path}")

    Path(VIDEOS_DIR).mkdir(parents=True, exist_ok=True)
    slug = story.get("title", "video").replace(" ", "_")[:40]
    if not output_path:
        output_path = str(Path(VIDEOS_DIR) / f"{slug}.mp4")

    audio_duration = _get_duration(audio_path)
    print(f"[VIDEO] Audio duration: {audio_duration:.2f}s")

    # Build ordered clip list: (path, duration, is_video)
    clips = _build_clip_list(image_paths, stock_media, audio_duration)

    if not clips:
        raise ValueError("No clips to assemble.")

    # Two-pass: segment clips to not exceed audio, then concat + mux audio
    clips = _trim_clip_list(clips, audio_duration)

    total = sum(c[1] for c in clips)
    print(f"[VIDEO] {len(clips)} clips, total visual duration: {total:.2f}s")

    # Build temp segment files, then concat
    with tempfile.TemporaryDirectory() as tmp:
        segment_paths = _render_segments(clips, tmp)
        concat_txt = _write_concat(segment_paths, tmp)
        _concat_and_mux(concat_txt, audio_path, audio_duration, output_path)

    print(f"[VIDEO] Saved → {output_path}")
    return output_path


def _build_clip_list(image_paths, stock_media, audio_duration):
    clips = []  # (path, duration, is_video)

    if stock_media:
        for scene_key in sorted(stock_media.keys()):
            scene = stock_media[scene_key]
            # Videos first in each scene
            for vp in scene.get("videos", []):
                if Path(vp).exists():
                    try:
                        dur = _get_duration(vp)
                        clips.append((vp, dur, True))
                    except Exception:
                        pass
            # Photos (includes AI image at its random slot)
            for pp in scene.get("photos", []):
                if Path(pp).exists():
                    clips.append((pp, PHOTO_DURATION, False))
    else:
        # Fallback: image_paths only
        for p in image_paths:
            if Path(p).exists():
                if _is_video(p):
                    try:
                        dur = _get_duration(p)
                        clips.append((p, dur, True))
                    except Exception:
                        pass
                else:
                    clips.append((p, PHOTO_DURATION, False))

    return clips


def _trim_clip_list(clips, audio_duration):
    """
    Keep clips until we'd exceed audio duration.
    Last clip gets truncated to fit exactly.
    If total clips are shorter than audio, loop them to fill.
    """
    total = sum(c[1] for c in clips)

    # If clips are shorter than audio, loop until we cover it
    if total < audio_duration:
        original = clips[:]
        while total < audio_duration:
            clips = clips + original
            total = sum(c[1] for c in clips)

    # Trim to audio_duration
    trimmed = []
    running = 0.0
    for path, dur, is_vid in clips:
        remaining = audio_duration - running
        if remaining <= 0:
            break
        actual = min(dur, remaining)
        trimmed.append((path, actual, is_vid))
        running += actual

    return trimmed


def _render_segments(clips, tmp_dir):
    """
    Render each clip to a normalised 1080x1920 mp4 segment.
    Photos get zoompan ken-burns effect.
    Videos get scaled/padded only.
    """
    paths = []
    for i, (src, dur, is_vid) in enumerate(clips):
        out = os.path.join(tmp_dir, f"seg_{i:04d}.mp4")
        frames = max(1, int(dur * FPS))

        if is_vid:
            vf = _scale_filter()
            cmd = [
                "ffmpeg", "-y",
                "-ss", "0", "-t", str(dur),
                "-i", src,
                "-vf", vf,
                "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                "-an",
                "-t", str(dur),
                "-pix_fmt", "yuv420p",
                out,
            ]
        else:
            zoom_step = 0.0008
            vf = _scale_filter(
                f"zoompan=z='min(zoom+{zoom_step},1.3)':d={frames}:"
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
        paths.append(out)

    return paths


def _write_concat(segment_paths, tmp_dir):
    txt = os.path.join(tmp_dir, "concat.txt")
    with open(txt, "w") as f:
        for p in segment_paths:
            f.write(f"file '{p}'\n")
    return txt


def _concat_and_mux(concat_txt, audio_path, audio_duration, output_path):
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_txt,
        "-i", audio_path,
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(audio_duration),  # hard trim to exact audio length
        "-pix_fmt", "yuv420p",
        output_path,
    ]
    subprocess.run(cmd, check=True)
