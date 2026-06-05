import io
import logging
from pathlib import Path
from google import genai
from google.genai import types
from PIL import Image, ImageOps
from config.settings import (
    GEMINI_API_KEY,
    GEMINI_IMAGE_MODEL,
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
)
from models.data_models import PipelineState
from utils.api_helpers import with_retry
from utils.file_helpers import get_image_path

logger = logging.getLogger(__name__)
_client = genai.Client(api_key=GEMINI_API_KEY)


@with_retry(max_attempts=3, delay_seconds=5.0)
def _generate_single_image(prompt: str, output_path: Path) -> Path:
    """Generate one image from a prompt and save it as PNG."""
    response = _client.models.generate_content(
        model=GEMINI_IMAGE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["image", "text"]
        ),
    )

    for part in response.candidates[0].content.parts:
        if part.inline_data is not None and part.inline_data.mime_type.startswith("image/"):
            img = Image.open(io.BytesIO(part.inline_data.data)).convert("RGB")
            # Cover+crop: 비율 유지하며 꽉 채우고 중앙 크롭
            img = ImageOps.fit(img, (VIDEO_WIDTH, VIDEO_HEIGHT), Image.LANCZOS)
            img.save(str(output_path), "PNG")
            return output_path

    raise RuntimeError(f"No image returned by Gemini for prompt: {prompt[:80]}...")


def generate_images(state: PipelineState) -> PipelineState:
    """Generate one PNG image per segment using Gemini image generation."""
    for segment in state.segments:
        output_path = get_image_path(segment.index)

        if output_path.exists():
            logger.info(f"  [Segment {segment.index}] Image exists, skipping.")
            segment.image_path = str(output_path)
            continue

        logger.info(f"  [Segment {segment.index}] Generating image...")
        _generate_single_image(segment.image_prompt, output_path)
        segment.image_path = str(output_path)
        logger.info(f"  [Segment {segment.index}] Saved: {output_path.name}")

    return state
