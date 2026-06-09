# VDS Lite Agent

Standalone MVP for CSV / multi-file / Excel analysis with an LLM-generated Pandas execution loop and a lightweight VDS-style web UI.

The backend does not contain a hardcoded ability router or deterministic intent parser. The LLM receives the full supported file content, table profile, and user question, then decides the intent, table usage, joins, analysis steps, and Pandas code. The backend only stores file context, calls the LLM, validates generated code, executes `analyze(df)` or `analyze(tables)`, and records the result.

## Run tests

```bash
/Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest -q
```

## Run API

```bash
VDS_LITE_LLM_PROVIDER=openai OPENAI_API_KEY=... uvicorn backend.main:app --reload --port 8890
```

Use `VDS_LITE_LLM_PROVIDER=deepseek` with `DEEPSEEK_API_KEY` for DeepSeek-compatible chat completions.

Open the browser UI at:

```text
http://127.0.0.1:8890/app
```

## API

- `POST /api/chat/upload`: upload one small CSV or `.xlsx` workbook.
- `POST /api/chat/upload-batch`: upload multiple small CSV files as separate tables.
- `POST /api/chat/ask`: ask a question with `dataset_id` and `question`.
- `GET /api/chat/sessions/{dataset_id}`: reload profile for an uploaded dataset.
- `GET /api/chat/runs/{run_id}`: placeholder for run lookup in the MVP.

The LLM sees the full supported file content for small files. Generated code must define `analyze(df) -> dict` for single-table datasets or `analyze(tables) -> dict` for multi-table / Excel datasets; the backend validates and executes it in a short-lived process.
