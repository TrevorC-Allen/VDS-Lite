from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


class ProjectStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def list_projects(self) -> list[dict[str, Any]]:
        state = self._load()
        return sorted(
            state["projects"].values(),
            key=lambda item: (
                1 if item.get("pinned") else 0,
                str(item.get("pinned_at") or item.get("updated_at") or ""),
                str(item.get("updated_at") or ""),
            ),
            reverse=True,
        )

    def search(self, query: str, *, limit: int = 40) -> list[dict[str, Any]]:
        state = self._load()
        normalized_query = _normalize_search_text(query)
        projects = state["projects"]
        conversations = state["conversations"]
        results: list[dict[str, Any]] = []

        for project in projects.values():
            project_name = str(project.get("name") or "")
            if not normalized_query or normalized_query in _normalize_search_text(project_name):
                results.append(
                    {
                        "result_type": "project",
                        "project_id": project.get("project_id"),
                        "conversation_id": "",
                        "title": project_name or "未命名项目",
                        "subtitle": "项目",
                        "snippet": _search_snippet(project_name, normalized_query),
                        "updated_at": project.get("updated_at") or project.get("created_at") or "",
                        "pinned": bool(project.get("pinned")),
                    }
                )

        for conversation in conversations.values():
            project = projects.get(str(conversation.get("project_id") or ""), {})
            title = str(conversation.get("title") or "新对话")
            searchable_parts = [title, str(project.get("name") or "")]
            for turn in conversation.get("turns") or []:
                searchable_parts.extend(_turn_search_texts(turn))
            haystack = "\n".join(searchable_parts)
            if normalized_query and normalized_query not in _normalize_search_text(haystack):
                continue
            snippet = _search_snippet(haystack, normalized_query) if normalized_query else _conversation_preview(conversation)
            results.append(
                {
                    "result_type": "conversation",
                    "project_id": conversation.get("project_id"),
                    "conversation_id": conversation.get("conversation_id"),
                    "title": title,
                    "subtitle": str(project.get("name") or "普通聊天"),
                    "snippet": snippet,
                    "updated_at": conversation.get("updated_at") or conversation.get("created_at") or "",
                    "pinned": bool(conversation.get("pinned")),
                }
            )

        return sorted(
            results,
            key=lambda item: (
                1 if item.get("pinned") else 0,
                str(item.get("updated_at") or ""),
            ),
            reverse=True,
        )[:limit]

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        return self._load()["projects"].get(project_id)

    def ensure_default_project(self) -> dict[str, Any]:
        state = self._load()
        if state["projects"]:
            return next(iter(state["projects"].values()))
        project = self._new_project("默认项目")
        state["projects"][project["project_id"]] = project
        self._save(state)
        return project

    def create_project(self, name: str | None = None) -> dict[str, Any]:
        state = self._load()
        project = self._new_project(name or f"项目 {len(state['projects']) + 1}")
        state["projects"][project["project_id"]] = project
        self._save(state)
        return project

    def update_project_dataset(self, project_id: str, dataset_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        state = self._load()
        project = state["projects"].get(project_id)
        if project is None:
            raise KeyError(f"project not found: {project_id}")
        project["current_dataset_id"] = dataset_id
        project["dataset_profile_summary"] = _profile_summary(profile)
        sources = project.setdefault("sources", [])
        source = {
            "source_id": f"src_{dataset_id}",
            "source_type": "dataset",
            "dataset_id": dataset_id,
            "title": _dataset_source_title(profile),
            "metadata": _profile_summary(profile),
            "created_at": _now_id(),
        }
        sources[:] = [item for item in sources if item.get("dataset_id") != dataset_id]
        sources.insert(0, source)
        project["updated_at"] = _now_id()
        self._save(state)
        return project

    def update_project(self, project_id: str, *, name: str | None = None, pinned: bool | None = None) -> dict[str, Any]:
        state = self._load()
        project = state["projects"].get(project_id)
        if project is None:
            raise KeyError(f"project not found: {project_id}")
        if name is not None and name.strip():
            project["name"] = name.strip()
        if pinned is not None:
            project["pinned"] = bool(pinned)
            project["pinned_at"] = _now_id() if pinned else ""
        project["updated_at"] = _now_id()
        self._save(state)
        return project

    def delete_project(self, project_id: str) -> dict[str, Any]:
        state = self._load()
        if project_id not in state["projects"]:
            raise KeyError(f"project not found: {project_id}")
        state["projects"].pop(project_id)
        state["conversations"] = {
            conversation_id: conversation
            for conversation_id, conversation in state["conversations"].items()
            if conversation.get("project_id") != project_id
        }
        self._save(state)
        return {"project_id": project_id, "deleted": True}

    def list_conversations(self, project_id: str | None = None) -> list[dict[str, Any]]:
        state = self._load()
        normalized_project_id = str(project_id or "")
        conversations = [
            conversation
            for conversation in state["conversations"].values()
            if str(conversation.get("project_id") or "") == normalized_project_id
        ]
        return sorted(
            conversations,
            key=lambda item: (
                1 if item.get("pinned") else 0,
                str(item.get("pinned_at") or item.get("updated_at") or ""),
                str(item.get("updated_at") or ""),
            ),
            reverse=True,
        )

    def create_conversation(
        self,
        *,
        project_id: str | None = None,
        title: str | None = None,
        dataset_id: str | None = None,
    ) -> dict[str, Any]:
        state = self._load()
        normalized_project_id = str(project_id or "")
        project = None
        if normalized_project_id:
            project = state["projects"].get(normalized_project_id)
            if project is None:
                raise KeyError(f"project not found: {normalized_project_id}")
        conversation = self._new_conversation(
            project_id=normalized_project_id,
            title=title or "新对话",
            dataset_id=dataset_id or (project or {}).get("current_dataset_id") or "",
        )
        state["conversations"][conversation["conversation_id"]] = conversation
        self._save(state)
        return conversation

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        return self._load()["conversations"].get(conversation_id)

    def update_conversation(
        self,
        conversation_id: str,
        *,
        title: str | None = None,
        pinned: bool | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        state = self._load()
        conversation = state["conversations"].get(conversation_id)
        if conversation is None:
            raise KeyError(f"conversation not found: {conversation_id}")
        if title is not None and title.strip():
            conversation["title"] = title.strip()[:80]
        if pinned is not None:
            conversation["pinned"] = bool(pinned)
            conversation["pinned_at"] = _now_id() if pinned else ""
        if project_id is not None:
            if project_id not in state["projects"]:
                raise KeyError(f"project not found: {project_id}")
            conversation["project_id"] = project_id
        conversation["updated_at"] = _now_id()
        self._save(state)
        return conversation

    def delete_conversation(self, conversation_id: str) -> dict[str, Any]:
        state = self._load()
        if conversation_id not in state["conversations"]:
            raise KeyError(f"conversation not found: {conversation_id}")
        state["conversations"].pop(conversation_id)
        self._save(state)
        return {"conversation_id": conversation_id, "deleted": True}

    def append_turn(self, conversation_id: str, turn: dict[str, Any]) -> dict[str, Any]:
        state = self._load()
        conversation = state["conversations"].get(conversation_id)
        if conversation is None:
            raise KeyError(f"conversation not found: {conversation_id}")
        turns = conversation.setdefault("turns", [])
        turns.append(turn)
        if turn.get("question") and conversation.get("title") in {"新对话", ""}:
            conversation["title"] = str(turn["question"])[:40]
        conversation["dataset_id"] = turn.get("dataset_id") or conversation.get("dataset_id") or ""
        conversation["updated_at"] = _now_id()
        self._save(state)
        return conversation

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"projects": {}, "conversations": {}}
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {"projects": {}, "conversations": {}}
        state.setdefault("projects", {})
        state.setdefault("conversations", {})
        if self._migrate_legacy_default_project(state):
            self._save(state)
        return state

    def _save(self, state: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _new_project(self, name: str, *, project_id: str | None = None) -> dict[str, Any]:
        created_at = _now_id()
        return {
            "project_id": project_id or f"proj_{uuid4().hex[:10]}",
            "name": name,
            "current_dataset_id": "",
            "dataset_profile_summary": {},
            "sources": [],
            "memories": [],
            "pinned": False,
            "pinned_at": "",
            "created_at": created_at,
            "updated_at": created_at,
        }

    def _new_conversation(self, *, project_id: str, title: str, dataset_id: str) -> dict[str, Any]:
        created_at = _now_id()
        return {
            "conversation_id": f"conv_{uuid4().hex[:12]}",
            "project_id": project_id,
            "title": title,
            "dataset_id": dataset_id,
            "turns": [],
            "pinned": False,
            "pinned_at": "",
            "created_at": created_at,
            "updated_at": created_at,
        }

    def _migrate_legacy_default_project(self, state: dict[str, Any]) -> bool:
        changed = False
        projects = state.get("projects") or {}
        conversations = state.get("conversations") or {}
        for project_id, project in list(projects.items()):
            if str(project.get("name") or "") != "默认项目":
                continue
            if project.get("pinned") or project.get("memories"):
                continue
            for conversation in conversations.values():
                if str(conversation.get("project_id") or "") == project_id:
                    conversation["project_id"] = ""
                    changed = True
            projects.pop(project_id, None)
            changed = True
        return changed


def _profile_summary(profile: dict[str, Any]) -> dict[str, Any]:
    tables = profile.get("tables") if isinstance(profile.get("tables"), list) else [profile]
    return {
        "dataset_kind": profile.get("dataset_kind"),
        "table_count": len(tables),
        "tables": [
            {
                "table_name": table.get("table_name") or table.get("original_filename") or "table",
                "row_count": table.get("row_count"),
                "column_count": table.get("column_count"),
            }
            for table in tables[:8]
            if isinstance(table, dict)
        ],
    }


def _dataset_source_title(profile: dict[str, Any]) -> str:
    tables = profile.get("tables") if isinstance(profile.get("tables"), list) else [profile]
    names = [
        str(table.get("original_filename") or table.get("table_name") or "").strip()
        for table in tables[:3]
        if isinstance(table, dict)
    ]
    names = [name for name in names if name]
    if not names:
        return "上传的数据源"
    suffix = "" if len(tables) <= 3 else f" 等 {len(tables)} 张表"
    return "、".join(names) + suffix


def _now_id() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_search_text(value: Any) -> str:
    return str(value or "").casefold().strip()


def _turn_search_texts(turn: dict[str, Any]) -> list[str]:
    texts = [
        str(turn.get("question") or ""),
        str(turn.get("direct_answer") or ""),
        str(turn.get("intent") or ""),
        str(turn.get("execution_error") or ""),
    ]
    sections = turn.get("response_sections")
    if isinstance(sections, dict):
        for value in sections.values():
            if isinstance(value, list):
                texts.extend(str(item) for item in value)
            elif value:
                texts.append(str(value))
    return texts


def _search_snippet(text: str, normalized_query: str) -> str:
    text = " ".join(str(text or "").split())
    if not text:
        return ""
    if not normalized_query:
        return text[:160]
    index = _normalize_search_text(text).find(normalized_query)
    if index < 0:
        return text[:160]
    start = max(0, index - 42)
    end = min(len(text), index + len(normalized_query) + 96)
    prefix = "..." if start else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"


def _conversation_preview(conversation: dict[str, Any]) -> str:
    turns = conversation.get("turns") or []
    if turns:
        first_turn = turns[0]
        return _search_snippet(
            str(first_turn.get("question") or first_turn.get("direct_answer") or ""),
            "",
        )
    return "暂无消息。"
