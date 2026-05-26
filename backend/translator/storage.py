from __future__ import annotations

import asyncio
import json
import logging
import shutil
import os
import time
import uuid
from pathlib import Path
from typing import Any

import aiofiles

from backend.translator.validator import ChunkRecord, JobRecord, LogEntry, SegmentRecord, ensure_list


logger = logging.getLogger(__name__)


class FileStorage:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.uploads_dir = base_dir / "uploads"
        self.jobs_dir = base_dir / "jobs"
        self.outputs_dir = base_dir / "outputs"
        self.json_cache: dict[str, Any] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def ensure_base_dirs(self) -> None:
        for path in (self.uploads_dir, self.jobs_dir, self.outputs_dir):
            path.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str) -> Path:
        return self.jobs_dir / job_id

    def chunks_dir(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "chunks"

    def job_outputs_dir(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "outputs"

    def job_json_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "job.json"

    def segments_json_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "segments.json"

    def chunk_json_path(self, job_id: str, chunk_id: str) -> Path:
        return self.chunks_dir(job_id) / f"{chunk_id}.json"

    def translation_log_path(self, job_id: str) -> Path:
        return self.job_outputs_dir(job_id) / "translation_log.json"

    def _get_lock(self, job_id: str) -> asyncio.Lock:
        if job_id not in self._locks:
            self._locks[job_id] = asyncio.Lock()
        return self._locks[job_id]

    def _cache_key(self, path: Path) -> str:
        return str(path.resolve())

    def _replace_with_retry_sync(self, tmp_path: Path, target_path: Path, retries: int = 10) -> None:
        for i in range(retries):
            try:
                os.replace(tmp_path, target_path)
                return
            except PermissionError:
                time.sleep(0.1 * (i + 1))
        os.replace(tmp_path, target_path)

    async def _replace_with_retry(self, tmp_path: Path, target_path: Path, retries: int = 10) -> None:
        for i in range(retries):
            try:
                os.replace(tmp_path, target_path)
                return
            except PermissionError:
                await asyncio.sleep(0.1 * (i + 1))
        os.replace(tmp_path, target_path)

    def _atomic_write_json_sync(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        backup_path = path.with_suffix(path.suffix + ".bak")
        data = json.dumps(payload, ensure_ascii=False, indent=2)
        try:
            with tmp_path.open("w", encoding="utf-8", newline="\n") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            if path.exists():
                try:
                    shutil.copy2(path, backup_path)
                except Exception as exc:
                    logger.warning("JSON backup write failed for %s: %s", path, exc)
            self._replace_with_retry_sync(tmp_path, path)
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception as cleanup_exc:
                logger.warning("JSON tmp cleanup failed for %s: %s", tmp_path, cleanup_exc)
            raise

    async def _write_json(self, path: Path, payload: Any) -> None:
        await asyncio.to_thread(self._atomic_write_json_sync, path, payload)
        self.json_cache[self._cache_key(path)] = payload

    async def _read_json(self, path: Path, default: Any = None) -> Any:
        cache_key = self._cache_key(path)
        backup_path = path.with_suffix(path.suffix + ".bak")

        async def try_read(target: Path) -> Any:
            async with aiofiles.open(target, "r", encoding="utf-8") as file:
                content = await file.read()
            if not content.strip():
                raise ValueError("empty-json")
            return json.loads(content)

        try:
            if not path.exists():
                logger.warning("JSON file missing: %s", path)
                return default
            payload = await try_read(path)
            self.json_cache[cache_key] = payload
            return payload
        except json.JSONDecodeError as exc:
            logger.warning("JSON decode failed for %s: %s", path, exc)
            if backup_path.exists():
                try:
                    payload = await try_read(backup_path)
                    self.json_cache[cache_key] = payload
                    return payload
                except Exception as backup_exc:
                    logger.warning("JSON backup read failed for %s: %s", backup_path, backup_exc)
            return default
        except ValueError as exc:
            logger.warning("JSON file empty while reading %s: %s", path, exc)
            if backup_path.exists():
                try:
                    payload = await try_read(backup_path)
                    self.json_cache[cache_key] = payload
                    return payload
                except Exception as backup_exc:
                    logger.warning("JSON backup read failed for %s: %s", backup_path, backup_exc)
            return default
        except Exception as exc:
            logger.warning("JSON read failed for %s: %s", path, exc)
            return default

    async def save_uploaded_file(self, file_name: str, content: bytes, job_id: str) -> Path:
        await self.ensure_base_dirs()
        suffix = Path(file_name).suffix
        safe_name = Path(file_name).name
        target_path = self.uploads_dir / f"{job_id}{suffix}"
        async with aiofiles.open(target_path, "wb") as file:
            await file.write(content)
        name_marker = target_path.with_suffix(f"{suffix}.name.txt")
        async with aiofiles.open(name_marker, "w", encoding="utf-8", newline="\n") as file:
            await file.write(safe_name)
        return target_path

    async def create_job(self, job: JobRecord, segments: list[SegmentRecord], chunks: list[ChunkRecord]) -> None:
        await self.ensure_base_dirs()
        self.job_dir(job.job_id).mkdir(parents=True, exist_ok=True)
        self.chunks_dir(job.job_id).mkdir(parents=True, exist_ok=True)
        self.job_outputs_dir(job.job_id).mkdir(parents=True, exist_ok=True)
        await self.save_job(job)
        await self.save_segments(job.job_id, segments)
        for chunk in chunks:
            await self.save_chunk(job.job_id, chunk)
        await self._write_json(self.translation_log_path(job.job_id), [])

    async def save_job(self, job: JobRecord) -> None:
        async with self._get_lock(job.job_id):
            await self._write_json(self.job_json_path(job.job_id), job.model_dump())

    async def load_job(self, job_id: str) -> JobRecord:
        payload = await self._read_json(self.job_json_path(job_id))
        if payload is None:
            raise FileNotFoundError(f"job.json not available for job_id={job_id}")
        return JobRecord(**payload)

    async def save_segments(self, job_id: str, segments: list[SegmentRecord]) -> None:
        async with self._get_lock(job_id):
            await self._write_json(self.segments_json_path(job_id), [segment.model_dump() for segment in segments])

    async def load_segments(self, job_id: str) -> list[SegmentRecord]:
        data = await self._read_json(self.segments_json_path(job_id), default=[])
        return [SegmentRecord(**item) for item in data]

    async def save_chunk(self, job_id: str, chunk: ChunkRecord) -> None:
        async with self._get_lock(job_id):
            await self._write_json(self.chunk_json_path(job_id, chunk.chunk_id), chunk.model_dump())

    async def load_chunks(self, job_id: str) -> list[ChunkRecord]:
        chunks: list[ChunkRecord] = []
        for path in sorted(self.chunks_dir(job_id).glob("chunk_*.json")):
            payload = await self._read_json(path)
            if payload is None:
                continue
            chunks.append(ChunkRecord(**payload))
        return chunks

    async def append_log(self, job_id: str, entry: LogEntry) -> None:
        async with self._get_lock(job_id):
            path = self.translation_log_path(job_id)
            entries = []
            if path.exists():
                entries = await self._read_json(path, default=[])
            if isinstance(entries, dict):
                entries = ensure_list(entries.get("events", []))
            else:
                entries = ensure_list(entries)
            entries.append(entry.model_dump())
            await self._write_json(path, entries)
