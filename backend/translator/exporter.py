from __future__ import annotations

import re
import shutil

import aiofiles

from backend.translator.storage import FileStorage
from backend.translator.validator import ChunkRecord, JobRecord, SegmentRecord


FINAL_OUTPUT_FILES = {"translated.txt", "translated.md", "bilingual.txt", "bilingual.md"}

XML_CLEANUP_PATTERNS = [
    re.compile(r"```(?:xml|html)?\s*", re.IGNORECASE),
    re.compile(r"```"),
    re.compile(r"</?translation\s*>", re.IGNORECASE),
    re.compile(r"<segment\b[^>]*>", re.IGNORECASE),
    re.compile(r"</segment\s*>", re.IGNORECASE),
]


def clean_translation_text(text: str) -> str:
    cleaned = text or ""
    for pattern in XML_CLEANUP_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    return cleaned.strip()


def _successful_segments(segments: list[SegmentRecord]) -> list[SegmentRecord]:
    return sorted((segment for segment in segments if segment.status == "success"), key=lambda item: item.order)


def _build_translated_text(segments: list[SegmentRecord]) -> str:
    return "\n\n".join(clean_translation_text(segment.translated_text) for segment in segments if segment.translated_text.strip())


def _build_bilingual_text(segments: list[SegmentRecord]) -> str:
    parts = []
    for segment in segments:
        parts.append(
            "\n".join(
                [
                    "【原文】",
                    segment.source_text.strip(),
                    "",
                    "【译文】",
                    clean_translation_text(segment.translated_text),
                ]
            )
        )
    return "\n\n----------------------------------------\n\n".join(parts)


def _build_bilingual_markdown(segments: list[SegmentRecord]) -> str:
    parts = []
    for segment in segments:
        parts.append(
            "\n".join(
                [
                    f"## {segment.segment_id.upper()}",
                    "",
                    "**原文**",
                    "",
                    segment.source_text.strip(),
                    "",
                    "**译文**",
                    "",
                    clean_translation_text(segment.translated_text),
                ]
            )
        )
    return "\n\n---\n\n".join(parts)


def _clean_outputs_dir(storage: FileStorage, job_id: str) -> None:
    outputs_dir = storage.job_outputs_dir(job_id)
    debug_dir = storage.job_dir(job_id) / "debug"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    debug_dir.mkdir(parents=True, exist_ok=True)
    for path in outputs_dir.iterdir():
        if path.name in FINAL_OUTPUT_FILES:
            continue
        target = debug_dir / path.name
        try:
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            shutil.move(str(path), str(target))
        except Exception:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)


async def export_outputs(
    storage: FileStorage,
    job: JobRecord,
    segments: list[SegmentRecord],
    chunks: list[ChunkRecord],
) -> None:
    if job.status != "completed":
        return
    if job.completed_segments != job.total_segments or job.failed_segments != 0:
        raise RuntimeError("任务未完成，不能导出最终文件")

    outputs_dir = storage.job_outputs_dir(job.job_id)
    outputs_dir.mkdir(parents=True, exist_ok=True)
    _clean_outputs_dir(storage, job.job_id)

    final_segments = _successful_segments(segments)
    translated_text = _build_translated_text(final_segments)
    bilingual_text = _build_bilingual_text(final_segments)
    bilingual_markdown = _build_bilingual_markdown(final_segments)

    async with aiofiles.open(outputs_dir / "translated.txt", "w", encoding="utf-8-sig", newline="\n") as file:
        await file.write(translated_text)
    async with aiofiles.open(outputs_dir / "translated.md", "w", encoding="utf-8", newline="\n") as file:
        await file.write(translated_text)
    async with aiofiles.open(outputs_dir / "bilingual.txt", "w", encoding="utf-8-sig", newline="\n") as file:
        await file.write(bilingual_text)
    async with aiofiles.open(outputs_dir / "bilingual.md", "w", encoding="utf-8", newline="\n") as file:
        await file.write(bilingual_markdown)

    _clean_outputs_dir(storage, job.job_id)
