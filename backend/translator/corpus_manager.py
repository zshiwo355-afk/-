from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.translator.validator import ensure_list


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_source_target(source: str, target: str, item_name: str) -> tuple[str, str]:
    source = source.strip()
    target = target.strip()
    if not source or not target:
        raise ValueError(f"{item_name}的原文和译文不能为空")
    return source, target


class CorpusManager:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir

    def ensure_default_corpus(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        path = self._corpus_path("default")
        if path.exists():
            return
        now = utc_now_iso()
        data = {
            "id": "default",
            "name": "未配置语料库",
            "description": "",
            "domain_prompt": "",
            "glossary": [],
            "style_examples": [],
            "created_at": now,
            "updated_at": now,
        }
        self.save_corpus("default", data)

    def _corpus_path(self, corpus_id: str) -> Path:
        return self.base_dir / corpus_id / "corpus.json"

    def _safe_id(self, value: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip().lower()).strip("_")
        return safe or f"corpus_{uuid.uuid4().hex[:8]}"

    def make_unique_corpus_id(self, preferred_id: str) -> str:
        base_id = self._safe_id(preferred_id)
        corpus_id = base_id
        index = 2
        while self._corpus_path(corpus_id).exists():
            corpus_id = f"{base_id}_{index}"
            index += 1
        return corpus_id

    def normalize_corpus(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError("语料库备份必须是 JSON 对象")
        now = utc_now_iso()
        normalized_glossary = []
        for index, item in enumerate(ensure_list(data.get("glossary", [])), start=1):
            source = str(item.get("source", "")).strip() if isinstance(item, dict) else ""
            target = str(item.get("target", "")).strip() if isinstance(item, dict) else ""
            if not source or not target:
                raise ValueError(f"第 {index} 条术语的原文和译文不能为空")
            normalized_glossary.append(
                {
                    "id": str(item.get("id") or f"term_{uuid.uuid4().hex[:8]}"),
                    "source": source,
                    "target": target,
                    "note": str(item.get("note", "")),
                    "enabled": bool(item.get("enabled", True)),
                }
            )

        normalized_examples = []
        for index, item in enumerate(ensure_list(data.get("style_examples", [])), start=1):
            source = str(item.get("source", "")).strip() if isinstance(item, dict) else ""
            target = str(item.get("target", "")).strip() if isinstance(item, dict) else ""
            if not source or not target:
                raise ValueError(f"第 {index} 条风格示例的原文和译文不能为空")
            normalized_examples.append(
                {
                    "id": str(item.get("id") or f"ex_{uuid.uuid4().hex[:8]}"),
                    "source": source,
                    "target": target,
                    "note": str(item.get("note", "")),
                    "enabled": bool(item.get("enabled", True)),
                }
            )

        return {
            "id": self._safe_id(str(data.get("id") or data.get("name") or "corpus")),
            "name": str(data.get("name") or "未命名语料库"),
            "description": str(data.get("description") or ""),
            "domain_prompt": str(data.get("domain_prompt") or ""),
            "glossary": normalized_glossary,
            "style_examples": normalized_examples,
            "created_at": str(data.get("created_at") or now),
            "updated_at": now,
        }

    def _read(self, path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _write(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as file:
            file.write(json.dumps(data, ensure_ascii=False, indent=2))

    def list_corpora(self) -> list[dict[str, Any]]:
        self.ensure_default_corpus()
        items = []
        for path in sorted(self.base_dir.glob("*/corpus.json")):
            data = self._read(path)
            items.append(
                {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "description": data.get("description", ""),
                    "updated_at": data.get("updated_at", ""),
                    "glossary_count": len(data.get("glossary", [])),
                    "style_example_count": len(data.get("style_examples", [])),
                }
            )
        return items

    def get_corpus(self, corpus_id: str) -> dict[str, Any]:
        self.ensure_default_corpus()
        path = self._corpus_path(corpus_id)
        if not path.exists():
            raise FileNotFoundError(corpus_id)
        return self._read(path)

    def save_corpus(self, corpus_id: str, data: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        data = self.normalize_corpus(data)
        existing_created_at = data.get("created_at")
        data = {
            **data,
            "id": corpus_id,
            "glossary": data.get("glossary", []),
            "style_examples": data.get("style_examples", []),
            "created_at": existing_created_at or now,
            "updated_at": now,
        }
        self._write(self._corpus_path(corpus_id), data)
        return data

    def import_corpus_json(
        self,
        mode: str,
        data: dict[str, Any],
        target_corpus_id: str = "default",
    ) -> dict[str, Any]:
        normalized = self.normalize_corpus(data)
        if mode == "replace_current":
            corpus_id = target_corpus_id or "default"
        elif mode == "create_new":
            corpus_id = self.make_unique_corpus_id(normalized.get("id") or normalized.get("name") or "corpus")
        else:
            raise ValueError("Invalid import mode")

        saved = self.save_corpus(corpus_id, normalized)
        return {
            "ok": True,
            "corpus_id": saved["id"],
            "glossary_count": len(saved.get("glossary", [])),
            "style_example_count": len(saved.get("style_examples", [])),
            "corpus": saved,
        }

    def create_corpus(self, name: str, description: str = "") -> dict[str, Any]:
        corpus_id = self._safe_id(name)
        if self._corpus_path(corpus_id).exists():
            corpus_id = f"{corpus_id}_{uuid.uuid4().hex[:6]}"
        return self.save_corpus(
            corpus_id,
            {
                "id": corpus_id,
                "name": name,
                "description": description,
                "domain_prompt": "",
                "glossary": [],
                "style_examples": [],
            },
        )

    def delete_corpus(self, corpus_id: str) -> None:
        if corpus_id == "default":
            raise ValueError("default corpus cannot be deleted")
        path = self.base_dir / corpus_id
        if path.exists():
            shutil.rmtree(path)

    def update_domain_prompt(self, corpus_id: str, domain_prompt: str) -> dict[str, Any]:
        data = self.get_corpus(corpus_id)
        data["domain_prompt"] = domain_prompt
        return self.save_corpus(corpus_id, data)

    def add_glossary_term(self, corpus_id: str, source: str, target: str, note: str = "", enabled: bool = True) -> dict[str, Any]:
        source, target = require_source_target(source, target, "术语")
        data = self.get_corpus(corpus_id)
        item = {"id": f"term_{uuid.uuid4().hex[:8]}", "source": source, "target": target, "note": note, "enabled": enabled}
        data["glossary"] = ensure_list(data.get("glossary", []))
        data["glossary"].append(item)
        self.save_corpus(corpus_id, data)
        return item

    def update_glossary_term(self, corpus_id: str, term_id: str, source: str, target: str, note: str = "", enabled: bool = True) -> dict[str, Any]:
        source, target = require_source_target(source, target, "术语")
        data = self.get_corpus(corpus_id)
        data["glossary"] = ensure_list(data.get("glossary", []))
        for item in data["glossary"]:
            if item.get("id") == term_id:
                item.update({"source": source, "target": target, "note": note, "enabled": enabled})
                self.save_corpus(corpus_id, data)
                return item
        raise FileNotFoundError(term_id)

    def delete_glossary_term(self, corpus_id: str, term_id: str) -> None:
        data = self.get_corpus(corpus_id)
        data["glossary"] = [item for item in ensure_list(data.get("glossary", [])) if isinstance(item, dict) and item.get("id") != term_id]
        self.save_corpus(corpus_id, data)

    def add_style_example(self, corpus_id: str, source: str, target: str, note: str = "", enabled: bool = True) -> dict[str, Any]:
        source, target = require_source_target(source, target, "风格示例")
        data = self.get_corpus(corpus_id)
        item = {"id": f"ex_{uuid.uuid4().hex[:8]}", "source": source, "target": target, "note": note, "enabled": enabled}
        data["style_examples"] = ensure_list(data.get("style_examples", []))
        data["style_examples"].append(item)
        self.save_corpus(corpus_id, data)
        return item

    def update_style_example(self, corpus_id: str, example_id: str, source: str, target: str, note: str = "", enabled: bool = True) -> dict[str, Any]:
        source, target = require_source_target(source, target, "风格示例")
        data = self.get_corpus(corpus_id)
        data["style_examples"] = ensure_list(data.get("style_examples", []))
        for item in data["style_examples"]:
            if item.get("id") == example_id:
                item.update({"source": source, "target": target, "note": note, "enabled": enabled})
                self.save_corpus(corpus_id, data)
                return item
        raise FileNotFoundError(example_id)

    def delete_style_example(self, corpus_id: str, example_id: str) -> None:
        data = self.get_corpus(corpus_id)
        data["style_examples"] = [item for item in ensure_list(data.get("style_examples", [])) if isinstance(item, dict) and item.get("id") != example_id]
        self.save_corpus(corpus_id, data)

    def select_relevant_terms(self, corpus_id: str, text: str, limit: int = 30) -> list[dict[str, Any]]:
        corpus = self.get_corpus(corpus_id)
        haystack = text.lower()
        matches = [
            item for item in ensure_list(corpus.get("glossary", []))
            if isinstance(item, dict) and item.get("enabled", True) and item.get("source", "").lower() in haystack
        ]
        matches.sort(key=lambda item: len(item.get("source", "")), reverse=True)
        return matches[:limit]

    def select_relevant_examples(self, corpus_id: str, text: str, limit: int = 3) -> list[dict[str, Any]]:
        del text
        if limit <= 0:
            return []
        corpus = self.get_corpus(corpus_id)
        enabled = [
            item
            for item in ensure_list(corpus.get("style_examples", []))
            if isinstance(item, dict) and item.get("enabled", True)
        ]
        return enabled[-limit:]
