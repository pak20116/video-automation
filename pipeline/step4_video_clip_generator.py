import time
import logging
from pathlib import Path

from google import genai
from google.genai import types

from config.settings import (
    GEMINI_API_KEY,
    GEMINI_VIDEO_MODEL,
    VEO_CLIP_DURATION,
    CLIPS_DIR,
)
from models.data_models import PipelineState
from utils.api_helpers import with_retry

logger = logging.getLogger(__name__)
_client = genai.Client(api_key=GEMINI_API_KEY)

_POLL_INTERVAL_S = 20
_MAX_POLL_ATTEMPTS = 60  # 20 minutes max


def _build_veo_prompt(image_prompt: str) -> str:
    """Wrap the image prompt into a Veo-optimised motion prompt."""
    return (
        f"{image_prompt}. "
        "Smooth camera movement, natural motion, cinematic quality. "
        "No sudden cuts, no text overlays."
    )


@with_retry(max_attempts=2, delay_seconds=15.0)
def _generate_single_clip(prompt: str, output_path: Path) -> Path:
    """Submit a Veo job, poll until done, and save the MP4."""
    logger.info(f"    Submitting Veo job (model={GEMINI_VIDEO_MODEL})...")

    try:
        operation = _client.models.generate_videos(
            model=GEMINI_VIDEO_MODEL,
            prompt=_build_veo_prompt(prompt),
            config=types.GenerateVideosConfig(
                aspect_ratio="16:9",
                duration_seconds=VEO_CLIP_DURATION,
                number_of_videos=1,
            ),
        )
    except Exception as e:
        err = str(e)
        if "not found" in err.lower() or "INVALID_ARGUMENT" in err or "NOT_FOUND" in err:
            raise RuntimeError(
                f"Veo 모델({GEMINI_VIDEO_MODEL})을 사용할 수 없습니다. "
                "Google AI Studio에서 Veo API 접근 권한을 확인하세요: "
                "https://aistudio.google.com/\n원본 오류: " + err
            ) from e
        raise

    # Poll
    for attempt in range(_MAX_POLL_ATTEMPTS):
        if operation.done:
            break
        logger.info(f"    Veo 생성 중... ({attempt * _POLL_INTERVAL_S}s 경과)")
        time.sleep(_POLL_INTERVAL_S)
        operation = _client.operations.get(operation)
    else:
        raise RuntimeError("Veo 작업이 시간 초과되었습니다 (20분). 나중에 다시 시도하세요.")

    if hasattr(operation, "error") and operation.error and getattr(operation.error, "code", 0) != 0:
        raise RuntimeError(f"Veo API 오류: {operation.error.message}")

    generated = getattr(operation.result, "generated_videos", None)
    if not generated:
        raise RuntimeError("Veo가 영상을 반환하지 않았습니다.")

    video_file = generated[0].video
    logger.info(f"    Veo 생성 완료 — 다운로드 중...")

    # Download: try SDK first, fall back to direct URI access
    try:
        video_bytes = _client.files.download(file=video_file)
        if not isinstance(video_bytes, (bytes, bytearray)):
            video_bytes = bytes(video_bytes)
    except Exception:
        import urllib.request
        import urllib.error
        try:
            with urllib.request.urlopen(video_file.uri) as resp:
                video_bytes = resp.read()
        except urllib.error.URLError as dl_err:
            raise RuntimeError(f"Veo 클립 다운로드 실패: {dl_err}") from dl_err

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(video_bytes)
    return output_path


def generate_video_clips(state: PipelineState) -> PipelineState:
    """Generate one MP4 clip per segment using Google Veo."""
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)

    for segment in state.segments:
        output_path = CLIPS_DIR / f"segment_{segment.index:03d}.mp4"

        if output_path.exists():
            logger.info(f"  [Segment {segment.index}] 클립 존재 — 건너뜀.")
            segment.video_clip_path = str(output_path)
            continue

        logger.info(f"  [Segment {segment.index}] Veo 동영상 클립 생성 중...")
        _generate_single_clip(segment.image_prompt, output_path)
        segment.video_clip_path = str(output_path)
        logger.info(f"  [Segment {segment.index}] 저장: {output_path.name}")

    return state
