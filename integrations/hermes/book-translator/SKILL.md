---
name: book-translator
description: Controls local long-form book translation jobs.
version: 1.0.0
author: Text Book Translator contributors + Hermes Agent
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [translation, books, txt, markdown, long-form]
    category: productivity
    related_skills: []
---

# Book Translator Skill

Use the local Text Book Translator service to submit and control long-form translation jobs, then return the generated document. This skill only orchestrates existing translation jobs; it never reads, changes, or prints the model API Key.

## When to Use

- The user attaches a `.txt` or `.md` book and asks to translate it.
- The user asks for the progress or result of a previously submitted book.
- The user asks to pause, resume, or cancel a translation job.
- Do not use this skill for PDF, EPUB, DOCX, images, or scanned books unless another workflow has first converted them to TXT or Markdown and the user accepts that conversion.

## Prerequisites

- Python 3.11 or newer; no third-party Python package is required.
- Text Book Translator is running and reachable at `http://127.0.0.1:8000` by default.
- Run the translator with one Uvicorn worker; active-runner detection is process-local.
- The user has configured the model URL, API Key, and model in the translator UI.
- Keep the service on loopback for personal use. A remotely exposed service requires authentication and transport security.

Install this directory as `${HERMES_HOME:-~/.hermes}/skills/book-translator`, preserving `SKILL.md` and `scripts/`.

## How to Run

Run the helper with the native `terminal` tool. Hermes injects the absolute skill directory; resolve `scripts/book_translator.py` against it. In the examples below, `${HERMES_SKILL_DIR}` is replaced by Hermes when the skill loads.

```bash
python3 "${HERMES_SKILL_DIR}/scripts/book_translator.py" preflight
```

Every invocation writes exactly one JSON object to stdout. Progress and safe diagnostics may appear on stderr. Treat the JSON `ok` field and process exit code as authoritative.

## Quick Reference

| Action | Command |
| --- | --- |
| Check service | `preflight` |
| Upload and start | `submit --file PATH --target-language 简体中文` |
| Check progress | `status --job-id JOB_ID` |
| Wait for a terminal state | `wait --job-id JOB_ID --poll-interval 5` |
| Download result | `download --job-id JOB_ID --output-type bilingual.md --output-dir DIR` |
| Pause | `pause --job-id JOB_ID` |
| Resume | `resume --job-id JOB_ID` |
| Cancel | `cancel --job-id JOB_ID` |

Omitting `--job-id` uses the most recent job recorded for this Hermes profile. Prefer the explicit `job_id` returned by `submit` when several translations may be active.

## Procedure

1. Confirm the user explicitly requested translation. Translation sends the book content to the model provider configured in Text Book Translator.
2. Run `preflight`. If `configured` is false, ask the user to configure the model connection in the web UI; never request or inspect their API Key.
3. Confirm the attachment path ends in `.txt` or `.md`. If the target language is omitted, use `简体中文`.
4. Submit the file:

   ```bash
   python3 "${HERMES_SKILL_DIR}/scripts/book_translator.py" submit \
     --file "/absolute/path/book.md" \
     --target-language "简体中文" \
     --translate-mode faithful \
     --translation-level 3 \
     --speed-mode stable
   ```

   The helper hashes file content plus all stable translation parameters into `client_request_id`. A repeated request reuses its job instead of creating duplicate model charges. `pending` jobs start; `paused`, `failed`, or inactive `running`/`pausing` jobs resume; completed jobs with a missing result manifest resume to rebuild it. Active jobs and completed jobs with ready results are reused without another start.

5. Report the returned `job_id` and status. For a long book, do not block the conversation on a foreground command. Run `wait` through `terminal` with background execution and completion notification, or use `status` on later turns.
6. After `wait` returns `status=completed`, require both `result_ready=true` and the requested entry in `outputs`.
7. Download into a directory accessible to the active Hermes channel:

   ```bash
   python3 "${HERMES_SKILL_DIR}/scripts/book_translator.py" download \
     --job-id "JOB_ID" \
     --output-type bilingual.md \
     --output-dir "/absolute/path/outputs"
   ```

8. Use the returned `output_path` with the channel's normal document attachment mechanism. State whether the file is a pure translation or bilingual edition.

## Pitfalls

- Never read translator configuration files or place an API Key in this helper's arguments, output, logs, or Hermes memory.
- Do not retry `submit` with altered defaults unintentionally; any stable translation parameter change creates a different request identity.
- A `wait` timeout does not cancel the server job. Keep the `job_id` and query it later.
- Do not download on `status=completed` alone. The output manifest must also be ready.
- Cancellation is terminal for a deterministic request identity. If the user wants to translate the same file with the same parameters again, explain that they must create a new task in the web UI; never change parameters silently to bypass a cancelled job.
- Later model-connection or corpus-content changes do not alter an existing deterministic request identity. Use a new task in the web UI when the user explicitly wants a fresh translation with changed model or corpus context.
- Do not use `repair-stuck` automatically. A repair request can race an active worker; use `resume`, which is idempotent.
- If a non-loopback `--api-url` is necessary, confirm the deployment has authentication before sending a book.

## Verification

- `preflight` returns `ok=true`, `configured=true`, and lists `.txt` and `.md` capabilities.
- `submit` returns one JSON object containing `job_id`, `client_request_id`, `status`, `reused`, and `action`.
- Repeating the same file and parameters returns the same `job_id` with `reused=true`.
- A completed job returns `result_ready=true` and an output manifest.
- `download` verifies the manifest size and SHA-256 before returning `output_path`.
