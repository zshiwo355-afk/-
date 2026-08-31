from __future__ import annotations

from typing import Any

from backend.translator.validator import ChunkRecord, JobRecord, SegmentRecord


MODE_INSTRUCTIONS = {
    "faithful": "忠实翻译，不删减、不扩写、不解释，尽量保留原文论证结构和概念关系。",
    "natural": "在忠实原文的基础上，使用自然、通顺的目标语言书面表达。允许适度调整语序，但不能改变含义。",
    "psychology": "使用目标语言中的心理学与关系研究专业表达。术语要稳定，隐喻不要机械直译，并按原文学科语境保持中性、专业。",
    "wiki": "译文要清楚、稳定、可检索。关键术语首次出现时可保留原文括注。不要过度文学化，适合导入知识库。",
    "bilingual_learning": "关键术语尽量保留原文括注，方便学习和对照阅读。译文要忠实但便于理解。",
}

LEVEL_INSTRUCTIONS = {
    1: "尽量贴近原文句式，少调整语序。",
    2: "忠实原文，适度调整语序，让目标语言表达基本通顺。",
    3: "使用自然的目标语言表达，保持原意，适合日常阅读。",
    4: "使用目标语言的专业书籍风格，允许更充分的语序调整，但不能改变原意。",
    5: "深度润色，译文更自然成熟，但必须保持原文信息完整，不能增加原文没有的观点。",
}


def render_source_segments(segments: list[SegmentRecord]) -> str:
    return "\n\n".join(
        f'<segment id="{segment.segment_id}">\n{segment.source_text}\n</segment>' for segment in segments
    )


def _mode_instruction(job: JobRecord) -> str:
    return MODE_INSTRUCTIONS.get(job.config.translate_mode, MODE_INSTRUCTIONS["faithful"])


def _level_instruction(job: JobRecord) -> str:
    level = max(1, min(5, int(job.config.translation_level or 3)))
    return LEVEL_INSTRUCTIONS[level]


def _format_terms(terms: list[dict[str, Any]]) -> str:
    if not terms:
        return "无"
    return "\n".join(
        f"- {item.get('source', '')} => {item.get('target', '')}。说明：{item.get('note', '')}".strip()
        for item in terms
    )


def format_examples(examples: list[dict[str, Any]]) -> str:
    if not examples:
        return "无"
    return "\n\n".join(
        "\n".join(
            [
                f"原文：{str(item.get('source', ''))[:800]}",
                f"译文：{str(item.get('target', ''))[:800]}",
                f"说明：{str(item.get('note', ''))[:200]}",
            ]
        )
        for item in examples
    )


def build_messages(
    job: JobRecord,
    chunk: ChunkRecord,
    source_segments: list[SegmentRecord],
    completed_chunks: list[ChunkRecord],
    corpus_context: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    del chunk, completed_chunks
    corpus_context = corpus_context or {}
    domain_prompt = (corpus_context.get("domain_prompt") or "无")[:1500]
    terms = corpus_context.get("terms") or []
    examples = corpus_context.get("examples") or []

    system_prompt = "你是专业多语言书籍翻译助手。"
    user_prompt = (
        f"【目标语言】\n{job.target_language}\n\n"
        f"【翻译模式】\n{_mode_instruction(job)}\n\n"
        f"【翻译程度】\n{_level_instruction(job)}\n\n"
        f"【领域说明】\n{domain_prompt}\n\n"
        f"【本次必须遵守的术语】\n{_format_terms(terms)}\n\n"
        f"【风格参考译例】\n{format_examples(examples)}\n\n"
        "【严格要求】\n"
        "1. 自动识别每个 source_segment 的实际原文语言，并全部翻译为目标语言；遇到混合语言时按实际内容分别处理。\n"
        "2. 风格参考译例只用于模仿语气、措辞和句式，不能覆盖原文事实、目标语言或术语要求。\n"
        "3. 只翻译 source_segments，不要总结，不要删减。\n"
        "4. 每个输入 segment 必须输出对应 segment。\n"
        "5. segment id 必须完全照抄。\n"
        "6. 不要合并 segment。\n"
        "7. 不要删除 segment。\n"
        "8. 不要新增 segment。\n"
        "9. 书名、文章名、作品名优先保留原文；如需解释，可在首次出现后用目标语言括注，但不要直接替换原题。\n"
        "10. 输出格式必须是：\n"
        "<translation>\n"
        "<segment id=\"seg_xxxxxx\">\n"
        "译文\n"
        "</segment>\n"
        "</translation>\n\n"
        "【source_segments】\n"
        f"{render_source_segments(source_segments)}"
    )
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]


def build_single_segment_messages(
    job: JobRecord,
    segment: SegmentRecord,
    completed_chunks: list[ChunkRecord],
    corpus_context: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    return build_messages(
        job,
        ChunkRecord(chunk_id="single", order=0, segment_ids=[segment.segment_id], source_text=segment.source_text),
        [segment],
        completed_chunks,
        corpus_context,
    )
