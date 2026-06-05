import json
from pathlib import Path
from config.settings import OUTPUT_DIR, IMAGES_DIR, AUDIO_DIR, CLIPS_DIR


def ensure_output_dirs() -> None:
    for d in [OUTPUT_DIR, IMAGES_DIR, AUDIO_DIR, CLIPS_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def save_pipeline_state(state_dict: dict) -> Path:
    path = OUTPUT_DIR / "segments.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state_dict, f, indent=2, ensure_ascii=False)
    return path


def load_pipeline_state() -> dict:
    path = OUTPUT_DIR / "segments.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_image_path(segment_index: int) -> Path:
    return IMAGES_DIR / f"segment_{segment_index:03d}.png"


def get_audio_path() -> Path:
    return AUDIO_DIR / "full_tts.mp3"


def get_clip_path(segment_index: int) -> Path:
    return CLIPS_DIR / f"segment_{segment_index:03d}.mp4"
