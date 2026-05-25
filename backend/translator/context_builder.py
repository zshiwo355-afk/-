from __future__ import annotations

from backend.translator.validator import ChunkRecord, JobRecord, SegmentRecord


MODE_INSTRUCTIONS = {
    "忠实翻译": "以忠实翻译为主，尽量保留原意、结构和语气。",
    "阅读优化": "在不改变原意的前提下优化中文可读性。",
    "知识库入库": "强调术语统一、结构清晰，适合知识库沉淀。",
}


def extract_glossary(chunks: list[ChunkRecord]) -> dict[str, str]:
    glossary: dict[str, str] = {}
    for chunk in chunks:
        glossary.update(chunk.terms)
    return glossary


def build_chapter_summary(chunks: list[ChunkRecord], chapter_title: str) -> str:
    summaries = [chunk.summary.strip() for chunk in chunks if chunk.chapter_title == chapter_title and chunk.summary.strip()]
    return " ".join(summaries[-3:]).strip()


def build_previous_context(chunks: list[ChunkRecord]) -> str:
    completed_chunks = [chunk for chunk in chunks if chunk.status == "completed"]
    if not completed_chunks:
        return ""
    last_chunk = completed_chunks[-1]
    tail = last_chunk.source_text[-500:].strip()
    summary = last_chunk.summary.strip()
    return f"{tail}\n\nSummary: {summary}".strip()


def build_book_context(chunks: list[ChunkRecord]) -> str:
    summaries = [chunk.summary.strip() for chunk in chunks if chunk.summary.strip()]
    return " ".join(summaries[-5:]).strip()


def render_source_segments(segments: list[SegmentRecord]) -> str:
    return "\n\n".join(
        f'<segment id="{segment.segment_id}">\n{segment.source_text}\n</segment>' for segment in segments
    )


def build_messages(
    job: JobRecord,
    chunk: ChunkRecord,
    source_segments: list[SegmentRecord],
    completed_chunks: list[ChunkRecord],
) -> list[dict[str, str]]:
    glossary = extract_glossary(completed_chunks)
    chapter_summary = build_chapter_summary(completed_chunks, chunk.chapter_title)
    previous_context = build_previous_context(completed_chunks)
    book_context = build_book_context(completed_chunks)
    glossary_text = "\n".join(f"{source} = {target}" for source, target in glossary.items()) or "(empty)"
    mode_instruction = MODE_INSTRUCTIONS.get(job.config.translation_mode, MODE_INSTRUCTIONS["忠实翻译"])

    system_prompt = (
        "You are a professional book translation engine.\n"
        f"Translate English book content into {job.target_language}.\n"
        "Always preserve Markdown structure, list structure, block quotes, and code blocks.\n"
        "Never omit content, never merge segments, never delete segment ids.\n"
        "Only translate <segment> blocks inside source_segments.\n"
        "Never translate previous_context.\n"
        "Output exactly three sections in this order: <translation>...</translation>, <summary>...</summary>, <terms>...</terms>."
    )

    user_prompt = (
        f"Target language: {job.target_language}\n"
        f"Translation mode: {job.config.translation_mode}\n"
        f"Mode instruction: {mode_instruction}\n\n"
        f"book_context:\n{book_context or '(empty)'}\n\n"
        f"chapter_title:\n{chunk.chapter_title or '(none)'}\n\n"
        f"chapter_summary:\n{chapter_summary or '(empty)'}\n\n"
        f"glossary:\n{glossary_text}\n\n"
        f"previous_context:\n{previous_context or '(empty)'}\n\n"
        "source_segments:\n"
        f"{render_source_segments(source_segments)}\n\n"
        "Requirements:\n"
        "1. Only translate source_segments.\n"
        "2. Do not translate or repeat previous_context.\n"
        "3. Do not summarize or shorten the translation content.\n"
        "4. Preserve Markdown structure.\n"
        "5. Keep each segment id unchanged.\n"
        "6. Do not merge or reorder segments.\n"
        "7. Prefer the glossary when relevant.\n"
        "8. In <summary>, write a brief summary for this chunk only.\n"
        "9. In <terms>, list one term per line in the format source = target.\n"
        "10. If a source segment contains a code block, keep the code block untouched."
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

