import tempfile
import unittest
from pathlib import Path

from backend.translator.context_builder import build_messages
from backend.translator.pipeline import EventBroker, TranslationPipeline
from backend.translator.segmenter import split_long_block
from backend.translator.storage import FileStorage
from backend.translator.validator import ChunkRecord, JobConfigSnapshot, JobRecord, SegmentRecord


def make_job(target_language: str = "韩语") -> JobRecord:
    return JobRecord(
        job_id="test-job",
        file_name="book.txt",
        source_path="book.txt",
        target_language=target_language,
        total_segments=1,
        config=JobConfigSnapshot(
            model="hy-mt2-pro",
            temperature=0.1,
            stream=False,
            chunk_size_chars=3500,
            max_retries=3,
            target_language=target_language,
            translate_mode="natural",
            translation_level=4,
        ),
    )


class AutoSourceLanguageTest(unittest.TestCase):
    def test_primary_and_retry_prompts_do_not_assume_english(self):
        job = make_job()
        segment = SegmentRecord(
            segment_id="seg_000001",
            order=1,
            source_text="Bonjour le monde. こんにちは世界。",
        )
        chunk = ChunkRecord(
            chunk_id="chunk_000001",
            order=1,
            segment_ids=[segment.segment_id],
            source_text=segment.source_text,
        )

        primary = "\n".join(message["content"] for message in build_messages(job, chunk, [segment], []))
        self.assertIn("专业多语言书籍翻译助手", primary)
        self.assertIn("自动识别每个 source_segment", primary)
        self.assertIn("韩语", primary)
        self.assertNotIn("英文书籍", primary)
        self.assertNotIn("自然中文", primary)

        style_context = {
            "examples": [{"source": "Bonjour.", "target": "안녕하세요.", "note": "简洁"}],
        }
        styled_primary = "\n".join(
            message["content"]
            for message in build_messages(job, chunk, [segment], [], style_context)
        )
        self.assertIn("风格参考译例", styled_primary)
        self.assertIn("原文：Bonjour.", styled_primary)
        self.assertIn("译文：안녕하세요.", styled_primary)

        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = TranslationPipeline(FileStorage(Path(temp_dir)), EventBroker())
            retry = "\n".join(
                message["content"]
                for message in pipeline._build_segment_retry_messages(job, segment, style_context)
            )
        self.assertIn("自动识别下面段落的原文语言", retry)
        self.assertIn("韩语", retry)
        self.assertNotIn("英文书籍", retry)
        self.assertIn("风格参考译例", retry)
        self.assertIn("译文：안녕하세요.", retry)

    def test_cjk_sentence_punctuation_is_used_when_splitting(self):
        self.assertEqual(
            split_long_block("第一句话很短。第二句话也很短！第三句话结束？", 9),
            ["第一句话很短。", "第二句话也很短！", "第三句话结束？"],
        )


if __name__ == "__main__":
    unittest.main()
