import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY is not set. Copy .env.example to .env and fill in your API keys.")
if not ELEVENLABS_API_KEY:
    raise ValueError("ELEVENLABS_API_KEY is not set. Copy .env.example to .env and fill in your API keys.")

GEMINI_TEXT_MODEL = "gemini-2.5-flash"
GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image"

ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
ELEVENLABS_MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5")

FFMPEG_PATH = os.getenv("FFMPEG_PATH", "ffmpeg")

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
IMAGES_DIR = OUTPUT_DIR / "images"
AUDIO_DIR = OUTPUT_DIR / "audio"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

VIDEO_WIDTH = int(os.getenv("VIDEO_WIDTH", "1920"))
VIDEO_HEIGHT = int(os.getenv("VIDEO_HEIGHT", "1080"))
VIDEO_FPS = int(os.getenv("VIDEO_FPS", "30"))
SUBTITLE_FONT_SIZE = int(os.getenv("SUBTITLE_FONT_SIZE", "48"))

IMAGE_STYLE = os.getenv("IMAGE_STYLE", "photorealistic, cinematic lighting")
CHARACTER_DESCRIPTION = os.getenv("CHARACTER_DESCRIPTION", "")
