from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from backend.translator.pipeline import EventBroker, TranslationPipeline
from backend.translator.storage import FileStorage


async def find_resume_job(storage: FileStorage, source_path: str) -> str | None:
    if not storage.jobs_dir.exists():
        return None
    candidates = []
    for job_dir in storage.jobs_dir.iterdir():
        if not job_dir.is_dir():
            continue
        job_file = job_dir / "job.json"
        if not job_file.exists():
            continue
        try:
            job = await storage.load_job(job_dir.name)
        except Exception:
            continue
        if Path(job.source_path).resolve() == Path(source_path).resolve() and job.status not in {"completed", "cancelled"}:
            candidates.append(job)
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.updated_at, reverse=True)
    return candidates[0].job_id


async def run_translate(args: argparse.Namespace) -> int:
    storage = FileStorage(Path(__file__).resolve().parent / "backend" / "data")
    await storage.ensure_base_dirs()
    broker = EventBroker()
    pipeline = TranslationPipeline(storage=storage, broker=broker)
    source_path = str(Path(args.input).resolve())

    if args.resume:
        resume_job_id = await find_resume_job(storage, source_path)
        if resume_job_id:
            job = await pipeline.resume_job(resume_job_id)
        else:
            job = await pipeline.create_job_from_file(
                source_path=source_path,
                file_name=Path(source_path).name,
                target_language=args.target_language,
                translation_mode=args.translation_mode,
                stream=args.stream,
                chunk_size_chars=args.chunk_size_chars,
            )
            job = await pipeline.start_job(job.job_id)
    else:
        job = await pipeline.create_job_from_file(
            source_path=source_path,
            file_name=Path(source_path).name,
            target_language=args.target_language,
            translation_mode=args.translation_mode,
            stream=args.stream,
            chunk_size_chars=args.chunk_size_chars,
        )
        job = await pipeline.start_job(job.job_id)

    while True:
        latest = await storage.load_job(job.job_id)
        print(
            f"[{latest.status}] completed={latest.completed_segments}/{latest.total_segments} "
            f"failed={latest.failed_segments} current={latest.current_segment_id}"
        )
        if latest.status in {"completed", "failed", "paused", "cancelled"}:
            print(f"job_id={latest.job_id}")
            print(f"outputs={storage.job_outputs_dir(latest.job_id)}")
            return 0 if latest.status == "completed" else 1
        await asyncio.sleep(2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local text book translator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    translate = subparsers.add_parser("translate", help="Translate a TXT or MD file")
    translate.add_argument("--input", required=True, help="Path to the .txt or .md file")
    translate.add_argument("--target-language", default="简体中文")
    translate.add_argument("--translation-mode", default="忠实翻译")
    translate.add_argument("--chunk-size-chars", type=int, default=3500)
    translate.add_argument("--resume", action="store_true")
    translate.add_argument(
        "--stream",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable or disable model streaming",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "translate":
        return asyncio.run(run_translate(args))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

