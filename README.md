# text-book-translator

本地英文书籍翻译工具。上传 `.txt` / `.md` 文件后，通过腾讯云 TokenHub 的 `hy-mt2-pro` 模型进行段落级对齐翻译，默认输出简体中文，支持暂停、继续、断点续跑、SSE 实时状态和多格式结果导出。

## 功能

- 本地网页拖拽上传 `.txt` / `.md`
- 左右双栏原文 / 译文对照
- 段落级 `segment_id` 对齐
- 自动分段、分块，但前端不暴露 chunk 细节
- 点击任意段落联动高亮和滚动
- 支持暂停、继续、停止
- 支持流式增量显示，失败时自动回退到非流式
- 所有 chunk 完成后立即落盘，支持断点续跑
- 可导出 `translated.md`、`bilingual.md`、`aligned.jsonl`、`translation_log.json`

## 项目结构

```text
text-book-translator/
  backend/
    app.py
    config.py
    requirements.txt
    config.example.json
    config.local.json
    translator/
      __init__.py
      text_loader.py
      segmenter.py
      chunker.py
      context_builder.py
      hy_mt2_client.py
      pipeline.py
      exporter.py
      storage.py
      validator.py
    data/
      uploads/
      jobs/
      outputs/
  frontend/
    package.json
    index.html
    src/
      main.jsx
      App.jsx
      api.js
      styles.css
      components/
        DropZone.jsx
        Toolbar.jsx
        TranslationViewer.jsx
        ProgressPanel.jsx
  cli.py
  .gitignore
  README.md
```

## 1. 创建 Python 虚拟环境

macOS / Linux：

```bash
python3 -m venv .venv
```

如果本机 `python3` 低于 3.10，请改用实际可用的 3.10+ 解释器，例如：

```bash
python3.11 -m venv .venv
```

Windows PowerShell：

```powershell
python -m venv .venv
```

当前项目已在根目录创建 `.venv`，本次实际使用的是 `python3.11`。

## 2. 安装 Python 依赖

macOS / Linux：

```bash
source .venv/bin/activate
pip install -r backend/requirements.txt
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
```

## 3. 安装前端依赖

```bash
cd frontend
npm install
```

## 4. 填写项目根目录 `.env`

推荐直接修改项目根目录的 [.env](/Users/xx/ai/fanyi/text-book-translator/.env)。前端和后端都会读取这一个文件：

```dotenv
# Frontend
VITE_API_BASE=http://127.0.0.1:8000

# Backend
TOKENHUB_API_KEY=your-real-api-key
TOKENHUB_BASE_URL=https://tokenhub.tencentmaas.com/v1
TRANSLATION_MODEL=hy-mt2-pro
DEFAULT_TARGET_LANGUAGE=简体中文
TRANSLATION_TEMPERATURE=0.1
TRANSLATION_STREAM=true
CHUNK_SIZE_CHARS=3500
MAX_RETRIES=3
```

说明：

- `VITE_API_BASE` 是前端请求后端的地址
- `TOKENHUB_API_KEY` 是必填项
- 其余项不改也可以，按默认值运行

如需保留旧方式，后端仍兼容 [backend/config.local.json](/Users/xx/ai/fanyi/text-book-translator/backend/config.local.json)，但 `.env` 的优先级更高。

## 5. 启动后端

macOS / Linux：

```bash
source .venv/bin/activate
uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```

## 6. 启动前端

```bash
cd frontend
npm install
npm run dev
```

默认前端访问地址通常是 `http://127.0.0.1:5173`。如果后端地址变化，只改根目录 `.env` 里的 `VITE_API_BASE` 即可。

## 7. 上传文件翻译

1. 打开本地前端页面。
2. 拖拽或点击选择 `.txt` / `.md` 文件。
3. 选择目标语言、翻译模式、是否流式和 chunk size。
4. 点击“开始翻译”。
5. 页面会显示文件信息、任务状态、当前章节、当前 segment 和双栏对齐内容。

## 8. 暂停 / 继续

- 点击“暂停”后，任务状态先变为 `pausing`
- 当前 chunk 完成并落盘后，状态变为 `paused`
- 点击“继续”后，会从第一个 `pending` 或 `failed` 的位置恢复
- 已成功的 segment 不会重复翻译

## 9. CLI 翻译

CLI 复用同一套 pipeline：

```bash
source .venv/bin/activate
python cli.py translate --input ./book.txt --target-language 简体中文 --resume
```

更多参数示例：

```bash
python cli.py translate \
  --input ./book.md \
  --target-language 日语 \
  --translation-mode 阅读优化 \
  --chunk-size-chars 3200 \
  --stream
```

## 10. 下载结果

翻译任务完成、暂停或失败后，可以从页面右上角直接下载：

- `translated.md`
- `bilingual.md`
- `aligned.jsonl`
- `translation_log.json`

文件实际写入位置为：

```text
backend/data/jobs/{job_id}/outputs/
```

## 11. OpenClaw 调用方式

方式一：调用 CLI

```bash
python cli.py translate --input ./book.txt --target-language 简体中文 --resume
```

方式二：调用本地 HTTP API

上传：

```bash
curl -X POST http://127.0.0.1:8000/api/jobs/upload \
  -F "file=@./book.txt" \
  -F "target_language=简体中文" \
  -F "translation_mode=忠实翻译" \
  -F "stream=true" \
  -F "chunk_size_chars=3500"
```

开始：

```bash
curl -X POST http://127.0.0.1:8000/api/jobs/{job_id}/start
```

暂停：

```bash
curl -X POST http://127.0.0.1:8000/api/jobs/{job_id}/pause
```

继续：

```bash
curl -X POST http://127.0.0.1:8000/api/jobs/{job_id}/resume
```

停止：

```bash
curl -X POST http://127.0.0.1:8000/api/jobs/{job_id}/cancel
```

SSE：

```bash
curl http://127.0.0.1:8000/api/jobs/{job_id}/events
```

## 设计说明

- `segment` 是前端展示和对齐的最小单位
- `chunk` 是后端调用模型的最小单位
- 请求中会把多个 segment 包装成带 `segment id` 的结构发给模型
- 返回结果按 `segment_id` 解析并写回 `segments.json`
- 每个 chunk 完成后立刻写入 `chunks/chunk_*.json`
- 任务状态包含 `pending`、`running`、`pausing`、`paused`、`completed`、`failed`、`cancelled`

## 本地检查

项目已完成一次本地 Python 语法检查。前端依赖安装和 `vite build` 需要你在本机执行 `npm install` 后再跑。
