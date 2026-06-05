from typing import Optional
from pydantic import BaseModel, Field


class ScriptSegment(BaseModel):
    index: int
    text: str
    image_prompt: Optional[str] = None
    image_path: Optional[str] = None
    audio_start_ms: Optional[int] = None
    audio_end_ms: Optional[int] = None
    duration_ms: Optional[int] = None


class PipelineState(BaseModel):
    script_path: str
    raw_script: str
    segments: list[ScriptSegment] = Field(default_factory=list)
    word_timestamps: list["WordTimestamp"] = Field(default_factory=list)
    audio_path: Optional[str] = None
    subtitle_path: Optional[str] = None
    output_video_path: Optional[str] = None
    total_audio_duration_ms: Optional[int] = None


class WordTimestamp(BaseModel):
    word: str
    start_ms: int
    end_ms: int
    segment_index: Optional[int] = None
