from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from backend.apps.ai_model.model_factory import create_llm_client
from backend.apps.chat.task.llm_pandas import LlmPandasAgent
from backend.apps.datasource.store import CsvDatasetStore


QUESTIONS = [
    "总销售额是多少？",
    "销售额最高前 5 个产品？",
    "各国家销售额排名？",
    "11 月销售额趋势？",
    "退货最多的产品？",
    "前 10 产品占整体销售额多少？",
]


@pytest.mark.skipif(
    os.getenv("RUN_REAL_LLM_SMOKE") != "1",
    reason="Set RUN_REAL_LLM_SMOKE=1 to call the configured real LLM provider.",
)
def test_real_llm_smoke_answers_at_least_four_of_six_questions(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(
        Path("samples/microsoft_anonymized_sales.csv"),
        original_filename="microsoft_anonymized_sales.csv",
    )
    agent = LlmPandasAgent(llm_client=create_llm_client())

    records = []
    success_count = 0
    for question in QUESTIONS:
        result = agent.ask(dataset, question)
        ok = bool(result["direct_answer"]) and result["execution_error"] is None
        success_count += int(ok)
        records.append(
            {
                "question": question,
                "ok": ok,
                "direct_answer": result["direct_answer"],
                "intent": result["intent"],
                "pandas_code": result["pandas_code"],
                "rows": result["rows"],
                "columns": result["columns"],
                "execution_error": result["execution_error"],
                "llm_raw": result["llm_raw"],
                "run_id": result["run_id"],
            }
        )

    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / f"real_llm_smoke_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.write_text(
        json.dumps(
            {
                "dataset_id": dataset.dataset_id,
                "success_count": success_count,
                "total": len(QUESTIONS),
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    assert success_count >= 4, f"Only {success_count}/6 real LLM questions succeeded. See {output_path}."
