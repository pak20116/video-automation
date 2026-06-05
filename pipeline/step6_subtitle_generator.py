import logging
import os
from dotenv import load_dotenv, dotenv_values
from pathlib import Path
from config.settings import OUTPUT_DIR, VIDEO_WIDTH, VIDEO_HEIGHT
from models.data_models import PipelineState, WordTimestamp

logger = logging.getLogger(__name__)

_SENTENCE_END = set('.?!。？！')
_ENV_FILE = Path(__file__).parent.parent / ".env"

_ASS_HEADER = """\
[Script Info]
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Malgun Gothic,{fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2.5,1,2,10,10,50,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _read_env_int(key: str, default: int) -> int:
    """Read integer value directly from .env file, bypassing cached os.environ."""
    vals = dotenv_values(_ENV_FILE)
    raw = vals.get(key)
    if raw is not None:
        try:
            return int(raw)
        except ValueError:
            pass
    return int(os.getenv(key, str(default)))


def _ms_to_ass_time(ms: int) -> str:
    ms = max(ms, 0)
    h = ms // 3600000
    m = (ms % 3600000) // 60000
    s = (ms % 60000) // 1000
    cs = (ms % 1000) // 10
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _is_sentence_end(word: str) -> bool:
    return bool(word) and word[-1] in _SENTENCE_END


def _group_into_lines(word_timestamps: list[WordTimestamp], max_words: int) -> list[list[WordTimestamp]]:
    groups: list[list[WordTimestamp]] = []
    current: list[WordTimestamp] = []

    for wt in word_timestamps:
        current.append(wt)
        if _is_sentence_end(wt.word) or len(current) >= max_words:
            groups.append(current[:])
            current = []

    if current:
        groups.append(current)

    return groups


def generate_subtitles(state: PipelineState) -> PipelineState:
    """단어 타임스탬프 기반 ASS 자막 생성 (맑은 고딕, 하단 중앙)."""
    if not state.word_timestamps:
        logger.warning("word_timestamps가 없습니다. 자막 없이 진행합니다.")
        subtitle_path = OUTPUT_DIR / "subtitles.ass"
        # Write a valid (but empty) ASS file so FFmpeg/libass doesn't crash
        empty_ass = _ASS_HEADER.format(
            width=VIDEO_WIDTH,
            height=VIDEO_HEIGHT,
            fontsize=_read_env_int("SUBTITLE_FONT_SIZE", 24),
        )
        subtitle_path.write_text(empty_ass, encoding="utf-8-sig")
        state.subtitle_path = str(subtitle_path)
        return state

    # Read settings directly from .env to always get the latest values
    max_words = _read_env_int("SUBTITLE_WORDS_PER_LINE", 5)
    font_size = _read_env_int("SUBTITLE_FONT_SIZE", 24)
    logger.info(f"  SUBTITLE_WORDS_PER_LINE={max_words}, SUBTITLE_FONT_SIZE={font_size}")

    groups = _group_into_lines(state.word_timestamps, max_words)

    header = _ASS_HEADER.format(
        width=VIDEO_WIDTH,
        height=VIDEO_HEIGHT,
        fontsize=font_size,
    )
    dialogue_lines: list[str] = []

    for i, group in enumerate(groups):
        start_ms = group[0].start_ms

        # Extend end time to the next group's start to eliminate silence gaps
        if i + 1 < len(groups):
            end_ms = groups[i + 1][0].start_ms - 1
        else:
            end_ms = group[-1].end_ms + 800  # linger 0.8s after last word

        # Safety: end must be after start
        end_ms = max(end_ms, start_ms + 100)

        start = _ms_to_ass_time(start_ms)
        end   = _ms_to_ass_time(end_ms)
        text  = " ".join(wt.word for wt in group)
        dialogue_lines.append(
            f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}"
        )

    ass_content = header + "\n".join(dialogue_lines)
    subtitle_path = OUTPUT_DIR / "subtitles.ass"
    subtitle_path.write_text(ass_content, encoding="utf-8-sig")

    state.subtitle_path = str(subtitle_path)
    logger.info(f"  Subtitles saved: {subtitle_path.name} ({len(dialogue_lines)} entries)")
    return state
