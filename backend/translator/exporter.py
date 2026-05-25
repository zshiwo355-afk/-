from __future__ import annotations

import json

import aiofiles

from backend.translator.storage import FileStorage
from backend.translator.validator import ChunkRecord, JobRecord, SegmentRecord


async def export_outputs(
    storage: FileStorage,
    job: JobRecord,
    segments: list[SegmentRecord],
    chunks: list[ChunkRecord],
) -> None:
    outputs_dir = storage.job_outputs_dir(job.job_id)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    translated_md = "\n\n".join(segment.translated_text or "等待翻译" for segment in segments)
    bilingual_md_parts = []
    for segment in segments:
        bilingual_md_parts.append(
            "\n".join(
                [
                    f"## {segment.segment_id}",
                    "",
                    "### Source",
                    segment.source_text,
                    "",
                    "### Translation",
                    segment.translated_text or "等待翻译",
                ]
            )
        )
    bilingual_md = "\n\n---\n\n".join(bilingual_md_parts)

    aligned_lines = [
        json.dumps(
            {
                "segment_id": segment.segment_id,
                "chapter_title": segment.chapter_title,
                "source_text": segment.source_text,
                "translated_text": segment.translated_text,
                "status": segment.status,
                "chunk_id": segment.chunk_id,
                "summary": segment.summary,
                "terms": segment.terms,
                "error": segment.error,
            },
            ensure_ascii=False,
        )
        for segment in segments
    ]

    existing_entries = []
    log_path = storage.translation_log_path(job.job_id)
    if log_path.exists():
        async with aiofiles.open(log_path, "r", encoding="utf-8") as file:
            content = await file.read()
            existing_entries = json.loads(content) if content.strip() else []

    translation_log = {
        "job": job.model_dump(),
        "chunks": [chunk.model_dump() for chunk in chunks],
        "events": existing_entries,
    }

    async with aiofiles.open(outputs_dir / "translated.md", "w", encoding="utf-8") as file:
        await file.write(translated_md)
    async with aiofiles.open(outputs_dir / "bilingual.md", "w", encoding="utf-8") as file:
        await file.write(bilingual_md)
    async with aiofiles.open(outputs_dir / "aligned.jsonl", "w", encoding="utf-8") as file:
        await file.write("\n".join(aligned_lines))
    async with aiofiles.open(outputs_dir / "translation_log.json", "w", encoding="utf-8") as file:
        await file.write(json.dumps(translation_log, ensure_ascii=False, indent=2))
