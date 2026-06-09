from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from backend.apps.ops.store import OpsStore


class EvaluationPayload(BaseModel):
    run_id: str | None = None
    runId: str | None = None
    question: str
    exactness: float
    faithfulness: float
    coverage: float
    safety: float
    notes: str | None = None


class TemplatePayload(BaseModel):
    name: str
    scenario: str | None = None
    steps: list[str] | str = []
    capabilities: list[str] = []


class QaPayload(BaseModel):
    question: str
    answer: str
    evidence: str | None = None


router = APIRouter(prefix="/api/ops", tags=["ops"])
ops_store = OpsStore(Path("storage") / "ops_state.json", Path("storage") / "rag_documents")


@router.get("/state")
def get_state() -> dict[str, Any]:
    return ops_store.load_state()


@router.post("/evaluations")
def add_evaluation(payload: EvaluationPayload) -> dict[str, Any]:
    record = ops_store.add_evaluation(payload.model_dump())
    return {"record": record, "state": ops_store.load_state()}


@router.post("/templates")
def add_template(payload: TemplatePayload) -> dict[str, Any]:
    template = ops_store.add_template(payload.model_dump())
    return {"template": template, "state": ops_store.load_state()}


@router.post("/rag/qa")
def add_qa_pair(payload: QaPayload) -> dict[str, Any]:
    pair = ops_store.add_qa_pair(payload.model_dump())
    return {"qa_pair": pair, "state": ops_store.load_state()}


@router.post("/rag/documents")
async def upload_rag_documents(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    temp_dir = Path("storage") / "tmp" / "rag"
    temp_dir.mkdir(parents=True, exist_ok=True)
    documents: list[dict[str, Any]] = []
    temp_paths: list[Path] = []
    try:
        for index, file in enumerate(files, start=1):
            filename = file.filename or f"document_{index}.txt"
            temp_path = temp_dir / f"{index}_{filename}"
            temp_path.write_bytes(await file.read())
            temp_paths.append(temp_path)
            try:
                documents.append(ops_store.add_rag_document(temp_path, filename))
            except Exception as error:
                raise HTTPException(status_code=400, detail=f"{filename}: {error}") from error
        return {"documents": documents, "state": ops_store.load_state()}
    finally:
        for temp_path in temp_paths:
            temp_path.unlink(missing_ok=True)
