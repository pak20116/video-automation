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
    CHARACTER_REF_IMAGE_PATH,
)
from models.data_models import PipelineState
from utils.api_helpers import with_retry
from utils.file_helpers import get_image_path

logger = logging.getLogger(__name__)
_client = genai.Client(api_key=GEMINI_API_KEY)

_MIME_MAP = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def _build_contents(prompt: str):
    """Return multimodal contents (ref image + explicit character instruction + prompt)."""
    ref_path = Path(CHARACTER_REF_IMAGE_PATH) if CHARACTER_REF_IMAGE_PATH else None
    if ref_path and ref_path.exists():
        mime = _MIME_MAP.get(ref_path.suffix.lower(), "image/png")
        image_bytes = ref_path.read_bytes()
        instruction = (
            "REFERENCE CHARACTER IMAGE: The image above shows the EXACT character design you must use.\n"
            "REQUIREMENTS:\n"
            "- Replicate this character faithfully: same art style, same face, same body proportions, "
            "same hair, same clothing colors and style\n"
            "- This character is the main subject of the scene below\n"
            "- Do NOT use a generic character — use THIS specific character from the reference image\n\n"
            "SCENE TO GENERATE:\n" + prompt
        )
        return [
            types.Part.from_bytes(data=image_bytes, mime_type=mime),
            types.Part.from_text(instruction),
        ]
    return prompt


@with_retry(max_attempts=3, delay_seconds=5.0)
def _generate_single_image(prompt: str, output_path: Path) -> Path:
    """Generate one image from a prompt (+ optional ref image) and save as PNG."""
    response = _client.models.generate_content(
        model=GEMINI_IMAGE_MODEL,
        contents=_build_contents(prompt),
        config=types.GenerateContentConfig(
            response_modalities=["image", "text"]
        ),
    )

    for part in response.candidates[0].content.parts:
        if part.inline_data is not None and part.inline_data.mime_type.startswith("image/"):
            img = Image.open(io.BytesIO(part.inline_data.data)).convert("RGB")
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
