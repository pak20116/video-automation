import logging
from models.data_models import PipelineState
from utils.file_helpers import ensure_output_dirs, save_pipeline_state, load_pipeline_state
from pipeline.step1_script_loader import load_script
from pipeline.step2_script_splitter import split_script
from pipeline.step3_prompt_generator import generate_image_prompts
from pipeline.step4_image_generator import generate_images
from pipeline.step5_tts_generator import generate_tts
from pipeline.step6_subtitle_generator import generate_subtitles
from pipeline.step7_video_renderer import render_video

logger = logging.getLogger(__name__)

_STEPS = [
    (2, "Script Splitting",      split_script),
    (3, "Image Prompt Gen",      generate_image_prompts),
    (4, "Image Generation",      generate_images),
    (5, "TTS Generation",        generate_tts),
    (6, "Subtitle Generation",   generate_subtitles),
    (7, "Video Rendering",       render_video),
]


def run_pipeline(script_path: str, start_step: int = 1) -> PipelineState:
    """
    Run the full 7-step video automation pipeline.

    Args:
        script_path: Path to the input .txt script file.
        start_step: 1-indexed step to start from. Useful for resuming after failure.
                    Steps 2-7 load saved state from output/segments.json automatically.

    Returns:
        Completed PipelineState with output_video_path set.
    """
    ensure_output_dirs()
    logger.info("=" * 50)
    logger.info("  Video Automation Pipeline — Starting")
    logger.info("=" * 50)

    logger.info("[Step 1/7] Script Loading")
    if start_step > 1:
        # Resume: restore the full state saved after the last successful step
        logger.info("  Resuming from saved state (output/segments.json)...")
        state = PipelineState(**load_pipeline_state())
        logger.info(f"  Loaded {len(state.segments)} segments from previous run.")
    else:
        state = load_script(script_path)
        save_pipeline_state(state.model_dump())

    for step_num, step_name, step_fn in _STEPS:
        if step_num < start_step:
            logger.info(f"[Step {step_num}/7] {step_name} — SKIPPED")
            continue

        logger.info(f"[Step {step_num}/7] {step_name}")
        try:
            state = step_fn(state)
            save_pipeline_state(state.model_dump())
        except Exception as e:
            logger.error(f"Pipeline failed at step {step_num} ({step_name}): {e}")
            logger.info(f"Tip: Fix the issue and re-run with --start-step {step_num}")
            raise

    logger.info("=" * 50)
    logger.info(f"  Done! Output: {state.output_video_path}")
    logger.info("=" * 50)
    return state
