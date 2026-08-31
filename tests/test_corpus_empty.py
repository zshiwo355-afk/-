import tempfile
import unittest
from pathlib import Path

from backend.translator.corpus_manager import CorpusManager


class EmptyCorpusTest(unittest.TestCase):
    def test_empty_directory_gets_an_unconfigured_placeholder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = CorpusManager(Path(temp_dir))

            self.assertEqual(
                manager.list_corpora(),
                [
                    {
                        "id": "default",
                        "name": "未配置语料库",
                        "description": "",
                        "updated_at": manager.get_corpus("default")["updated_at"],
                        "glossary_count": 0,
                        "style_example_count": 0,
                    }
                ],
            )
            corpus = manager.get_corpus("default")
            self.assertEqual(corpus["domain_prompt"], "")
            self.assertEqual(corpus["glossary"], [])
            self.assertEqual(corpus["style_examples"], [])
            self.assertEqual(manager.select_relevant_terms("default", "anything"), [])
            self.assertEqual(manager.select_relevant_examples("default", "anything"), [])

    def test_empty_required_text_cannot_silently_delete_an_item(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = CorpusManager(Path(temp_dir))
            manager.ensure_default_corpus()
            term = manager.add_glossary_term("default", "attachment", "依恋")
            example = manager.add_style_example("default", "Hello", "你好")

            with self.assertRaisesRegex(ValueError, "不能为空"):
                manager.update_glossary_term("default", term["id"], " ", "依恋")
            with self.assertRaisesRegex(ValueError, "不能为空"):
                manager.update_style_example("default", example["id"], "Hello", " ")

            corpus = manager.get_corpus("default")
            self.assertEqual(corpus["glossary"], [term])
            self.assertEqual(corpus["style_examples"], [example])

    def test_multilingual_style_examples_are_sent_without_english_word_matching(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = CorpusManager(Path(temp_dir))
            manager.ensure_default_corpus()
            manager.add_style_example("default", "第一句。", "第一种译法。")
            manager.add_style_example("default", "第二句。", "第二种译法。", enabled=False)
            third = manager.add_style_example("default", "こんにちは。", "你好。")
            fourth = manager.add_style_example("default", "안녕하세요.", "您好。")
            fifth = manager.add_style_example("default", "Bonjour.", "早上好。")

            self.assertEqual(
                manager.select_relevant_examples("default", "完全无关的中文原文", limit=3),
                [third, fourth, fifth],
            )

    def test_corpus_backup_must_be_a_json_object(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = CorpusManager(Path(temp_dir))
            with self.assertRaisesRegex(ValueError, "JSON 对象"):
                manager.normalize_corpus([])


if __name__ == "__main__":
    unittest.main()
