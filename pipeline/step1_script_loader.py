from pathlib import Path
from models.data_models import PipelineState


def load_script(script_path: str) -> PipelineState:
    """Load plain text script file and initialize pipeline state."""
    path = Path(script_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Script not found: {path}")

    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Script file is empty: {path}")

    return PipelineState(
        script_path=str(path),
        raw_script=text,
    )
