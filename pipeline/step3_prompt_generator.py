import logging
from pathlib import Path
from google import genai
from google.genai import types
from config.settings import (
    GEMINI_API_KEY,
    GEMINI_TEXT_MODEL,
    IMAGE_STYLE,
    CHARACTER_DESCRIPTION,
    CHARACTER_REF_IMAGE_PATH,
)
from models.data_models import PipelineState
from utils.api_helpers import with_retry

logger = logging.getLogger(__name__)
_client = genai.Client(api_key=GEMINI_API_KEY)

_MIME_MAP = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}

# Default: stickman style (no reference image)
_PROMPT_TEMPLATE_DEFAULT = """You are a visual director creating image prompts for a 2D stick figure cartoon video.

STYLE RULES (must follow strictly):
- Characters: simple stick figures with a perfect circle head, dot eyes, small curved mouth, thin stick limbs, flat-colored simple clothing
- Background: clean white or very light solid color, simple flat geometric shapes for furniture/props
- Art style: {style}
- NO photorealism, NO 3D rendering, NO complex shading, NO real photographs
{character_section}
For the following narration segment, write ONE image generation prompt in English that:
1. Describes the scene using the stick figure style above
2. Specifies what stick figure characters are doing and their simple expressions
3. Describes the minimal background elements

Output ONLY the image prompt — no explanation, no preamble, no quotes.

Narration: "{text}"
"""

# Reference image mode: Gemini Vision pre-analyzes the character; extracted description is embedded here
_PROMPT_TEMPLATE_WITH_REF = """You are a visual director creating image prompts for an animated video.

A CHARACTER REFERENCE IMAGE will be provided alongside the image generation request.
The image generator MUST replicate that character exactly — this is critical.

CHARACTER DESCRIPTION (extracted from the reference image — replicate this precisely):
{ref_description}

CHARACTER VISUAL SUMMARY: {char_summary}

STRICT RULES:
- The character MUST look identical to the reference: same art style, same face, same body proportions, same hair, same clothing colors
- Do NOT substitute with a generic character — use the EXACT character from the reference image
- Art style: {style}
- Keep backgrounds clean and simple so the character is the clear focus
{character_section}
For the following narration segment, write ONE image generation prompt in English that:
1. Opens with "Using the exact character from the reference image: {char_summary},"
2. Describes specifically what the character is doing and their expression in this scene
3. Briefly describes the background setting

Output ONLY the image prompt — no explanation, no preamble, no quotes.

Narration: "{text}"
"""


def _has_ref_image() -> bool:
    return bool(CHARACTER_REF_IMAGE_PATH and Path(CHARACTER_REF_IMAGE_PATH).exists())


_ref_description_cache: str = ""
_char_summary_cache: str = ""


def _analyze_ref_image() -> tuple[str, str]:
    """Use Gemini Vision to extract a detailed character description from the reference image."""
    ref_path = Path(CHARACTER_REF_IMAGE_PATH)
    mime = _MIME_MAP.get(ref_path.suffix.lower(), "image/png")
    image_bytes = ref_path.read_bytes()

    analysis_prompt = (
        "Analyze this character image for use in AI image generation. "
        "Provide TWO outputs:\n\n"
        "1. DETAILED DESCRIPTION — describe the character's full visual appearance:\n"
        "   - Art style (cartoon/stick figure/3D/anime/etc)\n"
        "   - Face: shape, eyes style, nose, mouth, expression\n"
        "   - Hair: color, style, length\n"
        "   - Body: type, proportions, posture\n"
        "   - Clothing: colors, style, distinctive items\n"
        "   - Any unique visual features or accessories\n\n"
        "2. SHORT SUMMARY — max 25 words, key visual traits only for embedding in an image prompt.\n\n"
        "Format your response exactly as:\n"
        "DESCRIPTION: [full description here]\n"
        "---\n"
        "SUMMARY: [short summary here]"
    )

    response = _client.models.generate_content(
        model=GEMINI_TEXT_MODEL,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=mime),
            types.Part.from_text(analysis_prompt),
        ],
    )

    text = response.text.strip()
    description = text
    summary = "character from reference image"

    if "---" in text:
        parts = text.split("---", 1)
        description = parts[0].replace("DESCRIPTION:", "").strip()
        summary = parts[1].replace("SUMMARY:", "").strip().splitlines()[0].strip()
    elif "SUMMARY:" in text:
        idx = text.find("SUMMARY:")
        summary = text[idx:].replace("SUMMARY:", "").strip().splitlines()[0].strip()
        description = text[:idx].replace("DESCRIPTION:", "").strip()

    logger.info(f"  Character summary: {summary[:100]}")
    return description, summary


def _get_ref_description() -> tuple[str, str]:
    """Return (detailed_description, short_summary) for the reference image, cached per pipeline run."""
    global _ref_description_cache, _char_summary_cache
    if not _ref_description_cache and _has_ref_image():
        logger.info("  Analyzing character reference image with Gemini Vision...")
        try:
            _ref_description_cache, _char_summary_cache = _analyze_ref_image()
        except Exception as e:
            logger.warning(f"  Character analysis failed ({e}), using fallback description")
            _ref_description_cache = "character as shown in the reference image"
            _char_summary_cache = "character from reference image"
    return _ref_description_cache, _char_summary_cache


@with_retry(max_attempts=6, delay_seconds=5.0)
def _generate_single_prompt(text: str) -> str:
    character_section = (
        f"\nCHARACTERS (keep consistent across all scenes):\n{CHARACTER_DESCRIPTION}\n"
        if CHARACTER_DESCRIPTION.strip() else ""
    )

    if _has_ref_image():
        ref_description, char_summary = _get_ref_description()
        prompt = _PROMPT_TEMPLATE_WITH_REF.format(
            text=text,
            style=IMAGE_STYLE,
            character_section=character_section,
            ref_description=ref_description,
            char_summary=char_summary,
        )
    else:
        prompt = _PROMPT_TEMPLATE_DEFAULT.format(
            text=text,
            style=IMAGE_STYLE,
            character_section=character_section,
        )

    response = _client.models.generate_content(model=GEMINI_TEXT_MODEL, contents=prompt)
    return response.text.strip()


def generate_image_prompts(state: PipelineState) -> PipelineState:
    """Generate a detailed image prompt for each script segment."""
    for segment in state.segments:
        segment.image_prompt = _generate_single_prompt(segment.text)
        logger.info(f"  [Segment {segment.index}] Prompt: {segment.image_prompt[:80]}...")

    return state
