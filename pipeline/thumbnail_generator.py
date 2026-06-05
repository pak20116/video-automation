import io
import logging
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
from google import genai
from google.genai import types

from config.settings import GEMINI_API_KEY, GEMINI_IMAGE_MODEL, OUTPUT_DIR
from utils.api_helpers import with_retry

logger = logging.getLogger(__name__)
_client = genai.Client(api_key=GEMINI_API_KEY)

THUMB_W = 1280
THUMB_H = 720

_TITLE_FONT_PATHS = [
    "C:/Windows/Fonts/malgunbd.ttf",   # Malgun Gothic Bold (Korean + Latin)
    "C:/Windows/Fonts/arialbd.ttf",    # Arial Bold
    "C:/Windows/Fonts/impact.ttf",     # Impact (classic thumbnail font)
]
_BODY_FONT_PATHS = [
    "C:/Windows/Fonts/malgun.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def _load_font(size: int, paths: list[str]) -> ImageFont.FreeTypeFont:
    for path in paths:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except Exception:
        return (255, 215, 0)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    dummy_img = Image.new("RGB", (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_img)
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip() if current else word
        w = dummy_draw.textbbox((0, 0), candidate, font=font)[2]
        if w <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines if lines else [""]


@with_retry(max_attempts=3, delay_seconds=5.0)
def _generate_background(topic: str, art_style: str, character_desc: str) -> Image.Image:
    # Put style/character constraints first so Gemini prioritises them
    prompt_parts = []
    if art_style:
        prompt_parts.append(
            f"Draw in EXACTLY this art style: {art_style}. "
            "The visual style must match this description precisely."
        )
    if character_desc:
        prompt_parts.append(
            f"Include these exact characters using the same design: {character_desc}."
        )
    prompt_parts += [
        f"Scene topic: {topic}.",
        "YouTube thumbnail composition — high contrast, vibrant colors, dynamic and eye-catching.",
        "NO text or letters anywhere in the image. 16:9 widescreen.",
        "Must be visually consistent with the described art style throughout.",
    ]

    response = _client.models.generate_content(
        model=GEMINI_IMAGE_MODEL,
        contents=" ".join(prompt_parts),
        config=types.GenerateContentConfig(response_modalities=["image", "text"]),
    )
    for part in response.candidates[0].content.parts:
        if part.inline_data and part.inline_data.mime_type.startswith("image/"):
            img = Image.open(io.BytesIO(part.inline_data.data)).convert("RGB")
            return ImageOps.fit(img, (THUMB_W, THUMB_H), Image.LANCZOS)
    raise RuntimeError("Gemini returned no image for thumbnail background")


def _apply_gradient_overlay(img: Image.Image, opacity: int, position: str) -> Image.Image:
    base = img.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    W, H = base.size
    max_alpha = min(int(opacity * 2.55), 220)

    for y in range(H):
        if position == "bottom":
            t = (y / H) ** 1.8
        elif position == "top":
            t = ((H - y) / H) ** 1.8
        else:  # center
            dist = abs(y / H - 0.5) * 2
            t = dist ** 1.5
        draw.line([(0, y), (W - 1, y)], fill=(0, 0, 0, int(max_alpha * t)))

    return Image.alpha_composite(base, overlay).convert("RGB")


def _draw_shadowed_text(
    canvas: Image.Image,
    xy: tuple[int, int],
    text: str,
    font,
    color: tuple[int, int, int],
) -> Image.Image:
    base = canvas.convert("RGBA")

    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text(
        (xy[0] + 5, xy[1] + 5), text, font=font, fill=(0, 0, 0, 200)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=8))
    base = Image.alpha_composite(base, shadow)

    text_layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(text_layer).text(xy, text, font=font, fill=(*color, 255))
    base = Image.alpha_composite(base, text_layer)

    return base.convert("RGB")


def compose_thumbnail(
    bg: Image.Image,
    title: str,
    subtitle: str,
    accent_color: str,
    text_position: str,
    overlay_opacity: int,
) -> Image.Image:
    W, H = THUMB_W, THUMB_H
    accent_rgb = _hex_to_rgb(accent_color)
    img = _apply_gradient_overlay(bg, overlay_opacity, text_position)

    # Dynamic font size: larger for short titles
    char_count = len(title)
    if char_count <= 10:
        title_size = 108
    elif char_count <= 18:
        title_size = 90
    elif char_count <= 28:
        title_size = 74
    elif char_count <= 40:
        title_size = 62
    else:
        title_size = 52

    title_font = _load_font(title_size, _TITLE_FONT_PATHS)
    sub_font = _load_font(46, _BODY_FONT_PATHS)

    padding = 64
    max_text_w = W - 2 * padding

    title_lines = _wrap_text(title, title_font, max_text_w)

    dummy = Image.new("RGB", (1, 1))
    dummy_draw = ImageDraw.Draw(dummy)

    def text_h(t, f) -> int:
        bb = dummy_draw.textbbox((0, 0), t, font=f)
        return bb[3] - bb[1]

    line_gap = 12
    line_heights = [text_h(line, title_font) for line in title_lines]
    total_title_h = sum(line_heights) + line_gap * max(0, len(line_heights) - 1)

    bar_h, bar_gap = 8, 20
    sub_gap = 18
    sub_h = text_h(subtitle, sub_font) if subtitle else 0
    total_block_h = bar_h + bar_gap + total_title_h + (sub_gap + sub_h if subtitle else 0)

    if text_position == "bottom":
        block_top = H - total_block_h - padding
    elif text_position == "top":
        block_top = padding
    else:
        block_top = (H - total_block_h) // 2

    # Accent bar
    draw = ImageDraw.Draw(img)
    draw.rectangle(
        [(padding, block_top), (padding + 90, block_top + bar_h)],
        fill=accent_rgb,
    )

    # Title
    y = block_top + bar_h + bar_gap
    for i, line in enumerate(title_lines):
        img = _draw_shadowed_text(img, (padding, y), line, title_font, (255, 255, 255))
        y += line_heights[i] + line_gap

    # Subtitle
    if subtitle:
        img = _draw_shadowed_text(img, (padding, y + sub_gap), subtitle, sub_font, accent_rgb)

    return img


def generate_thumbnail_from_frame(
    frame_path: Path,
    title: str,
    subtitle: str = "",
    accent_color: str = "#FFD700",
    text_position: str = "bottom",
    overlay_opacity: int = 65,
    output_path: Optional[Path] = None,
) -> Path:
    """Generate thumbnail using an existing video frame — guarantees visual consistency."""
    if output_path is None:
        output_path = OUTPUT_DIR / "thumbnail.png"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"  [Thumbnail] Using frame: {Path(frame_path).name}")
    bg = ImageOps.fit(
        Image.open(str(frame_path)).convert("RGB"),
        (THUMB_W, THUMB_H),
        Image.LANCZOS,
    )

    logger.info("  [Thumbnail] Composing text overlay...")
    final = compose_thumbnail(bg, title, subtitle, accent_color, text_position, overlay_opacity)
    final.save(str(output_path), "PNG", optimize=True)
    logger.info(f"  [Thumbnail] Saved to {output_path}")
    return output_path


def generate_thumbnail(
    topic: str,
    title: str,
    subtitle: str = "",
    art_style: str = "",
    character_desc: str = "",
    accent_color: str = "#FFD700",
    text_position: str = "bottom",
    overlay_opacity: int = 65,
    output_path: Optional[Path] = None,
) -> Path:
    """Generate thumbnail with AI-generated background matching art style."""
    if output_path is None:
        output_path = OUTPUT_DIR / "thumbnail.png"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("  [Thumbnail] Generating background image with Gemini...")
    bg = _generate_background(topic, art_style, character_desc)

    logger.info("  [Thumbnail] Composing text overlay...")
    final = compose_thumbnail(bg, title, subtitle, accent_color, text_position, overlay_opacity)

    final.save(str(output_path), "PNG", optimize=True)
    logger.info(f"  [Thumbnail] Saved to {output_path}")
    return output_path
