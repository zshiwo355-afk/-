from __future__ import annotations

import re
import shutil
from pathlib import Path

import aiofiles

from backend.translator.segmenter import is_heading_line
from backend.translator.storage import FileStorage
from backend.translator.validator import ChunkRecord, JobRecord, SegmentRecord


XML_CLEANUP_PATTERNS = [
    re.compile(r"```(?:xml|html)?\s*", re.IGNORECASE),
    re.compile(r"```"),
    re.compile(r"</?translation\s*>", re.IGNORECASE),
    re.compile(r"<segment\b[^>]*>", re.IGNORECASE),
    re.compile(r"</segment\s*>", re.IGNORECASE),
]

CONTENTS_HEADING_KEYS = {"contents", "table of contents"}
LEADING_INDEX_RE = re.compile(r"^\s*((?:\d+(?:\.\d+)*)[.)]?)\s+")
NON_ALNUM_RE = re.compile(r"[^0-9a-z]+")
INVALID_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
EXPORTABLE_STATUSES = {"completed", "failed", "paused", "cancelled"}


def clean_translation_text(text: str) -> str:
    cleaned = text or ""
    for pattern in XML_CLEANUP_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    return cleaned.strip()


def build_output_filenames(file_name: str) -> dict[str, str]:
    source_path = Path(file_name or "book.txt")
    stem = INVALID_FILENAME_CHARS_RE.sub("_", source_path.stem).strip().rstrip(". ")
    if not stem:
        stem = "book"
    return {
        "translated.txt": f"{stem}.txt",
        "translated.md": f"{stem}.md",
        "bilingual.txt": f"{stem}_bilingual.txt",
        "bilingual.md": f"{stem}_bilingual.md",
    }


def _ordered_segments(segments: list[SegmentRecord]) -> list[SegmentRecord]:
    return sorted(segments, key=lambda item: item.order)


def _normalized_key(text: str) -> str:
    text = LEADING_INDEX_RE.sub("", text.strip())
    text = NON_ALNUM_RE.sub(" ", text.lower())
    return " ".join(text.split())


def _is_contents_heading(text: str) -> bool:
    return _normalized_key(text) in CONTENTS_HEADING_KEYS


def _is_heading_segment(segment: SegmentRecord) -> bool:
    source_text = segment.source_text.strip()
    chapter_title = segment.chapter_title.strip()
    return bool(source_text) and (source_text == chapter_title or is_heading_line(source_text))


def _fallback_translation_text(segment: SegmentRecord) -> str:
    if segment.status == "failed":
        reason = segment.error or "未知错误"
        return f"【未完成翻译：{reason}】\n{segment.source_text.strip()}"
    return f"【未完成翻译：任务未完成】\n{segment.source_text.strip()}"


def _segment_translation(segment: SegmentRecord) -> str:
    cleaned = clean_translation_text(segment.translated_text)
    if cleaned:
        return cleaned
    return _fallback_translation_text(segment)


def _build_contents_overrides(segments: list[SegmentRecord]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for segment in segments:
        if segment.status != "success":
            continue
        if not _is_contents_heading(segment.chapter_title):
            continue
        if _is_contents_heading(segment.source_text):
            continue

        content_key = _normalized_key(segment.source_text)
        if not content_key:
            continue

        matched_heading = ""
        for candidate in segments:
            if candidate.order <= segment.order:
                continue
            if candidate.status != "success":
                continue
            if _is_contents_heading(candidate.chapter_title):
                continue
            if _normalized_key(candidate.source_text) != content_key:
                continue
            translated_heading = _segment_translation(candidate)
            if not translated_heading:
                continue
            if _is_heading_segment(candidate) or len(candidate.source_text.strip()) <= 160:
                matched_heading = translated_heading
                break

        if not matched_heading:
            continue

        prefix_match = LEADING_INDEX_RE.match(segment.source_text.strip())
        if prefix_match:
            heading_without_prefix = LEADING_INDEX_RE.sub("", matched_heading, count=1).strip()
            overrides[segment.segment_id] = f"{prefix_match.group(1)} {heading_without_prefix}".strip()
        else:
            overrides[segment.segment_id] = matched_heading

    return overrides


def _build_translated_text(segments: list[SegmentRecord]) -> str:
    contents_overrides = _build_contents_overrides(segments)
    parts = []
    for segment in segments:
        text = contents_overrides.get(segment.segment_id, _segment_translation(segment))
        if text.strip():
            parts.append(text)
    return "\n\n".join(parts)


def _build_bilingual_text(segments: list[SegmentRecord]) -> str:
    contents_overrides = _build_contents_overrides(segments)
    parts = []
    for segment in segments:
        translated_text = contents_overrides.get(segment.segment_id, _segment_translation(segment))
        parts.append(
            "\n".join(
                [
                    "【原文】",
                    segment.source_text.strip(),
                    "",
                    "【译文】",
                    translated_text,
                ]
            )
        )
    return "\n\n----------------------------------------\n\n".join(parts)


def _build_bilingual_markdown(segments: list[SegmentRecord]) -> str:
    contents_overrides = _build_contents_overrides(segments)
    parts = []
    for segment in segments:
        translated_text = contents_overrides.get(segment.segment_id, _segment_translation(segment))
        parts.append(
            "\n".join(
                [
                    f"## {segment.segment_id.upper()}",
                    "",
                    f"状态：`{segment.status}`",
                    "",
                    "**原文**",
                    "",
                    segment.source_text.strip(),
                    "",
                    "**译文**",
                    "",
                    translated_text,
                    "",
                    "**错误**",
                    "",
                    segment.error or "-",
                ]
            )
        )
    return "\n\n---\n\n".join(parts)


def _clean_outputs_dir(storage: FileStorage, job_id: str, keep_names: set[str]) -> None:
    outputs_dir = storage.job_outputs_dir(job_id)
    debug_dir = storage.job_dir(job_id) / "debug"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    debug_dir.mkdir(parents=True, exist_ok=True)
    for path in outputs_dir.iterdir():
        if path.name in keep_names:
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
    del chunks
    if job.status not in EXPORTABLE_STATUSES:
        return

    ordered_segments = _ordered_segments(segments)
    if not ordered_segments:
        return

    outputs_dir = storage.job_outputs_dir(job.job_id)
    outputs_dir.mkdir(parents=True, exist_ok=True)
    output_filenames = build_output_filenames(job.file_name)
    keep_names = set(output_filenames.values())
    _clean_outputs_dir(storage, job.job_id, keep_names)

    translated_text = _build_translated_text(ordered_segments)
    bilingual_text = _build_bilingual_text(ordered_segments)
    bilingual_markdown = _build_bilingual_markdown(ordered_segments)

    async with aiofiles.open(outputs_dir / output_filenames["translated.txt"], "w", encoding="utf-8-sig", newline="\n") as file:
        await file.write(translated_text)
    async with aiofiles.open(outputs_dir / output_filenames["translated.md"], "w", encoding="utf-8", newline="\n") as file:
        await file.write(translated_text)
    async with aiofiles.open(outputs_dir / output_filenames["bilingual.txt"], "w", encoding="utf-8-sig", newline="\n") as file:
        await file.write(bilingual_text)
    async with aiofiles.open(outputs_dir / output_filenames["bilingual.md"], "w", encoding="utf-8", newline="\n") as file:
        await file.write(bilingual_markdown)

    _clean_outputs_dir(storage, job.job_id, keep_names)
