from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.translator.validator import ensure_list


DEFAULT_DOMAIN_PROMPT = (
    "这是一本涉及心理学、精神分析、亲密关系、S/M、权力关系与边界的英文书籍。"
    "翻译时要保持概念稳定，避免把 BDSM / S/M 语境中的术语机械翻译成普通字面含义。"
)

DEFAULT_GLOSSARY = [
    ("top", "支配方", "BDSM / S/M 语境，不翻译为顶部"),
    ("bottom", "承受方", "BDSM / S/M 语境，不翻译为底部"),
    ("S/M", "S/M", "保留原缩写，必要时解释为施虐/受虐关系"),
    ("BDSM", "BDSM", "保留缩写，不要随意翻译"),
    ("oppressor", "压迫者", "心理权力关系语境"),
    ("victim role", "受害者角色", "角色扮演语境，不是现实受害"),
    ("internalized oppressor", "被内化的压迫者", "精神分析/社会心理学语境"),
    ("boundary", "边界", "关系心理学语境"),
    ("consent", "合意", "亲密关系和 BDSM 语境优先用合意，也可根据上下文译为同意"),
    ("scene", "场景", "BDSM 语境下指一次约定好的互动场景，不是普通风景"),
    ("power exchange", "权力交换", "亲密关系 / BDSM 语境"),
    ("dominance", "支配", "不要机械翻译为优势"),
    ("submission", "臣服", "BDSM / 关系权力语境"),
    ("shame", "羞耻", "心理学语境，保持稳定"),
    ("roleplay", "角色扮演", "不翻译为普通“游戏”"),
]

DEFAULT_EXAMPLES = [
    {
        "source": "And what could be more forbidden than our own nastiness?",
        "target": "还有什么比我们自身那些被压抑的阴暗面更禁忌呢？",
        "note": "心理学/精神分析语气，避免机械直译",
    }
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
            "name": "默认心理学语料库",
            "description": "适合心理学、精神分析、S/M、亲密关系、边界类书籍",
            "domain_prompt": DEFAULT_DOMAIN_PROMPT,
            "glossary": [
                {
                    "id": f"term_{index:03d}",
                    "source": source,
                    "target": target,
                    "note": note,
                    "enabled": True,
                }
                for index, (source, target, note) in enumerate(DEFAULT_GLOSSARY, start=1)
            ],
            "style_examples": [
                {"id": f"ex_{index:03d}", "enabled": True, **example}
                for index, example in enumerate(DEFAULT_EXAMPLES, start=1)
            ],
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
        now = utc_now_iso()
        normalized_glossary = []
        for item in ensure_list(data.get("glossary", [])):
            source = str(item.get("source", "")).strip() if isinstance(item, dict) else ""
            target = str(item.get("target", "")).strip() if isinstance(item, dict) else ""
            if not source or not target:
                continue
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
        for item in ensure_list(data.get("style_examples", [])):
            source = str(item.get("source", "")).strip() if isinstance(item, dict) else ""
            target = str(item.get("target", "")).strip() if isinstance(item, dict) else ""
            if not source or not target:
                continue
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
        data = self.get_corpus(corpus_id)
        item = {"id": f"term_{uuid.uuid4().hex[:8]}", "source": source, "target": target, "note": note, "enabled": enabled}
        data["glossary"] = ensure_list(data.get("glossary", []))
        data["glossary"].append(item)
        self.save_corpus(corpus_id, data)
        return item

    def update_glossary_term(self, corpus_id: str, term_id: str, source: str, target: str, note: str = "", enabled: bool = True) -> dict[str, Any]:
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
        data = self.get_corpus(corpus_id)
        item = {"id": f"ex_{uuid.uuid4().hex[:8]}", "source": source, "target": target, "note": note, "enabled": enabled}
        data["style_examples"] = ensure_list(data.get("style_examples", []))
        data["style_examples"].append(item)
        self.save_corpus(corpus_id, data)
        return item

    def update_style_example(self, corpus_id: str, example_id: str, source: str, target: str, note: str = "", enabled: bool = True) -> dict[str, Any]:
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
        corpus = self.get_corpus(corpus_id)
        text_words = set(re.findall(r"[a-zA-Z][a-zA-Z'-]+", text.lower()))
        scored = []
        for item in ensure_list(corpus.get("style_examples", [])):
            if not isinstance(item, dict):
                continue
            if not item.get("enabled", True):
                continue
            source_words = set(re.findall(r"[a-zA-Z][a-zA-Z'-]+", item.get("source", "").lower()))
            overlap = len(text_words & source_words)
            if overlap:
                scored.append((overlap, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[:limit]]
