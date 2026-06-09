from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.apps.datasource.store import _extract_document_text, _normalize_document_text


RAG_CHUNK_CHARS = 900


class OpsStore:
    def __init__(self, state_path: Path | str, rag_dir: Path | str):
        self.state_path = Path(state_path)
        self.rag_dir = Path(rag_dir)
        self._lock = threading.Lock()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.rag_dir.mkdir(parents=True, exist_ok=True)

    def load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self._default_state()
        try:
            stored = json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            stored = {}
        state = self._default_state()
        state.update({key: value for key, value in stored.items() if key in state})
        state["evaluations"] = list(stored.get("evaluations") or [])
        state["templates"] = list(stored.get("templates") or state["templates"])
        state["experience_cases"] = list(stored.get("experience_cases") or state["experience_cases"])
        rag = dict(state["rag"])
        rag.update(stored.get("rag") or {})
        rag["enabled"] = False
        rag["documents"] = list((stored.get("rag") or {}).get("documents") or [])
        rag["qa_pairs"] = list((stored.get("rag") or {}).get("qa_pairs") or [])
        state["rag"] = rag
        state["metrics"] = self._metrics(state["evaluations"])
        return state

    def save_state(self, state: dict[str, Any]) -> dict[str, Any]:
        state = dict(state)
        state.setdefault("rag", {})["enabled"] = False
        state["metrics"] = self._metrics(state.get("evaluations") or [])
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return state

    def add_evaluation(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            state = self.load_state()
            record = {
                "id": f"eval_{uuid4().hex[:10]}",
                "run_id": str(payload.get("run_id") or payload.get("runId") or "").strip() or "manual",
                "question": str(payload.get("question") or "").strip() or "未命名问题",
                "exactness": _score(payload.get("exactness")),
                "faithfulness": _score(payload.get("faithfulness")),
                "coverage": _score(payload.get("coverage")),
                "safety": _score(payload.get("safety")),
                "notes": str(payload.get("notes") or "").strip(),
                "created_at": _now(),
            }
            state["evaluations"].insert(0, record)
            self.save_state(state)
            return record

    def add_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            state = self.load_state()
            steps = payload.get("steps") or []
            if isinstance(steps, str):
                steps = [item.strip() for item in re.split(r"\n+", steps) if item.strip()]
            template = {
                "id": f"tpl_{uuid4().hex[:10]}",
                "name": str(payload.get("name") or "").strip() or "未命名分析模板",
                "scenario": str(payload.get("scenario") or "").strip(),
                "steps": [str(step).strip() for step in steps if str(step).strip()],
                "capabilities": [str(item) for item in (payload.get("capabilities") or [])],
                "created_at": _now(),
                "source": "user_configured",
            }
            state["templates"].insert(0, template)
            self.save_state(state)
            return template

    def add_qa_pair(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            state = self.load_state()
            pair = {
                "id": f"qa_{uuid4().hex[:10]}",
                "question": str(payload.get("question") or "").strip(),
                "answer": str(payload.get("answer") or "").strip(),
                "evidence": str(payload.get("evidence") or "").strip(),
                "created_at": _now(),
            }
            state["rag"]["qa_pairs"].insert(0, pair)
            self.save_state(state)
            return pair

    def add_rag_document(self, source_path: Path, original_filename: str) -> dict[str, Any]:
        text = _normalize_document_text(_extract_document_text(source_path))
        if not text:
            text = _normalize_document_text(source_path.read_text(encoding="utf-8", errors="ignore"))
        chunks = _chunk_text(text)
        document_id = f"ragdoc_{uuid4().hex[:10]}"
        doc_dir = self.rag_dir / document_id
        doc_dir.mkdir(parents=True, exist_ok=True)
        stored_path = doc_dir / original_filename
        shutil.copyfile(source_path, stored_path)
        chunk_records = [
            {
                "id": f"{document_id}_chunk_{index}",
                "source": original_filename,
                "chunk_index": index,
                "text": chunk,
                "char_count": len(chunk),
                "token_estimate": max(1, len(chunk) // 4),
                "sha256": hashlib.sha256(chunk.encode("utf-8")).hexdigest(),
            }
            for index, chunk in enumerate(chunks, start=1)
        ]
        document = {
            "id": document_id,
            "name": original_filename,
            "stored_path": str(stored_path),
            "status": "parsed_not_enabled",
            "enabled": False,
            "chunk_count": len(chunk_records),
            "char_count": len(text),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "created_at": _now(),
            "chunks": chunk_records,
        }
        with self._lock:
            state = self.load_state()
            state["rag"]["documents"].insert(0, document)
            state["rag"]["enabled"] = False
            self.save_state(state)
            return document

    @staticmethod
    def _default_state() -> dict[str, Any]:
        return {
            "evaluations": [],
            "metrics": {
                "exactness": 0,
                "faithfulness": 0,
                "coverage": 0,
                "safety": 0,
                "total_runs": 0,
                "risk_count": 0,
            },
            "rag": {
                "enabled": False,
                "documents": [],
                "qa_pairs": [],
                "retrieval": {
                    "vector": "not_enabled",
                    "hybrid": "not_enabled",
                    "note": "RAG construction records are stored, but retrieval is not connected to chat answers yet.",
                },
            },
            "templates": [
                {
                    "id": "tpl_rca_system",
                    "name": "Reasoning-driven RCA 根因分析",
                    "scenario": "分销额下降、目标缺口、拜访转化异常",
                    "steps": ["确认指标口径", "拆分维度贡献", "关联拜访/陈列/目标表", "输出证据和下一步动作"],
                    "capabilities": ["database", "webSearch", "nlSql", "nlLf"],
                    "source": "system_seed",
                }
            ],
            "experience_cases": [],
        }

    @staticmethod
    def _metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
        def average(key: str) -> float:
            if not records:
                return 0
            return round(sum(float(record.get(key) or 0) for record in records) / len(records), 4)

        return {
            "exactness": average("exactness"),
            "faithfulness": average("faithfulness"),
            "coverage": average("coverage"),
            "safety": average("safety"),
            "total_runs": len(records),
            "risk_count": sum(
                1
                for record in records
                if min(float(record.get("exactness") or 0), float(record.get("faithfulness") or 0), float(record.get("coverage") or 0), float(record.get("safety") or 0)) < 0.8
            ),
        }


def _chunk_text(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return [""]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + RAG_CHUNK_CHARS)
        boundary = text.rfind("\n", start, end)
        if boundary <= start + RAG_CHUNK_CHARS // 2:
            boundary = end
        chunk = text[start:boundary].strip()
        if chunk:
            chunks.append(chunk)
        start = boundary
    return chunks or [text]


def _score(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(1, number))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
