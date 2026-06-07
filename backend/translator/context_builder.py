from __future__ import annotations

from typing import Any

from backend.translator.validator import ChunkRecord, JobRecord, SegmentRecord


MODE_INSTRUCTIONS = {
    "faithful": "忠实翻译，不删减、不扩写、不解释，尽量保留原文论证结构和概念关系。",
    "natural": "在忠实原文的基础上，把译文调整为自然、通顺的中文书面表达。允许适度调整语序，但不能改变含义。",
    "psychology": "使用心理学、精神分析、亲密关系研究语境下的中文表达。术语要稳定，隐喻不要机械直译。遇到 S/M、BDSM、权力关系、边界、羞耻、压迫者、受害者等内容时，优先采用心理学和关系研究语境。",
    "wiki": "译文要清楚、稳定、可检索。关键术语首次出现时保留英文括注。不要过度文学化，适合导入知识库。",
    "bilingual_learning": "关键术语尽量保留英文括注，方便学习和对照阅读。译文要忠实但便于理解。",
}

LEVEL_INSTRUCTIONS = {
    1: "尽量贴近原文句式，少调整语序。",
    2: "忠实原文，适度调整语序，让中文基本通顺。",
    3: "自然中文，保持原意，适合日常阅读。",
    4: "中文专业书籍风格，允许更充分的语序调整，但不能改变原意。",
    5: "深度润色，译文更自然成熟，但必须保持原文信息完整，不能增加原文没有的观点。",
}


def render_source_segments(segments: list[SegmentRecord]) -> str:
    return "\n\n".join(
        f'<segment id="{segment.segment_id}">\n{segment.source_text}\n</segment>' for segment in segments
    )


def _mode_instruction(job: JobRecord) -> str:
    return MODE_INSTRUCTIONS.get(job.config.translate_mode, MODE_INSTRUCTIONS["psychology"])


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


def _format_examples(examples: list[dict[str, Any]]) -> str:
    if not examples:
        return "无"
    return "\n\n".join(
        "\n".join(
            [
                f"原文：{item.get('source', '')}",
                f"译文：{item.get('target', '')}",
                f"说明：{item.get('note', '')}",
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

    system_prompt = "你是专业英文书籍翻译助手。"
    user_prompt = (
        f"【目标语言】\n{job.target_language}\n\n"
        f"【翻译模式】\n{_mode_instruction(job)}\n\n"
        f"【翻译程度】\n{_level_instruction(job)}\n\n"
        f"【领域说明】\n{domain_prompt}\n\n"
        f"【本次必须遵守的术语】\n{_format_terms(terms)}\n\n"
        f"【参考译例】\n{_format_examples(examples)}\n\n"
        "【严格要求】\n"
        "1. 只翻译 source_segments。\n"
        "2. 不要总结，不要删减。\n"
        "3. 每个输入 segment 必须输出对应 segment。\n"
        "4. segment id 必须完全照抄。\n"
        "5. 不要合并 segment。\n"
        "6. 不要删除 segment。\n"
        "7. 不要新增 segment。\n"
        "8. 书名、文章名、作品名优先保留原文；如需解释，可在首次出现后加中文括注，但不要把原题替换成纯中文译名。\n"
        "9. 输出格式必须是：\n"
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
