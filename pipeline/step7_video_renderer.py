import logging
import subprocess
from pathlib import Path
from config.settings import (
    FFMPEG_PATH,
    OUTPUT_DIR,
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
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


# ── Clip-based renderer (Veo mode) ────────────────────────────────────

def _run_ffmpeg(cmd: list[str], label: str) -> None:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg [{label}] failed (exit {result.returncode}):\n"
            f"{result.stderr[-3000:]}"
        )


def _segment_duration_s(state: PipelineState, index: int) -> float:
    segments = state.segments
    total_ms = state.total_audio_duration_ms or 0
    seg = segments[index]
    end_ms = segments[index + 1].audio_start_ms if index + 1 < len(segments) else total_ms
    return max((end_ms - (seg.audio_start_ms or 0)) / 1000.0, 0.5)


def _concatenate_clips(state: PipelineState, output_path: Path) -> None:
    """Build a silent video track by stitching Veo clips to exact segment durations."""
    segments = state.segments
    scale = (
        f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
        f"fps={VIDEO_FPS},format=yuv420p"
    )

    inputs: list[str] = []
    filter_parts: list[str] = []
    labels: list[str] = []

    for i, seg in enumerate(segments):
        dur = _segment_duration_s(state, i)
        # -stream_loop -1 loops the clip so trim always has enough frames
        inputs += ["-stream_loop", "-1", "-i", seg.video_clip_path]
        filter_parts.append(
            f"[{i}:v]trim=0:{dur:.3f},setpts=PTS-STARTPTS,{scale}[v{i}]"
        )
        labels.append(f"[v{i}]")

    n = len(segments)
    filter_parts.append(f"{''.join(labels)}concat=n={n}:v=1:a=0[vout]")

    # Write filter_complex to a temp file (avoids Windows cmd-line length limit)
    fc_path = OUTPUT_DIR / "filter_complex.txt"
    fc_path.write_text(";".join(filter_parts), encoding="utf-8")

    cmd = (
        [FFMPEG_PATH, "-y"]
        + inputs
        + [
            "-filter_complex_script", str(fc_path),
            "-map", "[vout]",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-r", str(VIDEO_FPS),
            str(output_path),
        ]
    )
    logger.info("  FFmpeg: 클립 이어붙이기...")
    _run_ffmpeg(cmd, "clip-concat")
    fc_path.unlink(missing_ok=True)


def _add_audio_subtitles(
    video_path: Path,
    audio_path: str,
    subtitle_path: str,
    output_path: Path,
) -> None:
    """Second pass: mux audio and burn subtitles onto the concatenated clip video."""
    sub_escaped = _escape_subtitle_path(subtitle_path)
    cmd = [
        FFMPEG_PATH, "-y",
        "-i", str(video_path),
        "-i", audio_path,
        "-vf", f"ass='{sub_escaped}'",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "44100",
        "-pix_fmt", "yuv420p",
        "-shortest",
        str(output_path),
    ]
    logger.info("  FFmpeg: 오디오 + 자막 합성...")
    _run_ffmpeg(cmd, "audio-subs")


def render_video_from_clips(state: PipelineState) -> PipelineState:
    """Compose final MP4 from Veo clips, TTS audio, and subtitles."""
    output_path = OUTPUT_DIR / "final_video.mp4"
    temp_path = OUTPUT_DIR / "temp_clips_concat.mp4"

    _concatenate_clips(state, temp_path)
    _add_audio_subtitles(temp_path, state.audio_path, state.subtitle_path, output_path)
    temp_path.unlink(missing_ok=True)

    state.output_video_path = str(output_path)
    logger.info(f"  Video rendered (Veo clips): {output_path.name}")
    return state


def render_video_auto(state: PipelineState) -> PipelineState:
    """Choose clip-based or image-based rendering depending on what was generated."""
    if any(s.video_clip_path for s in state.segments):
        return render_video_from_clips(state)
    return render_video(state)
