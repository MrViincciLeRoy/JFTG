import os

HF_TOKEN = os.environ.get("HF_TOKEN", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

PHI3_MODEL = "microsoft/Phi-3-mini-4k-instruct"
HF_API_URL = f"https://api-inference.huggingface.co/models/{PHI3_MODEL}/v1/chat/completions"

GEMINI_IMAGE_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-preview-image-generation:generateContent"

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920

CASES_DIR = "cases"
OUTPUT_DIR = "output"
STORIES_DIR = f"{OUTPUT_DIR}/stories"
AUDIO_DIR = f"{OUTPUT_DIR}/audio"
IMAGES_DIR = f"{OUTPUT_DIR}/images"
VIDEOS_DIR = f"{OUTPUT_DIR}/videos"
