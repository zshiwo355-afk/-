from __future__ import annotations

from backend.translator.validator import ChunkRecord, SegmentRecord


def build_chunks(segments: list[SegmentRecord], chunk_size_chars: int) -> list[ChunkRecord]:
    chunks: list[ChunkRecord] = []
    current_segments: list[SegmentRecord] = []
    current_length = 0
    current_chapter = ""
    order = 1

    def flush() -> None:
        nonlocal current_segments, current_length, current_chapter, order
        if not current_segments:
            return
        chunk_id = f"chunk_{order:06d}"
        chunk_source_text = "\n\n".join(segment.source_text for segment in current_segments)
        chunk = ChunkRecord(
            chunk_id=chunk_id,
            order=order,
            chapter_title=current_chapter,
            segment_ids=[segment.segment_id for segment in current_segments],
            source_text=chunk_source_text,
        )
        for segment in current_segments:
            segment.chunk_id = chunk_id
        chunks.append(chunk)
        order += 1
        current_segments = []
        current_length = 0
        current_chapter = ""

    for segment in segments:
        segment_length = len(segment.source_text)
        segment_chapter = segment.chapter_title or current_chapter
        chapter_changed = bool(current_segments and segment_chapter != current_chapter)
        would_exceed_limit = bool(current_segments and current_length + segment_length + 2 > chunk_size_chars)

        if chapter_changed or would_exceed_limit:
            flush()

        if not current_segments:
            current_chapter = segment.chapter_title

        current_segments.append(segment)
        current_length += segment_length + 2

    flush()
    return chunks

