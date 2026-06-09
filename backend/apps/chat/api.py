from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from backend.apps.ai_model.model_factory import create_llm_client
from backend.apps.chat.project_store import ProjectStore
from backend.apps.chat.task.llm_pandas import LlmPandasAgent
from backend.apps.datasource.store import CsvDatasetStore


class AskPayload(BaseModel):
    dataset_id: str | None = None
    question: str
    project_id: str | None = None
    conversation_id: str | None = None


class CreateProjectPayload(BaseModel):
    name: str | None = None


class UpdateProjectPayload(BaseModel):
    name: str | None = None
    pinned: bool | None = None


class CreateConversationPayload(BaseModel):
    project_id: str | None = None
    title: str | None = None


class UpdateConversationPayload(BaseModel):
    title: str | None = None
    pinned: bool | None = None
    project_id: str | None = None


router = APIRouter(prefix="/api/chat", tags=["chat"])
store = CsvDatasetStore(root_dir=Path("storage"))
project_store = ProjectStore(path=Path("storage") / "chat_state.json")
run_records: dict[str, dict[str, Any]] = {}
conversation_records: dict[str, list[dict[str, Any]]] = {}


@router.post("/upload")
async def upload(file: UploadFile = File(...), project_id: str | None = Form(None)) -> dict[str, Any]:
    temp_dir = Path("storage") / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / (file.filename or "upload.csv")
    try:
        temp_path.write_bytes(await file.read())
        try:
            dataset = store.save_upload(temp_path, original_filename=file.filename)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except ImportError as error:
            raise HTTPException(status_code=500, detail=str(error)) from error
        project = project_store.get_project(project_id) if project_id else None
        if project_id and project is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        if project is not None:
            project_store.update_project_dataset(project["project_id"], dataset.dataset_id, dataset.profile)
        return {
            "dataset_id": dataset.dataset_id,
            "project_id": project["project_id"] if project else "",
            "profile": dataset.profile,
            "csv_text": dataset.csv_text,
        }
    finally:
        temp_path.unlink(missing_ok=True)


@router.post("/upload-batch")
async def upload_batch(files: list[UploadFile] = File(...), project_id: str | None = Form(None)) -> dict[str, Any]:
    temp_dir = Path("storage") / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_paths: list[Path] = []
    try:
        for index, file in enumerate(files, start=1):
            temp_path = temp_dir / f"{index}_{file.filename or 'upload.csv'}"
            temp_path.write_bytes(await file.read())
            temp_paths.append(temp_path)
        try:
            dataset = store.save_uploads(temp_paths, [file.filename for file in files])
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except ImportError as error:
            raise HTTPException(status_code=500, detail=str(error)) from error
        project = project_store.get_project(project_id) if project_id else None
        if project_id and project is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        if project is not None:
            project_store.update_project_dataset(project["project_id"], dataset.dataset_id, dataset.profile)
        return {
            "dataset_id": dataset.dataset_id,
            "project_id": project["project_id"] if project else "",
            "profile": dataset.profile,
            "csv_text": dataset.csv_text,
        }
    finally:
        for temp_path in temp_paths:
            temp_path.unlink(missing_ok=True)


@router.post("/ask")
def ask(payload: AskPayload) -> dict[str, Any]:
    conversation = project_store.get_conversation(payload.conversation_id) if payload.conversation_id else None
    project_id = payload.project_id or (conversation or {}).get("project_id") or ""
    project = project_store.get_project(project_id) if project_id else None
    if project_id and project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    dataset_id = payload.dataset_id or (conversation or {}).get("dataset_id") or (project or {}).get("current_dataset_id")
    if not dataset_id:
        detail = "No dataset is available for this project. Upload a file first." if project_id else "No dataset is available. Upload a file first."
        raise HTTPException(status_code=400, detail=detail)
    dataset = store.load(dataset_id)
    if conversation is None:
        conversation = project_store.create_conversation(
            project_id=project_id,
            title=payload.question[:40],
            dataset_id=dataset_id,
        )
    conversation_id = conversation["conversation_id"]
    history = conversation.get("turns", [])
    try:
        agent = LlmPandasAgent(llm_client=create_llm_client())
        response = agent.ask(dataset=dataset, question=payload.question, conversation_history=history)
    except Exception as error:
        response = {
            "run_id": f"run_{uuid4().hex[:12]}",
            "direct_answer": "",
            "rows": [],
            "columns": [],
            "intent": "",
            "data_brief": {},
            "semantic_interpretation": {},
            "assumptions": [],
            "expected_output": "",
            "response_sections": {},
            "chart": {},
            "pandas_code": "",
            "llm_raw": "",
            "sanity_checks": {"ok": False, "checks": [], "errors": []},
            "execution_error": f"{type(error).__name__}: {error}",
            "attempts": [
                {
                    "attempt": 1,
                    "ok": False,
                    "llm_raw": "",
                    "pandas_code": "",
                    "error": f"{type(error).__name__}: {error}",
                }
            ],
        }
    response["conversation_id"] = conversation_id
    response["project_id"] = project_id
    response["dataset_id"] = dataset_id
    turn_record = {
        "run_id": response["run_id"],
        "dataset_id": dataset_id,
        "question": payload.question,
        "direct_answer": response.get("direct_answer", ""),
        "intent": response.get("intent", ""),
        "rows": response.get("rows", []),
        "columns": response.get("columns", []),
        "response_sections": response.get("response_sections", {}),
        "chart": response.get("chart", {}),
        "pandas_code": response.get("pandas_code", ""),
        "execution_error": response.get("execution_error"),
    }
    conversation_records.setdefault(conversation_id, []).append(turn_record)
    project_store.append_turn(conversation_id, turn_record)
    run_records[response["run_id"]] = {
        "run_id": response["run_id"],
        "dataset_id": dataset_id,
        "project_id": project_id,
        "conversation_id": conversation_id,
        "question": payload.question,
        "status": "failed" if response.get("execution_error") else "completed",
        "payload": response,
    }
    return response


