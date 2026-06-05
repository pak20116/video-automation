import logging
from google import genai
from config.settings import GEMINI_API_KEY, GEMINI_TEXT_MODEL, IMAGE_STYLE, CHARACTER_DESCRIPTION
from models.data_models import PipelineState
from utils.api_helpers import with_retry

logger = logging.getLogger(__name__)
_client = genai.Client(api_key=GEMINI_API_KEY)

_PROMPT_TEMPLATE = """You are a visual director creating image prompts for a 2D stick figure cartoon video.

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


@with_retry(max_attempts=6, delay_seconds=5.0)
def _generate_single_prompt(text: str) -> str:
    character_section = (
        f"\nCHARACTERS (keep consistent across all scenes):\n{CHARACTER_DESCRIPTION}\n"
        if CHARACTER_DESCRIPTION.strip() else ""
    )
    prompt = _PROMPT_TEMPLATE.format(
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
