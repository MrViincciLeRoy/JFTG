import os

HF_TOKEN = os.environ.get("HF_TOKEN", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

HF_ROUTER_BASE = "https://router.huggingface.co/v1"
STORY_MODEL = "meta-llama/Llama-3.3-70B-Instruct"

GEMINI_IMAGE_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-preview-image-generation:generateContent"

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920

CASES_DIR = "cases"
OUTPUT_DIR = "output"
STORIES_DIR = f"{OUTPUT_DIR}/stories"
AUDIO_DIR = f"{OUTPUT_DIR}/audio"
IMAGES_DIR = f"{OUTPUT_DIR}/images"
VIDEOS_DIR = f"{OUTPUT_DIR}/videos"