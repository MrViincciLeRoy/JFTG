import argparse
import json
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shorts.config import CASES_DIR, STORIES_DIR
from shorts.stages.extract import extract
from shorts.stages.story import structure_story


def already_processed(slug: str, stories_dir: str) -> bool:
    return (Path(stories_dir) / f"{slug}_story.json").exists()


def save_story(story: dict, slug: str, stories_dir: str) -> str:
    Path(stories_dir).mkdir(parents=True, exist_ok=True)
    out = Path(stories_dir) / f"{slug}_story.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(story, f, indent=2, ensure_ascii=False)
    return str(out)


def run_pipeline(json_path: str, stories_dir: str, stages: list[int]) -> dict:
    result = {"file": json_path, "status": "ok", "error": None}

    try:
        print(f"\n{'='*60}")
        print(f"Processing: {json_path}")

        print("[1/5] Extracting case data...")
        case = extract(json_path)
        print(f"      Charges : {case['charges']}")
        print(f"      Verdict : {case['verdict']}")
        print(f"      Sentence: {case['sentence']}")

        story = None
        audio_path = None
        image_paths = []

        # Stage 2 ? story (uses HF_TOKEN via openai client)
        if 2 in stages:
            slug = Path(json_path).stem
            story_path = Path(stories_dir) / f"{slug}_story.json"
            if story_path.exists():
                with open(story_path, "r", encoding="utf-8") as f:
                    story = json.load(f)
                print(f"[2/5] Loaded existing story.")
            else:
                print("[2/5] Structuring story with LLM...")
                story = structure_story(case)
                save_story(story, slug, stories_dir)
                print(f"      Title : {story.get('title')}")
            result["story"] = story

        # Stage 3 ? TTS audio (kokoro, male voice, no token needed)
        if 3 in stages:
            if not story:
                raise ValueError("Stage 3 needs stage 2.")
            from shorts.stages.tts import generate_audio
            print("[3/5] Generating audio with Kokoro (male voice)...")
            audio_path = generate_audio(story)
            result["audio"] = audio_path

        # Stage 4 ? images (uses HF_TOKEN_2 exclusively)
        if 4 in stages:
            if not story:
                raise ValueError("Stage 4 needs stage 2.")
            from shorts.stages.images import generate_images
            print("[4/5] Generating images with FLUX (HF_TOKEN_2)...")
            image_paths = generate_images(story, case=case)
            result["images"] = image_paths

        # Stage 5 ? video assembly (needs audio + images)
        if 5 in stages:
            if not audio_path or not image_paths:
                raise ValueError("Stage 5 needs stages 3 and 4.")
            from shorts.stages.video import assemble_video
            print("[5/5] Assembling video with FFmpeg...")
            video_path = assemble_video(image_paths, audio_path, story)
            result["video"] = video_path
            print(f"      Video : {video_path}")

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        print(f"      ERROR: {e}")

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases-dir", default=CASES_DIR)
    parser.add_argument("--stories-dir", default=STORIES_DIR)
    parser.add_argument("--stages", default="1,2,3,4,5")
    parser.add_argument("--file", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    stages = [int(s.strip()) for s in args.stages.split(",")]

    if args.file:
        files = [Path(args.file)]
    else:
        files = sorted(Path(args.cases_dir).glob("*.json"))
        if not files:
            print(f"No JSON files in {args.cases_dir}")
            sys.exit(1)
        print(f"Found {len(files)} case(s) in {args.cases_dir}")

    if args.limit > 0:
        files = files[:args.limit]
        print(f"Limiting to {args.limit} case(s)")

    results = {"ok": 0, "skipped": 0, "error": 0}

    for json_path in files:
        slug = Path(json_path).stem
        if not args.force and 2 in stages and already_processed(slug, args.stories_dir) and max(stages) <= 2:
            print(f"Skip (done): {json_path}")
            results["skipped"] += 1
            continue

        result = run_pipeline(str(json_path), args.stories_dir, stages)
        results[result["status"]] = results.get(result["status"], 0) + 1

    print(f"\n{'='*60}")
    print(f"Done. OK: {results['ok']} | Skipped: {results['skipped']} | Errors: {results['error']}")


if __name__ == "__main__":
    main()