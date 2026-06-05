import logging
import subprocess
from pathlib import Path
from config.settings import (
    FFMPEG_PATH,
    OUTPUT_DIR,
    VIDEO_FPS,
    SUBTITLE_FONT_SIZE,
)
from models.data_models import PipelineState

logger = logging.getLogger(__name__)

_MIN_SEGMENT_DURATION_S = 0.5


def _build_concat_file(state: PipelineState) -> Path:
    """Build FFmpeg concat demuxer file mapping each image to its display duration.

    Each image is shown from its segment's audio_start_ms until the NEXT segment starts
    (or until total audio ends for the last segment).  This includes inter-segment
    silence gaps so the video timeline stays in sync with the audio.
    """
    lines: list[str] = []
    segments = state.segments
    total_ms = state.total_audio_duration_ms or 0

    for i, segment in enumerate(segments):
        if i + 1 < len(segments):
            end_ms = segments[i + 1].audio_start_ms
        else:
            end_ms = total_ms

        start_ms = segment.audio_start_ms or 0
        duration_s = max((end_ms - start_ms) / 1000.0, _MIN_SEGMENT_DURATION_S)

        image_posix = Path(segment.image_path).as_posix()
        lines.append(f"file '{image_posix}'")
        lines.append(f"duration {duration_s:.3f}")

    # Repeat last frame — required by FFmpeg concat demuxer to avoid black frame at end
    last_image = Path(segments[-1].image_path).as_posix()
    lines.append(f"file '{last_image}'")

    concat_path = OUTPUT_DIR / "concat_list.txt"
    concat_path.write_text("\n".join(lines), encoding="utf-8")
    return concat_path


def _escape_subtitle_path(subtitle_path: str) -> str:
    """Escape subtitle path for FFmpeg subtitles filter on Windows."""
    # FFmpeg subtitles filter requires colons in Windows drive letters to be escaped
    posix = Path(subtitle_path).as_posix()
    # Escape the drive letter colon: C:/path -> C\:/path
    if len(posix) >= 2 and posix[1] == ":":
        posix = posix[0] + "\\:" + posix[2:]
    return posix


def _build_ffmpeg_command(
    concat_path: Path,
    audio_path: str,
    subtitle_path: str,
    output_path: Path,
) -> list[str]:
    sub_escaped = _escape_subtitle_path(subtitle_path)
    # fps 필터로 프레임 먼저 확장 후 ass 적용 — concat demuxer는 이미지당 1프레임만 출력하므로
    # fps= 없이 ass= 만 쓰면 자막이 이미지 전환 시에만 바뀜
    subtitle_filter = f"fps={VIDEO_FPS},ass='{sub_escaped}'"

    return [
        FFMPEG_PATH,
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_path),
        "-i", audio_path,
        "-vf", subtitle_filter,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "44100",
        "-pix_fmt", "yuv420p",
        "-shortest",
        "-r", str(VIDEO_FPS),
        str(output_path),
    ]


def render_video(state: PipelineState) -> PipelineState:
    """Compose final MP4 from images, TTS audio, and burned-in subtitles via FFmpeg."""
    output_path = OUTPUT_DIR / "final_video.mp4"
    concat_path = _build_concat_file(state)

    cmd = _build_ffmpeg_command(
        concat_path=concat_path,
        audio_path=state.audio_path,
        subtitle_path=state.subtitle_path,
        output_path=output_path,
    )

    logger.info(f"  Running FFmpeg...")
    logger.debug(f"  Command: {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg failed (exit code {result.returncode}):\n"
            f"STDERR: {result.stderr[-3000:]}"
        )

    state.output_video_path = str(output_path)
    logger.info(f"  Video rendered: {output_path.name}")
    return state
