from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


JobStatus = Literal["pending", "running", "pausing", "paused", "completed", "failed", "cancelled"]
SegmentStatus = Literal["pending", "running", "partial", "success", "failed"]
ChunkStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
AUTH_FAILURE_MESSAGE = "TokenHub API Key 无效或 base_url/域名不匹配，请检查 backend/config.local.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return list(value.values())
    return [value]


class JobConfigSnapshot(BaseModel):
    model: str
    temperature: float
    stream: bool
    chunk_size_chars: int
    max_retries: int
    target_language: str
    translation_mode: str = "忠实翻译"
    corpus_id: str = "default"
    use_corpus: bool = True
    use_glossary: bool = True
    use_style_examples: bool = True
    use_domain_prompt: bool = True
    translate_mode: str = "psychology"
    translation_level: int = 3
    request_timeout_seconds: int = 180
    stream_timeout_seconds: int = 180
    stream_fallback: bool = True
    max_segments_per_chunk: int = 5
    min_chars_for_standalone_chunk: int = 300
    merge_tiny_chapter_segments: bool = True
    speed_mode: str = "stable"


class SegmentRecord(BaseModel):
    segment_id: str
    order: int
    chapter_title: str = ""
    source_text: str
    translated_text: str = ""
    status: SegmentStatus = "pending"
    chunk_id: str = ""
    summary: str = ""
    terms: dict[str, str] = Field(default_factory=dict)
    error: str = ""


class ChunkRecord(BaseModel):
    chunk_id: str
    order: int
    chapter_title: str = ""
    segment_ids: list[str]
    source_text: str
    status: ChunkStatus = "pending"
    summary: str = ""
    terms: dict[str, str] = Field(default_factory=dict)
    error: str = ""
    attempt_count: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    response_text: str = ""
    stream_fallback_used: bool = False
    used_terms: list[dict[str, Any]] = Field(default_factory=list)
    used_examples: list[dict[str, Any]] = Field(default_factory=list)


class JobRecord(BaseModel):
    job_id: str
    file_name: str
    source_path: str
    target_language: str
    status: JobStatus = "pending"
    total_segments: int
    total_chunks: int = 0
    avg_segment_chars: float = 0.0
    max_segment_chars: int = 0
    completed_segments: int = 0
    failed_segments: int = 0
    current_segment_id: str = ""
    current_chapter: str = ""
    last_error: str = ""
    pause_requested: bool = False
    cancel_requested: bool = False
    last_run_heartbeat_at: str = ""
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    config: JobConfigSnapshot


class TranslationParseResult(BaseModel):
    translations: dict[str, str] = Field(default_factory=dict)
    summary: str = ""
    terms: dict[str, str] = Field(default_factory=dict)
    missing_segment_ids: list[str] = Field(default_factory=list)


class TranslationResponse(BaseModel):
    text: str
    used_stream: bool
    stream_fallback_used: bool = False
    raw_error: str = ""


class LogEntry(BaseModel):
    timestamp: str = Field(default_factory=utc_now_iso)
    event: str
    payload: dict[str, Any] = Field(default_factory=dict)


class TranslationAuthError(Exception):
    def __init__(self, message: str, raw_error: str = ""):
        super().__init__(message)
        self.raw_error = raw_error or message


class TranslationTimeoutError(Exception):
    def __init__(self, message: str, timeout_seconds: int = 0):
        super().__init__(message)
        self.timeout_seconds = timeout_seconds
