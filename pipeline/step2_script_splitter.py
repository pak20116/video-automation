import json
import logging
from google import genai
from config.settings import GEMINI_API_KEY, GEMINI_TEXT_MODEL
from models.data_models import PipelineState, ScriptSegment
from utils.api_helpers import with_retry

logger = logging.getLogger(__name__)
_client = genai.Client(api_key=GEMINI_API_KEY)

_SPLIT_PROMPT = """You are a video editor's assistant. Split the following script into segments.
Each segment represents ONE visual scene or idea suitable for displaying a single image.
Segments should be 1-4 sentences long and form naturally complete thoughts.

Return ONLY a valid JSON array of strings — no explanation, no markdown, no code fences.
Each string is one segment's spoken text, preserving the original language exactly.

Script:
{script}"""


@with_retry(max_attempts=6, delay_seconds=5.0)
def split_script(state: PipelineState) -> PipelineState:
    """Split raw script into visual segments using Gemini Flash."""
    prompt = _SPLIT_PROMPT.format(script=state.raw_script)

    response = _client.models.generate_content(model=GEMINI_TEXT_MODEL, contents=prompt)
    raw = response.text.strip()

    # Strip markdown code fences if Gemini wraps the JSON
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    segment_texts: list[str] = json.loads(raw)
    logger.info(f"Script split into {len(segment_texts)} segments.")

    state.segments = [
        ScriptSegment(index=i, text=text.strip())
        for i, text in enumerate(segment_texts)
        if text.strip()
    ]
    return state
