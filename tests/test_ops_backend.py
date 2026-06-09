from pathlib import Path

from backend.apps.ops.store import OpsStore


def test_rag_document_upload_creates_real_disabled_chunks(tmp_path: Path) -> None:
    store = OpsStore(tmp_path / "ops_state.json", tmp_path / "rag_docs")
    source = tmp_path / "rules.md"
    source.write_text(
        "# 业务规则\n"
        "日目标 = 月目标 / 当月分销天数。\n"
        "补金额 = max(80%日目标 - 当日分销额, 0)。\n"
        "答案必须展示来源证据片段。\n",
        encoding="utf-8",
    )

    document = store.add_rag_document(source, "rules.md")
    state = store.load_state()

    assert document["name"] == "rules.md"
    assert document["enabled"] is False
    assert document["status"] == "parsed_not_enabled"
    assert document["chunk_count"] >= 1
    assert document["chunks"][0]["text"].startswith("# 业务规则")
    assert document["chunks"][0]["source"] == "rules.md"
    assert state["rag"]["enabled"] is False
    assert state["rag"]["documents"][0]["id"] == document["id"]


def test_evaluations_and_templates_are_persisted(tmp_path: Path) -> None:
    store = OpsStore(tmp_path / "ops_state.json", tmp_path / "rag_docs")

    evaluation = store.add_evaluation(
        {
            "run_id": "run_001",
            "question": "总销售额是多少？",
            "exactness": 0.91,
            "faithfulness": 0.88,
            "coverage": 0.82,
            "safety": 0.99,
            "notes": "人工评估",
        }
    )
    template = store.add_template(
        {
            "name": "RCA 模板",
            "scenario": "销售额下降",
            "steps": ["确认口径", "拆贡献", "找证据"],
            "capabilities": ["database", "nlSql"],
        }
    )

    reloaded = OpsStore(tmp_path / "ops_state.json", tmp_path / "rag_docs").load_state()
    assert reloaded["evaluations"][0]["id"] == evaluation["id"]
    assert reloaded["templates"][0]["id"] == template["id"]
    assert reloaded["metrics"]["total_runs"] == 1
    assert reloaded["metrics"]["exactness"] == 0.91
