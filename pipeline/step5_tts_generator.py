import asyncio
import base64
import logging
from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings
from config.settings import (
    ELEVENLABS_API_KEY,
    ELEVENLABS_VOICE_ID,
    ELEVENLABS_MODEL_ID,
    TTS_PROVIDER,
    EDGE_TTS_VOICE,
)
from models.data_models import PipelineState, WordTimestamp
from utils.api_helpers import with_retry
from utils.file_helpers import get_audio_path

logger = logging.getLogger(__name__)
_el_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)


@with_retry(max_attempts=6, delay_seconds=5.0)
def _call_tts_with_timestamps(text: str) -> dict:
    """Call ElevenLabs TTS with character-level timestamp alignment."""
    response = _el_client.text_to_speech.convert_with_timestamps(
        voice_id=ELEVENLABS_VOICE_ID,
        text=text,
        model_id=ELEVENLABS_MODEL_ID,
        voice_settings=VoiceSettings(
            stability=0.5,
            similarity_boost=0.75,
            style=0.0,
            use_speaker_boost=True,
        ),
    )
    return response


def _parse_alignment_to_words(alignment) -> list[WordTimestamp]:
    """Convert character-level ElevenLabs alignment to word-level timestamps."""
    # Support both dict (old SDK) and object (SDK 2.x)
    if hasattr(alignment, "characters"):
        chars = alignment.characters
        starts = alignment.character_start_times_seconds
        ends = alignment.character_end_times_seconds
    else:
        chars = alignment["characters"]
        starts = alignment["character_start_times_seconds"]
        ends = alignment["character_end_times_seconds"]

    words: list[WordTimestamp] = []
    current_word = ""
    word_start: float | None = None
    word_end: float | None = None

    for i, char in enumerate(chars):
        if char in (" ", "\n", "\t"):
            if current_word:
                words.append(WordTimestamp(
                    word=current_word,
                    start_ms=int(word_start * 1000),
                    end_ms=int(word_end * 1000),
                ))
                current_word = ""
                word_start = None
        else:
            if word_start is None:
                word_start = starts[i]
            word_end = ends[i]
            current_word += char

    if current_word and word_start is not None:
        words.append(WordTimestamp(
            word=current_word,
            start_ms=int(word_start * 1000),
            end_ms=int(word_end * 1000),
        ))

    return words


def _align_words_to_segments(state: PipelineState, word_timestamps: list[WordTimestamp]) -> PipelineState:
    """Map global word timestamps back to individual segments by sequential text matching."""
    word_idx = 0

    for segment in state.segments:
        segment_words = segment.text.split()
        seg_start: int | None = None
        seg_end: int | None = None
        matched = 0
        scan_idx = word_idx

        while scan_idx < len(word_timestamps) and matched < len(segment_words):
            wt = word_timestamps[scan_idx]
            expected = segment_words[matched].strip(".,!?;:'\"()[]").lower()
            actual = wt.word.strip(".,!?;:'\"()[]").lower()

            if actual == expected:
                if seg_start is None:
                    seg_start = wt.start_ms
                seg_end = wt.end_ms
                matched += 1

            scan_idx += 1

        segment.audio_start_ms = seg_start if seg_start is not None else 0
        segment.audio_end_ms = seg_end if seg_end is not None else 0
        segment.duration_ms = segment.audio_end_ms - segment.audio_start_ms
        word_idx = scan_idx

    return state


def _generate_tts_elevenlabs(state: PipelineState) -> PipelineState:
    """Generate TTS audio and extract per-segment timing from ElevenLabs alignment data."""
    audio_path = get_audio_path()

    logger.info("  Calling ElevenLabs TTS with timestamps...")
    result = _call_tts_with_timestamps(state.raw_script)

    audio_b64 = result.audio_base_64
    audio_bytes = base64.b64decode(audio_b64)
    audio_path.write_bytes(audio_bytes)
    state.audio_path = str(audio_path)
    logger.info(f"  Audio saved: {audio_path.name}")

    alignment = result.alignment
    word_timestamps = _parse_alignment_to_words(alignment)

    if word_timestamps:
        state.total_audio_duration_ms = word_timestamps[-1].end_ms

    state.word_timestamps = word_timestamps
    state = _align_words_to_segments(state, word_timestamps)

    for seg in state.segments:
        logger.info(
            f"  [Segment {seg.index}] {seg.audio_start_ms}ms → {seg.audio_end_ms}ms "
            f"({seg.duration_ms}ms)"
        )
    return state


# ── Edge TTS backend (free, no API key) ──────────────────────────────

async def _edge_tts_stream(text: str, voice: str) -> tuple[bytes, list[WordTimestamp]]:
    """Stream Edge TTS and collect audio bytes + word boundary timestamps."""
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    audio_chunks: list[bytes] = []
    words: list[WordTimestamp] = []

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_chunks.append(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            # offset / duration are in 100-nanosecond units → convert to ms
            start_ms = chunk["offset"] // 10_000
            end_ms = start_ms + chunk["duration"] // 10_000
            words.append(WordTimestamp(word=chunk["text"], start_ms=start_ms, end_ms=end_ms))

    return b"".join(audio_chunks), words


def _generate_tts_edge(state: PipelineState) -> PipelineState:
    """Generate TTS using Microsoft Edge TTS (free, no API key required)."""
    audio_path = get_audio_path()
    logger.info(f"  Calling Edge TTS (voice={EDGE_TTS_VOICE})...")

    audio_bytes, word_timestamps = asyncio.run(
        _edge_tts_stream(state.raw_script, EDGE_TTS_VOICE)
    )

    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(audio_bytes)
    state.audio_path = str(audio_path)
    logger.info(f"  Audio saved: {audio_path.name} ({len(audio_bytes) // 1024} KB)")

    if word_timestamps:
        state.total_audio_duration_ms = word_timestamps[-1].end_ms

    state.word_timestamps = word_timestamps
    state = _align_words_to_segments(state, word_timestamps)

    for seg in state.segments:
        logger.info(
            f"  [Segment {seg.index}] {seg.audio_start_ms}ms → {seg.audio_end_ms}ms "
            f"({seg.duration_ms}ms)"
        )
    return state


def generate_tts(state: PipelineState) -> PipelineState:
    """Route to Edge TTS or ElevenLabs based on TTS_PROVIDER setting.
    Automatically falls back to Edge TTS if ElevenLabs quota is exceeded."""
    if TTS_PROVIDER == "edge":
        return _generate_tts_edge(state)

    try:
        return _generate_tts_elevenlabs(state)
    except Exception as e:
        if "quota_exceeded" in str(e):
            logger.warning(
                "ElevenLabs quota exceeded — automatically falling back to Edge TTS. "
                "Switch TTS provider to 'Edge TTS' in the sidebar to skip this retry."
            )
            return _generate_tts_edge(state)
        raise
