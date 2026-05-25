from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
CONFIG_LOCAL_PATH = BASE_DIR / "config.local.json"
CONFIG_EXAMPLE_PATH = BASE_DIR / "config.example.json"
ENV_FILE_PATHS = (
    PROJECT_ROOT / ".env",
    PROJECT_ROOT / ".env.local",
)


class AppConfig(BaseModel):
    tokenhub_api_key: str = ""
    tokenhub_base_url: str = "https://tokenhub.tencentmaas.com/v1"
    model: str = "hy-mt2-pro"
    default_target_language: str = "简体中文"
    temperature: float = 0.1
    stream: bool = True
    chunk_size_chars: int = 3500
    max_retries: int = 3


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value}")


ENV_CONFIG_SPECS: dict[str, tuple[str, Any]] = {
    "TOKENHUB_API_KEY": ("tokenhub_api_key", str),
    "TOKENHUB_BASE_URL": ("tokenhub_base_url", str),
    "TRANSLATION_MODEL": ("model", str),
    "DEFAULT_TARGET_LANGUAGE": ("default_target_language", str),
    "TRANSLATION_TEMPERATURE": ("temperature", float),
    "TRANSLATION_STREAM": ("stream", _parse_bool),
    "CHUNK_SIZE_CHARS": ("chunk_size_chars", int),
    "MAX_RETRIES": ("max_retries", int),
}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    data: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[7:].strip()

            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            data[key.strip()] = value
    return data


def _build_env_config(env_data: dict[str, str]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for env_name, (config_key, parser) in ENV_CONFIG_SPECS.items():
        raw_value = env_data.get(env_name)
        if raw_value is None:
            continue
        data[config_key] = parser(raw_value)
    return data


def _load_env_config() -> dict[str, Any]:
    env_data: dict[str, str] = {}
    for path in ENV_FILE_PATHS:
        env_data.update(_read_env_file(path))
    return _build_env_config(env_data)


def _load_process_env_config() -> dict[str, Any]:
    env_data = {
        env_name: raw_value
        for env_name in ENV_CONFIG_SPECS
        if (raw_value := os.getenv(env_name)) is not None
    }
    return _build_env_config(env_data)


@lru_cache(maxsize=1)
def load_config() -> AppConfig:
    data = _read_json(CONFIG_EXAMPLE_PATH)
    data.update(_read_json(CONFIG_LOCAL_PATH))
    data.update(_load_env_config())
    data.update(_load_process_env_config())

    return AppConfig(**data)


def reload_config() -> AppConfig:
    load_config.cache_clear()
    return load_config()


def build_runtime_config(overrides: dict[str, Any] | None = None) -> AppConfig:
    config = load_config().model_dump()
    if overrides:
        config.update({key: value for key, value in overrides.items() if value is not None})
    return AppConfig(**config)