@router.get("/projects")
def projects() -> dict[str, Any]:
    return {"projects": project_store.list_projects()}


@router.get("/search")
def search(q: str = Query("", max_length=200), limit: int = Query(40, ge=1, le=100)) -> dict[str, Any]:
    return {"query": q, "results": project_store.search(q, limit=limit)}


@router.post("/projects")
def create_project(payload: CreateProjectPayload) -> dict[str, Any]:
    project = project_store.create_project(payload.name)
    return {"project": project}


@router.get("/projects/{project_id}")
def project(project_id: str) -> dict[str, Any]:
    project = project_store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return {
        "project": project,
        "conversations": project_store.list_conversations(project_id),
        "sources": project.get("sources", []),
        "memories": project.get("memories", []),
    }


@router.patch("/projects/{project_id}")
def update_project(project_id: str, payload: UpdateProjectPayload) -> dict[str, Any]:
    try:
        project = project_store.update_project(project_id, name=payload.name, pinned=payload.pinned)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"project": project}


@router.delete("/projects/{project_id}")
def delete_project(project_id: str) -> dict[str, Any]:
    try:
        return project_store.delete_project(project_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/conversations")
def create_conversation(payload: CreateConversationPayload) -> dict[str, Any]:
    project_id = payload.project_id or ""
    project = project_store.get_project(project_id) if project_id else None
    if project_id and project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    conversation = project_store.create_conversation(project_id=project_id, title=payload.title)
    return {"conversation": conversation}


@router.get("/conversations")
def conversations(project_id: str | None = Query(None)) -> dict[str, Any]:
    if project_id and project_store.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return {"conversations": project_store.list_conversations(project_id or "")}


@router.get("/projects/{project_id}/conversations")
def project_conversations(project_id: str) -> dict[str, Any]:
    project = project_store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return {
        "project": project,
        "conversations": project_store.list_conversations(project_id),
    }


@router.get("/conversations/{conversation_id}")
def conversation(conversation_id: str) -> dict[str, Any]:
    stored = project_store.get_conversation(conversation_id)
    if stored is not None:
        return {**stored, "dataset_available": _dataset_available(stored.get("dataset_id"))}
    return {
        "conversation_id": conversation_id,
        "turns": conversation_records.get(conversation_id, []),
    }


@router.patch("/conversations/{conversation_id}")
def update_conversation(conversation_id: str, payload: UpdateConversationPayload) -> dict[str, Any]:
    try:
        conversation = project_store.update_conversation(
            conversation_id,
            title=payload.title,
            pinned=payload.pinned,
            project_id=payload.project_id,
        )
        if payload.project_id and conversation.get("dataset_id"):
            try:
                dataset = store.load(str(conversation["dataset_id"]))
                project_store.update_project_dataset(payload.project_id, dataset.dataset_id, dataset.profile)
                conversation = project_store.get_conversation(conversation_id) or conversation
            except KeyError:
                pass
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"conversation": conversation}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict[str, Any]:
    try:
        return project_store.delete_conversation(conversation_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/sessions/{dataset_id}")
def session(dataset_id: str) -> dict[str, Any]:
    try:
        dataset = store.load(dataset_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {
        "dataset_id": dataset.dataset_id,
        "original_filename": dataset.original_filename,
        "profile": dataset.profile,
    }


@router.get("/runs/{run_id}")
def run(run_id: str) -> dict[str, Any]:
    record = run_records.get(run_id)
    if record is None:
        return {"run_id": run_id, "status": "not_found", "payload": None}
    return record


def _dataset_available(dataset_id: Any) -> bool:
    if not dataset_id:
        return False
    try:
        store.load(str(dataset_id))
    except KeyError:
        return False
    return True
