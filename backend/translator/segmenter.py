from __future__ import annotations

import re

from backend.translator.validator import SegmentRecord


CHAPTER_PATTERNS = [
    re.compile(r"^\s{0,3}#{1,6}\s+.+$"),
    re.compile(r"^\s*chapter\s+(\d+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten)\b.*$", re.IGNORECASE),
    re.compile(r"^\s*part\s+([ivxlcdm]+|\d+)\b.*$", re.IGNORECASE),
    re.compile(r"^\s*section\s+\d+(\.\d+)*\b.*$", re.IGNORECASE),
    re.compile(r"^\s*第\s*[0-9一二三四五六七八九十百千]+\s*[章节部卷篇]\s*.*$"),
    re.compile(r"^\s*\d+(\.\d+)*\s+.+$"),
]
SHORT_HEADING_WORDS = {"contents", "preface", "introduction", "prologue", "epilogue", "acknowledgements"}
LIST_PATTERN = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
BLOCKQUOTE_PATTERN = re.compile(r"^\s*>\s?")
FENCE_PATTERN = re.compile(r"^\s*(```|~~~)")
SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[\.\?\!;:])\s+")


def normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def is_heading_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if any(pattern.match(stripped) for pattern in CHAPTER_PATTERNS):
        return True
    lowered = stripped.lower()
    if lowered in SHORT_HEADING_WORDS:
        return True
    if stripped.isupper() and len(stripped) <= 48 and len(stripped.split()) <= 5:
        return True
    return False


def is_code_block(block: str) -> bool:
    stripped = block.strip()
    return stripped.startswith("```") or stripped.startswith("~~~")


def is_list_block(lines: list[str]) -> bool:
    return bool(lines) and all(LIST_PATTERN.match(line) for line in lines if line.strip())


def is_blockquote_block(lines: list[str]) -> bool:
    return bool(lines) and all(BLOCKQUOTE_PATTERN.match(line) for line in lines if line.strip())


def merge_lines(lines: list[str]) -> str:
    cleaned = [line.strip() for line in lines if line.strip()]
    if not cleaned:
        return ""
    if is_list_block(cleaned) or is_blockquote_block(cleaned):
        return "\n".join(cleaned)
    return " ".join(cleaned)


def split_raw_blocks(text: str) -> list[str]:
    lines = normalize_text(text).split("\n")
    blocks: list[str] = []
    current: list[str] = []
    in_code_block = False

    def flush_current() -> None:
        nonlocal current
        if current:
            block = "\n".join(current).strip()
            if block:
                blocks.append(block)
            current = []

    for line in lines:
        if FENCE_PATTERN.match(line.strip()):
            if in_code_block:
                current.append(line)
                flush_current()
                in_code_block = False
            else:
                flush_current()
                current = [line]
                in_code_block = True
            continue

        if in_code_block:
            current.append(line)
            continue

        if line.strip() == "":
            flush_current()
            continue

        current.append(line)

    flush_current()
    return blocks


def split_long_block(block: str, max_chars: int) -> list[str]:
    if len(block) <= max_chars or is_code_block(block):
        return [block]

    sentences = SENTENCE_SPLIT_PATTERN.split(block)
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        candidate = sentence if not current else f"{current} {sentence}"
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            pieces.append(current)
        if len(sentence) <= max_chars:
            current = sentence
            continue
        start = 0
        while start < len(sentence):
            pieces.append(sentence[start : start + max_chars].strip())
            start += max_chars
        current = ""

    if current:
        pieces.append(current)
    return pieces or [block]


def segment_document(text: str, max_segment_chars: int = 1800) -> list[SegmentRecord]:
    raw_blocks = split_raw_blocks(text)
    prepared_blocks: list[tuple[str, str]] = []

    for raw_block in raw_blocks:
        if is_code_block(raw_block):
            prepared_blocks.append(("code", raw_block.strip()))
            continue

        lines = [line.rstrip() for line in raw_block.splitlines() if line.strip()]
        if not lines:
            continue

        if len(lines) == 1 and is_heading_line(lines[0]):
            prepared_blocks.append(("heading", lines[0].strip()))
            continue

        if is_heading_line(lines[0]) and len(lines) <= 2 and all(len(line.strip()) <= 80 for line in lines):
            prepared_blocks.append(("heading", " ".join(line.strip() for line in lines)))
            continue

        prepared_blocks.append(("paragraph", merge_lines(lines)))

    segments: list[SegmentRecord] = []
    current_chapter = ""
    order = 1

    for block_type, block_text in prepared_blocks:
        if not block_text:
            continue

        if block_type == "heading":
            current_chapter = block_text
            segments.append(
                SegmentRecord(
                    segment_id=f"seg_{order:06d}",
                    order=order,
                    chapter_title=current_chapter,
                    source_text=block_text,
                )
            )
            order += 1
            continue

        for piece in split_long_block(block_text, max_segment_chars):
            if not piece.strip():
                continue
            segments.append(
                SegmentRecord(
                    segment_id=f"seg_{order:06d}",
                    order=order,
                    chapter_title=current_chapter,
                    source_text=piece.strip(),
                )
            )
            order += 1

    return segments
