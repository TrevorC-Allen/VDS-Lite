from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.apps.chat.task.llm_pandas import LlmPandasAgent
from backend.apps.chat.task.llm_pandas import build_repair_prompt
from backend.apps.chat.task.llm_pandas import build_prompt
from backend.apps.chat.task.llm_pandas import build_verifier_prompt
from backend.apps.chat.task.llm_pandas import build_uncomputable_diagnostic
from backend.apps.chat.task.llm_pandas import parse_llm_json
from backend.apps.chat.task.chart_renderer import build_rendered_chart
from backend.apps.chat.task.code_runner import UnsafeCodeError, run_pandas_code
from backend.apps.chat.api import AskPayload
from backend.apps.chat import api as chat_api
from backend.apps.chat.project_store import ProjectStore
from backend.apps.datasource.store import CsvDatasetStore


SAMPLE_CSV = """order_id,order_date,country,product,category,customer_id,quantity,unit_price,sales,is_return
O-1001,2025-10-01,UK,Notebook,Office,C-001,10,8.5,85.0,false
O-1002,2025-10-03,France,Pen,Office,C-002,30,1.5,45.0,false
O-1003,2025-11-02,UK,Monitor,Hardware,C-003,2,120.0,240.0,false
O-1004,2025-11-05,Germany,Keyboard,Hardware,C-004,5,35.0,175.0,false
O-1005,2025-11-08,UK,Notebook,Office,C-001,-2,8.5,-17.0,true
O-1006,2025-12-10,France,Monitor,Hardware,C-002,1,120.0,120.0,false
"""


class StubLlmClient:
    def __init__(self, response: str):
        self.response = response
        self.last_prompt = ""
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "语义校验器" in prompt:
            return '{"ok": true, "confidence": 0.9, "verdict": "语义匹配", "issues": [], "repair_instructions": ""}'
        self.last_prompt = prompt
        return self.response


class SequenceLlmClient:
    def __init__(self, responses: list[str], verifier_responses: list[str] | None = None):
        self.responses = responses
        self.verifier_responses = verifier_responses or []
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "语义校验器" in prompt:
            if self.verifier_responses:
                return self.verifier_responses.pop(0)
            return '{"ok": true, "confidence": 0.9, "verdict": "语义匹配", "issues": [], "repair_instructions": ""}'
        return self.responses.pop(0)


class RaisingLlmClient:
    def complete(self, prompt: str) -> str:
        raise ConnectionError("provider disconnected")


def write_csv(tmp_path: Path, content: str = SAMPLE_CSV) -> Path:
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(content, encoding="utf-8")
    return csv_path


def test_upload_csv_builds_profile_and_context(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")

    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")

    assert dataset.dataset_id
    assert dataset.profile["row_count"] == 6
    assert dataset.profile["columns"][0]["name"] == "order_id"
    assert "完整内容" in dataset.csv_text
    assert "O-1001,2025-10-01,UK,Notebook" in dataset.csv_text
    assert len(dataset.profile["preview_rows"]) == 6
    assert dataset.profile["columns_by_name"]["sales"]["dtype"].startswith("float")


def test_project_store_searches_projects_conversations_questions_and_answers(tmp_path: Path) -> None:
    project_store = ProjectStore(path=tmp_path / "chat_state.json")
    project = project_store.create_project("微软项目")
    conversation = project_store.create_conversation(
        project_id=project["project_id"],
        title="分销进度分析",
        dataset_id="dataset_1",
    )
    project_store.append_turn(
        conversation["conversation_id"],
        {
            "question": "孙源在2026年1月的分销目标金额是多少？",
            "direct_answer": "孙源在2026年1月的分销目标金额为305,368.00元。",
            "response_sections": {"analysis": ["按业代和月份筛选目标表。"]},
        },
    )

    project_results = project_store.search("微软")
    question_results = project_store.search("2026年1月")
    answer_results = project_store.search("305,368")

    assert any(result["result_type"] == "project" and result["project_id"] == project["project_id"] for result in project_results)
    assert any(result["conversation_id"] == conversation["conversation_id"] for result in question_results)
    assert any("305,368" in result["snippet"] for result in answer_results)


def test_project_store_pins_projects_first(tmp_path: Path) -> None:
    project_store = ProjectStore(path=tmp_path / "chat_state.json")
    first = project_store.create_project("普通项目")
    pinned = project_store.create_project("置顶项目")

    updated = project_store.update_project(pinned["project_id"], pinned=True)
    listed = project_store.list_projects()
    search_results = project_store.search("项目")

    assert updated["pinned"] is True
    assert updated["pinned_at"]
    assert listed[0]["project_id"] == pinned["project_id"]
    assert listed[1]["project_id"] == first["project_id"]
    assert search_results[0]["project_id"] == pinned["project_id"]
    assert search_results[0]["pinned"] is True


def test_unprojected_conversation_stays_outside_projects_until_moved(tmp_path: Path) -> None:
    project_store = ProjectStore(path=tmp_path / "chat_state.json")

    conversation = project_store.create_conversation(title="普通聊天", dataset_id="dataset_1")

    assert project_store.list_projects() == []
    assert conversation["project_id"] == ""
    assert project_store.list_conversations()[0]["conversation_id"] == conversation["conversation_id"]

    project = project_store.create_project("手动项目")
    moved = project_store.update_conversation(conversation["conversation_id"], project_id=project["project_id"])

    assert moved["project_id"] == project["project_id"]
    assert project_store.list_conversations() == []
    assert project_store.list_conversations(project["project_id"])[0]["conversation_id"] == conversation["conversation_id"]


def test_legacy_default_project_is_migrated_to_unprojected_history(tmp_path: Path) -> None:
    state_path = tmp_path / "chat_state.json"
    state_path.write_text(
        json.dumps(
            {
                "projects": {
                    "proj_default": {
                        "project_id": "proj_default",
                        "name": "默认项目",
                        "pinned": False,
                        "memories": [],
                    }
                },
                "conversations": {
                    "conv_legacy": {
                        "conversation_id": "conv_legacy",
                        "project_id": "proj_default",
                        "title": "旧普通聊天",
                        "dataset_id": "dataset_1",
                        "turns": [],
                        "created_at": "2026-06-09T00:00:00+00:00",
                        "updated_at": "2026-06-09T00:00:00+00:00",
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    migrated_store = ProjectStore(path=state_path)

    assert migrated_store.list_projects() == []
    migrated = migrated_store.get_conversation("conv_legacy")
    assert migrated is not None
    assert migrated["project_id"] == ""
    assert migrated_store.list_conversations()[0]["conversation_id"] == "conv_legacy"


def test_evidence_pack_adds_column_statistics_without_business_conclusions(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")

    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")
    evidence_pack = dataset.profile["evidence_pack"]
    sales_evidence = dataset.profile["columns_by_name"]["sales"]["evidence"]
    customer_evidence = dataset.profile["columns_by_name"]["customer_id"]["evidence"]

    assert evidence_pack["tables"][0]["table_name"] == "sales"
    assert evidence_pack["tables"][0]["row_count"] == 6
    assert "head_rows" in evidence_pack["tables"][0]
    assert "random_sample_rows" in evidence_pack["tables"][0]
    assert "tail_rows" in evidence_pack["tables"][0]
    assert sales_evidence["distinct_count"] == 6
    assert sales_evidence["uniqueness_ratio"] == 1.0
    assert sales_evidence["min"] == -17.0
    assert sales_evidence["max"] == 240.0
    assert "numeric" in sales_evidence["candidate_measure_evidence"]
    assert customer_evidence["repeated_value_count"] == 2
    serialized = str(evidence_pack).lower()
    assert "certain" not in serialized
    assert "definite" not in serialized


def test_upload_multiple_csvs_builds_table_manifest_and_multi_file_context(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    sales_path = write_csv(tmp_path)
    customers_path = tmp_path / "customers.csv"
    customers_path.write_text(
        "customer_id,segment,account_owner\n"
        "C-001,Strategic,Ada\n"
        "C-002,Growth,Ben\n"
        "C-003,Strategic,Ada\n",
        encoding="utf-8",
    )

    dataset = store.save_uploads(
        [sales_path, customers_path],
        original_filenames=["sales.csv", "customers.csv"],
    )

    assert dataset.profile["dataset_kind"] == "multi_csv"
    assert set(dataset.tables) == {"sales", "customers"}
    assert "sales.csv" in dataset.csv_text
    assert "customers.csv" in dataset.csv_text
    assert "引用方式: tables['sales']" in build_prompt(dataset=dataset, question="看一下")
    assert dataset.profiles_by_table["customers"]["row_count"] == 3
    assert dataset.profile["tables_by_name"]["sales"]["row_count"] == 6
    relations = dataset.profile["evidence_pack"]["relation_evidence"]
    customer_relation = next(
        relation for relation in relations
        if relation["left_table"] == "sales" and relation["right_table"] == "customers"
    )
    assert customer_relation["left_column"] == "customer_id"
    assert customer_relation["right_column"] == "customer_id"
    assert customer_relation["value_overlap_ratio"] > 0
    assert customer_relation["join_match_ratio"] > 0
    assert customer_relation["left_unique_ratio"] < customer_relation["right_unique_ratio"]
    assert any("candidate" in note for note in customer_relation["evidence_notes"])


def test_agent_sends_csv_context_to_llm_and_executes_generated_pandas(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")
    llm = StubLlmClient(
        """
        {
          "intent": "rank products by sales",
          "assumptions": ["sales is the trusted metric column"],
          "pandas_code": "def analyze(df):\\n    rows = df.groupby('product', as_index=False)['sales'].sum().sort_values('sales', ascending=False).head(3)\\n    return {'direct_answer': f\\\"Top product is {rows.iloc[0]['product']} with sales {rows.iloc[0]['sales']:.1f}\\\", 'rows': rows.to_dict(orient='records'), 'columns': list(rows.columns)}",
          "expected_output": "top products table"
        }
        """
    )
    agent = LlmPandasAgent(llm_client=llm)

    result = agent.ask(dataset, "销售额最高前 3 个产品？")

    assert "文件内容摘要与代表性样本" in llm.last_prompt
    assert "O-1005,2025-11-08,UK,Notebook" in llm.last_prompt
    assert result["intent"] == "rank products by sales"
    assert result["direct_answer"] == "Top product is Monitor with sales 360.0"
    assert result["rows"][0] == {"product": "Monitor", "sales": 360.0}
    assert result["execution_error"] is None
    assert result["run_id"]


def test_agent_returns_llm_data_brief_semantic_interpretation_and_sanity_checks(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")
    llm = StubLlmClient(
        json_payload(
            intent="total sales",
            pandas_code=(
                "def analyze(df):\n"
                "    total = float(df['sales'].sum())\n"
                "    return {'direct_answer': f'Total sales is {total:.1f}', 'rows': [{'metric': 'sales', 'value': total}], 'columns': ['metric', 'value']}"
            ),
            expected_output="metric value table",
            data_brief={"dataset_summary": "order detail style table"},
            semantic_interpretation={
                "operation_type": "aggregate",
                "target_table": None,
                "target_tables": [],
                "metric": "sales",
                "metric_formula_or_assumption": "sum sales",
                "aggregation": "sum",
                "dimension": None,
                "filters": [],
                "time_field": None,
                "time_grain": None,
                "sort": None,
                "top_n": None,
                "required_join_path": [],
                "expected_output_shape": "single_metric",
                "context_inheritance": {},
                "ambiguity_notes": [],
                "confidence": 0.86,
            },
        )
    )
    agent = LlmPandasAgent(llm_client=llm)

    result = agent.ask(dataset, "总销售额是多少？")

    assert "Evidence Pack" in llm.last_prompt
    assert "data_brief" in llm.last_prompt
    assert "semantic_interpretation" in llm.last_prompt
    assert result["data_brief"]["dataset_summary"] == "order detail style table"
    assert result["semantic_interpretation"]["operation_type"] == "aggregate"
    assert result["sanity_checks"]["ok"] is True
    assert result["execution_error"] is None


def test_agent_returns_llm_response_sections_and_rendered_chart(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")
    llm = StubLlmClient(
        json_payload(
            intent="rank products by sales with chart",
            pandas_code=(
                "def analyze(df):\n"
                "    rows = df.groupby('product', as_index=False)['sales'].sum().sort_values('sales', ascending=False).head(3)\n"
                "    top = rows.iloc[0]\n"
                "    return {\n"
                "        'direct_answer': f\"销售额最高的是 {top['product']}，销售额 {top['sales']:.1f}\",\n"
                "        'rows': rows.to_dict(orient='records'),\n"
                "        'columns': list(rows.columns),\n"
                "        'response_sections': {\n"
                "            'result_summary': f\"第一名是 {top['product']}，销售额 {top['sales']:.1f}\",\n"
                "            'analysis': ['按 product 汇总 sales 后降序排序。', f\"本次返回 {len(rows)} 个产品。\"],\n"
                "            'insights': ['Monitor 明显领先于其他产品。'],\n"
                "            'next_steps': ['继续看 Top 产品的月趋势。', '比较第一名和第二名差距。']\n"
                "        }\n"
                "    }"
            ),
            expected_output="top products table with chart",
            chart_spec={
                "chart_type": "horizontal_bar",
                "title": "产品销售额 Top 3",
                "x": "product",
                "y": "sales",
                "reason": "TopN ranking is best compared with a horizontal bar chart.",
                "confidence": 0.9,
            },
        )
    )
    agent = LlmPandasAgent(llm_client=llm)

    result = agent.ask(dataset, "销售额最高前 3 个产品？")

    assert "response_sections" in llm.last_prompt
    assert "chart_spec" in llm.last_prompt
    assert result["response_sections"]["analysis"][0] == "按 product 汇总 sales 后降序排序。"
    assert result["response_sections"]["next_steps"][0] == "继续看 Top 产品的月趋势。"
    assert result["chart"]["chart_type"] == "horizontal_bar"
    assert result["chart"]["x"] == "product"
    assert result["chart"]["y"] == "sales"
    assert result["chart"]["image_data_uri"].startswith("data:image/svg+xml;base64,")
    assert result["execution_error"] is None


def test_agent_includes_conversation_history_in_prompt(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")
    llm = StubLlmClient(
        json_payload(
            intent="follow up on previous customer",
            pandas_code=(
                "def analyze(df):\n"
                "    rows = df[df['customer_id'] == 'C-001'].groupby('product', as_index=False)['sales'].sum()\n"
                "    return {'direct_answer': 'follow-up ok', 'rows': rows.to_dict('records'), 'columns': list(rows.columns)}"
            ),
            expected_output="follow-up table",
        )
    )
    agent = LlmPandasAgent(llm_client=llm)

    result = agent.ask(
        dataset,
        "再看这个客户买了什么",
        conversation_history=[
            {
                "question": "看 C-001 的消费总额",
                "direct_answer": "客户 C-001 消费总额为 68.0",
                "intent": "customer total sales",
                "rows": [{"customer_id": "C-001", "sales": 68.0}],
                "columns": ["customer_id", "sales"],
                "pandas_code": "def analyze(df): pass",
            }
        ],
    )

    assert "对话历史" in llm.last_prompt
    assert "看 C-001 的消费总额" in llm.last_prompt
    assert "客户 C-001 消费总额为 68.0" in llm.last_prompt
    assert result["direct_answer"] == "follow-up ok"


def test_agent_retries_when_llm_verifier_rejects_missing_metric_semantics(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")
    llm = SequenceLlmClient(
        [
            json_payload(
                intent="bad missing field",
                pandas_code="def analyze(df):\n    return {'direct_answer': 'bad', 'rows': [{'value': 1}], 'columns': ['value']}",
                expected_output="bad",
                semantic_interpretation={
                    "operation_type": "aggregate",
                    "target_table": "sales",
                    "target_tables": ["sales"],
                    "metric": "missing_sales",
                    "metric_formula_or_assumption": "sum missing_sales",
                    "aggregation": "sum",
                    "dimension": None,
                    "filters": [],
                    "time_field": None,
                    "time_grain": None,
                    "sort": None,
                    "top_n": None,
                    "required_join_path": [],
                    "expected_output_shape": "single_metric",
                    "context_inheritance": {},
                    "ambiguity_notes": [],
                    "confidence": 0.5,
                },
            ),
            json_payload(
                intent="safe total sales",
                pandas_code=(
                    "def analyze(df):\n"
                    "    total = float(df['sales'].sum())\n"
                    "    return {'direct_answer': f'Total sales is {total:.1f}', 'rows': [{'metric': 'sales', 'value': total}], 'columns': ['metric', 'value']}"
                ),
                expected_output="metric value table",
                semantic_interpretation={
                    "operation_type": "aggregate",
                    "target_table": "sales",
                    "target_tables": ["sales"],
                    "metric": "sales",
                    "metric_formula_or_assumption": "sum sales",
                    "aggregation": "sum",
                    "dimension": None,
                    "filters": [],
                    "time_field": None,
                    "time_grain": None,
                    "sort": None,
                    "top_n": None,
                    "required_join_path": [],
                    "expected_output_shape": "single_metric",
                    "context_inheritance": {},
                    "ambiguity_notes": [],
                    "confidence": 0.9,
                },
            ),
        ],
        verifier_responses=[
            '{"ok": false, "confidence": 0.9, "verdict": "指标语义错误", "issues": ["metric missing_sales 不符合用户要的总销售额"], "repair_instructions": "改为使用 sales 字段求和。"}',
            '{"ok": true, "confidence": 0.9, "verdict": "语义匹配", "issues": [], "repair_instructions": ""}',
        ],
    )
    agent = LlmPandasAgent(llm_client=llm)

    result = agent.ask(dataset, "总销售额是多少？")

    assert result["execution_error"] is None
    assert result["direct_answer"] == "Total sales is 648.0"
    assert result["attempts"][0]["ok"] is False
    assert "missing_sales" in result["attempts"][0]["error"]
    assert "语义校验器" in llm.prompts[1]
    assert "LLM verifier" in llm.prompts[2]


def test_agent_retries_when_llm_verifier_rejects_trend_without_time_field(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")
    llm = SequenceLlmClient(
        [
            json_payload(
                intent="bad trend",
                pandas_code="def analyze(df):\n    return {'direct_answer': 'bad', 'rows': [{'value': 1}], 'columns': ['value']}",
                expected_output="trend table",
                semantic_interpretation={
                    "operation_type": "trend",
                    "target_table": "sales",
                    "target_tables": ["sales"],
                    "metric": "sales",
                    "metric_formula_or_assumption": "sum sales",
                    "aggregation": "sum",
                    "dimension": None,
                    "filters": [],
                    "time_field": None,
                    "time_grain": "month",
                    "sort": None,
                    "top_n": None,
                    "required_join_path": [],
                    "expected_output_shape": "time_series",
                    "context_inheritance": {},
                    "ambiguity_notes": [],
                    "confidence": 0.5,
                },
            ),
            json_payload(
                intent="safe trend",
                pandas_code=(
                    "def analyze(df):\n"
                    "    data = df.copy()\n"
                    "    data['month'] = pd.to_datetime(data['order_date']).dt.to_period('M').astype(str)\n"
                    "    rows = data.groupby('month', as_index=False)['sales'].sum()\n"
                    "    return {'direct_answer': 'Monthly trend calculated', 'rows': rows.to_dict('records'), 'columns': list(rows.columns)}"
                ),
                expected_output="trend table",
                semantic_interpretation={
                    "operation_type": "trend",
                    "target_table": "sales",
                    "target_tables": ["sales"],
                    "metric": "sales",
                    "metric_formula_or_assumption": "sum sales",
                    "aggregation": "sum",
                    "dimension": None,
                    "filters": [],
                    "time_field": "order_date",
                    "time_grain": "month",
                    "sort": "month ascending",
                    "top_n": None,
                    "required_join_path": [],
                    "expected_output_shape": "time_series",
                    "context_inheritance": {},
                    "ambiguity_notes": [],
                    "confidence": 0.9,
                },
            ),
        ],
        verifier_responses=[
            '{"ok": false, "confidence": 0.9, "verdict": "趋势语义错误", "issues": ["用户要月趋势，但结果没有使用 order_date 生成月份"], "repair_instructions": "使用 order_date 按月聚合 sales。"}',
            '{"ok": true, "confidence": 0.9, "verdict": "语义匹配", "issues": [], "repair_instructions": ""}',
        ],
    )
    agent = LlmPandasAgent(llm_client=llm)

    result = agent.ask(dataset, "看月销售趋势")

    assert result["execution_error"] is None
    assert result["direct_answer"] == "Monthly trend calculated"
    assert result["attempts"][0]["ok"] is False
    assert "order_date" in result["attempts"][0]["error"]


def test_sanity_check_allows_derived_metric_alias_when_formula_uses_existing_fields(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")
    llm = StubLlmClient(
        json_payload(
            intent="derived total sales",
            pandas_code=(
                "def analyze(df):\n"
                "    total = float((df['quantity'] * df['unit_price']).sum())\n"
                "    return {'direct_answer': f'Total sales is {total:.1f}', 'rows': [{'metric': 'total_sales', 'value': total}], 'columns': ['metric', 'value']}"
            ),
            expected_output="metric value table",
            semantic_interpretation={
                "operation_type": "aggregate",
                "target_table": "sales",
                "target_tables": ["sales"],
                "metric": "total_sales",
                "metric_formula_or_assumption": "quantity * unit_price",
                "aggregation": "sum",
                "dimension": None,
                "filters": [],
                "time_field": None,
                "time_grain": None,
                "sort": None,
                "top_n": None,
                "required_join_path": [],
                "expected_output_shape": "single_metric",
                "context_inheritance": {},
                "ambiguity_notes": [],
                "confidence": 0.9,
            },
        )
    )
    agent = LlmPandasAgent(llm_client=llm)

    result = agent.ask(dataset, "总销售额是多少？")

    assert result["execution_error"] is None
    assert result["semantic_interpretation"]["metric"] == "total_sales"
    assert result["sanity_checks"]["ok"] is True


def test_sanity_check_allows_time_field_dimension_with_month_annotation(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")
    llm = StubLlmClient(
        json_payload(
            intent="monthly sales gap",
            pandas_code=(
                "def analyze(df):\n"
                "    data = df.copy()\n"
                "    data['Sales'] = data['quantity'] * data['unit_price']\n"
                "    data['Month'] = pd.to_datetime(data['order_date']).dt.to_period('M').astype(str)\n"
                "    rows = data.groupby('Month', as_index=False)['Sales'].sum().sort_values('Month')\n"
                "    rows['Difference'] = rows['Sales'].diff().fillna(0)\n"
                "    return {'direct_answer': 'monthly gap ok', 'rows': rows.to_dict('records'), 'columns': list(rows.columns)}"
            ),
            expected_output="monthly sales and difference table",
            semantic_interpretation={
                "operation_type": "time_series_gap_analysis",
                "target_table": "sales",
                "target_tables": ["sales"],
                "metric": "Sales",
                "metric_formula_or_assumption": "quantity * unit_price",
                "aggregation": "sum",
                "dimension": "order_date（按月）",
                "filters": [],
                "time_field": "order_date",
                "time_grain": "month",
                "sort": "Month ascending",
                "top_n": None,
                "required_join_path": [],
                "expected_output_shape": "monthly rows with month sales and difference",
                "context_inheritance": {},
                "ambiguity_notes": [],
                "confidence": 0.9,
            },
        )
    )
    agent = LlmPandasAgent(llm_client=llm)

    result = agent.ask(dataset, "按月看差额")

    assert result["execution_error"] is None
    assert result["direct_answer"] == "monthly gap ok"
    assert result["columns"] == ["Month", "Sales", "Difference"]
    assert result["sanity_checks"]["ok"] is True


def test_agent_surfaces_llm_provider_errors_without_http_500_shape(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")
    agent = LlmPandasAgent(llm_client=RaisingLlmClient())

    result = agent.ask(dataset, "总销售额是多少？")

    assert result["direct_answer"] == ""
    assert result["rows"] == []
    assert "provider disconnected" in result["execution_error"]
    assert result["attempts"][0]["ok"] is False


def test_agent_sends_multi_file_context_and_executes_llm_chosen_join(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    sales_path = write_csv(tmp_path)
    customers_path = tmp_path / "customers.csv"
    customers_path.write_text(
        "customer_id,segment,account_owner\n"
        "C-001,Strategic,Ada\n"
        "C-002,Growth,Ben\n"
        "C-003,Strategic,Ada\n"
        "C-004,Growth,Ben\n",
        encoding="utf-8",
    )
    dataset = store.save_uploads([sales_path, customers_path], ["sales.csv", "customers.csv"])
    llm = StubLlmClient(
        json_payload(
            intent="join sales to customers and rank segments",
            pandas_code=(
                "def analyze(tables):\n"
                "    sales = tables['sales']\n"
                "    customers = tables['customers']\n"
                "    joined = sales.merge(customers, on='customer_id', how='left')\n"
                "    rows = joined.groupby('segment', as_index=False)['sales'].sum().sort_values('sales', ascending=False)\n"
                "    return {'direct_answer': f\"Top segment is {rows.iloc[0]['segment']} with sales {rows.iloc[0]['sales']:.1f}\", 'rows': rows.to_dict(orient='records'), 'columns': list(rows.columns)}"
            ),
            expected_output="segment sales table",
        )
    )
    agent = LlmPandasAgent(llm_client=llm)

    result = agent.ask(dataset, "按客户分层看销售额，哪个 segment 最高？")

    assert "多文件数据集" in llm.last_prompt
    assert "文件名: sales.csv" in llm.last_prompt
    assert "文件名: customers.csv" in llm.last_prompt
    assert "tables['sales']" in llm.last_prompt
    assert result["direct_answer"] == "Top segment is Growth with sales 340.0"
    assert result["rows"][0] == {"segment": "Growth", "sales": 340.0}
    assert result["execution_error"] is None


def test_excel_workbook_sheets_become_tables_for_llm_join(tmp_path: Path) -> None:
    pd = pytest.importorskip("pandas")
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    workbook_path = tmp_path / "workbook.xlsx"
    with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {"order_id": "O-1", "customer_id": "C-001", "sales": 100.0},
                {"order_id": "O-2", "customer_id": "C-002", "sales": 250.0},
            ]
        ).to_excel(writer, sheet_name="Orders", index=False)
        pd.DataFrame(
            [
                {"customer_id": "C-001", "segment": "Strategic"},
                {"customer_id": "C-002", "segment": "Growth"},
            ]
        ).to_excel(writer, sheet_name="Customers", index=False)

    dataset = store.save_upload(workbook_path, original_filename="workbook.xlsx")
    llm = StubLlmClient(
        json_payload(
            intent="join excel sheets by customer_id",
            pandas_code=(
                "def analyze(tables):\n"
                "    joined = tables['orders'].merge(tables['customers'], on='customer_id', how='left')\n"
                "    rows = joined.groupby('segment', as_index=False)['sales'].sum().sort_values('sales', ascending=False)\n"
                "    return {'direct_answer': f\"Top segment is {rows.iloc[0]['segment']}\", 'rows': rows.to_dict(orient='records'), 'columns': list(rows.columns)}"
            ),
            expected_output="segment sales table",
        )
    )
    agent = LlmPandasAgent(llm_client=llm)

    result = agent.ask(dataset, "Excel 里按客户分层看销售额")

    assert dataset.profile["dataset_kind"] == "excel_workbook"
    assert set(dataset.tables) == {"orders", "customers"}
    assert "工作簿: workbook.xlsx" in llm.last_prompt
    assert "sheet: Orders" in llm.last_prompt
    assert "tables['orders']" in llm.last_prompt
    assert result["direct_answer"] == "Top segment is Growth"
    assert result["rows"][0] == {"segment": "Growth", "sales": 250.0}
    assert result["execution_error"] is None


def test_excel_datetime_values_are_json_serializable(tmp_path: Path) -> None:
    pd = pytest.importorskip("pandas")
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    workbook_path = tmp_path / "dated_workbook.xlsx"
    with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {"invoice": "I-1", "invoice_date": pd.Timestamp("2025-11-01 10:30:00"), "sales": 12.5},
                {"invoice": "I-2", "invoice_date": pd.Timestamp("2025-11-02 08:00:00"), "sales": 18.0},
            ]
        ).to_excel(writer, sheet_name="Orders", index=False)

    dataset = store.save_upload(workbook_path, original_filename="dated_workbook.xlsx")

    assert dataset.profile["preview_rows"][0]["invoice_date"] == "2025-11-01T10:30:00"
    assert dataset.profile["columns_by_name"]["invoice_date"]["sample_values"][0] == "2025-11-01T10:30:00"
    assert "2025-11-01" in dataset.csv_text


def test_loaded_excel_datetime_columns_remain_datetime_for_resample(tmp_path: Path) -> None:
    pd = pytest.importorskip("pandas")
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    workbook_path = tmp_path / "dated_workbook.xlsx"
    with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {"customer_id": 17850.0, "invoice_date": pd.Timestamp("2025-11-01"), "sales": 10.0},
                {"customer_id": 17850.0, "invoice_date": pd.Timestamp("2025-12-01"), "sales": 15.0},
            ]
        ).to_excel(writer, sheet_name="Orders", index=False)

    dataset = store.save_upload(workbook_path, original_filename="dated_workbook.xlsx")
    reloaded = store.load(dataset.dataset_id)
    result = run_pandas_code(
        "def analyze(df):\n"
        "    customer = df[df['customer_id'] == 17850.0].copy()\n"
        "    monthly = customer.set_index('invoice_date')['sales'].resample('M').sum().reset_index()\n"
        "    monthly['change_rate'] = monthly['sales'].pct_change()\n"
        "    return {'direct_answer': 'ok', 'rows': monthly.to_dict('records'), 'columns': monthly.columns}",
        df=reloaded.dataframe,
    )

    assert str(reloaded.dataframe["invoice_date"].dtype).startswith("datetime64")
    assert result["direct_answer"] == "ok"
    assert result["columns"] == ["invoice_date", "sales", "change_rate"]
    assert result["rows"][1]["change_rate"] == 0.5


def test_prompt_does_not_offer_hardcoded_capability_menu(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")

    prompt = build_prompt(dataset=dataset, question="自己判断应该怎么分析这张表")

    assert "文件内容摘要与代表性样本" in prompt
    assert "pandas_code" in prompt
    assert "你必须自己决定分析意图、分析步骤和 Pandas 代码" in prompt
    assert "不要从后端预设菜单中选择" in prompt
    assert "允许按需 import 常见分析库" in prompt
    assert "禁止使用 open、eval、exec、__import__、os、sys、subprocess、socket" in prompt
    assert "如果违反这些边界，后端会拒绝执行" in prompt
    assert "expected_output 必须是短字符串" in prompt
    assert "response_sections" in prompt
    assert "chart_spec" in prompt
    assert "TopN/排名通常用 bar 或 horizontal_bar" in prompt
    assert "图表数据必须来自 Pandas 执行后的 rows" in prompt
    assert "rows 必须是 list[dict]" in prompt
    assert "不要把 rows 写成 shape[0]" in prompt
    assert "能力组" not in prompt
    assert "可选操作" not in prompt


def test_prompt_requires_exact_enum_and_metric_comment_matching(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")

    prompt = build_prompt(dataset=dataset, question="2025年2月天然水的历史分销金额是多少？")
    repair_prompt = build_repair_prompt(
        original_prompt=prompt,
        previous_raw="{}",
        previous_code="df[df['ctg_name'].str.contains('天然水')]['sign_amt'].sum()",
        error="LLM verifier rejected result: metric/filter semantics mismatch",
    )

    assert "文本枚举筛选必须先找精确值" in prompt
    assert "优先使用 == 或 isin 做精确匹配" in prompt
    assert "不要用 contains/regex/startswith 把“苏打天然水”" in prompt
    assert "指标字段必须尊重字段注释的精确口径" in prompt
    assert "用户只说“分销金额”时优先选择注释精确等于“分销金额”的字段" in prompt
    assert "按月筛选日期必须使用半开区间 [月初, 下月初)" in prompt
    assert "必须改为 == 或 isin 精确匹配" in repair_prompt
    assert "必须重新按字段注释选择精确匹配的普通金额字段" in repair_prompt
    assert "必须改为 [月初, 下月初) 或 dt.to_period('M')" in repair_prompt


def test_prompt_defines_mismatch_ratio_and_quadrant_defaults(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")

    prompt = build_prompt(dataset=dataset, question="谁是高销售低陈列？确认金额/分销金额比例最高的是谁？")
    repair_prompt = build_repair_prompt(
        original_prompt=prompt,
        previous_raw="{}",
        previous_code="",
        error="LLM verifier rejected result: 未发现高销售低陈列",
    )

    assert "不能只用中位数硬分后回答“未发现”" in prompt
    assert "返回最接近的 Top 候选" in prompt
    assert "direct_answer 不能只说“未发现”" in prompt
    assert "必须分别点名“高销售低陈列候选”和“高陈列低销售候选”" in prompt
    assert "rows 必须包含 category/候选类型 或 销售陈列效率/陈列销售比例" in prompt
    assert "不要擅自只取最新月" in prompt
    assert "必须检查并改用非零陈列执行指标" in prompt
    assert "比例越高代表陈列确认金额相对分销金额越高" in prompt
    assert "比例为 0 或很低通常表示陈列投入低" in prompt
    assert "默认按 确认金额/历史分销金额 比例从高到低排序" in prompt
    assert "不要为了减少数据量默认选择最新月" in prompt
    assert "不能选择会让关键指标全 0" in prompt
    assert "不得继续回答“未发现”" in repair_prompt
    assert "direct_answer 必须分别点名两类候选" in repair_prompt
    assert "不得用过滤后全 0 的陈列指标继续分类" in repair_prompt
    assert "不得把 0 或低比例直接说成投入产出风险最高" in repair_prompt
    assert "不得继续使用升序排序把低风险对象排在最前" in repair_prompt
    assert "必须改为全量可用期间或共同期间聚合" in repair_prompt


def test_prompt_defines_directional_change_and_requested_grain_rules(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")

    prompt = build_prompt(dataset=dataset, question="本周与上周相比，PSD减少最多的Top10门店？")
    repair_prompt = build_repair_prompt(
        original_prompt=prompt,
        previous_raw="{}",
        previous_code="",
        error="LLM verifier rejected result: 用户要求门店Top10，但代码按城市聚合；减少最多结果混入正值",
    )

    assert "PSD/UPT/AT/HW/RSI/AWT/ASP 等非可加总指标" in prompt
    assert "不能把缺失周期填 0 当成真实下降或上升" in prompt
    assert "减少最多/下降最多”时必须优先筛选 change < 0" in prompt
    assert "结果中不能混入正值并称为下降/减少" in prompt
    assert "不能擅自降级成城市、区域或学区聚合" in prompt
    assert "不要用销售额、城市汇总或其他未授权口径硬替代" in prompt
    assert "应返回“无法安全计算”的字段级诊断" in prompt
    assert "为什么不能安全计算" in prompt
    assert "优先使用这些业务周期字段" in prompt
    assert "不得把反方向值混入增长/下降排名" in repair_prompt
    assert "不得为了凑 TopN 把缺失事实填 0 后当成下降/减少" in repair_prompt
    assert "不得继续用粗维度冒充" in repair_prompt
    assert "必须返回字段级诊断 rows" in repair_prompt
    assert "这不是要硬算答案，而是要告诉用户为什么无法计算" in repair_prompt


def test_verifier_accepts_uncomputable_field_diagnostics(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")

    verifier_prompt = build_verifier_prompt(
        dataset=dataset,
        question="本周与上周相比，PSD增加最多的Top10门店？",
        conversation_history=[],
        llm_payload={
            "semantic_interpretation": {"metric": "PSD_row", "dimension": "门店名称"},
            "assumptions": ["PSD_row 和门店名称全为空，无法安全计算。"],
        },
        execution={
            "direct_answer": "由于 PSD_row 和门店名称字段全为空，无法计算各门店 PSD 变化。",
            "columns": ["requested_metric", "requested_dimension", "blocking_field", "evidence", "status", "next_step"],
            "rows": [
                {
                    "requested_metric": "PSD_row",
                    "requested_dimension": "门店名称",
                    "blocking_field": "PSD_row",
                    "evidence": "null_rate=100%",
                    "status": "全为空",
                    "next_step": "补充 PSD 或门店字段",
                }
            ],
        },
        pandas_code="def analyze(df): pass",
    )

    assert "返回“无法安全计算”的字段级诊断是正确行为，应 ok=true" in verifier_prompt
    assert "不要要求模型用销售额、城市、区域等未授权口径近似" in verifier_prompt
    assert "用更粗维度或其他指标冒充用户要求的门店/PSD/UPT/AT" in verifier_prompt


def test_uncomputable_verifier_reject_becomes_user_diagnostic() -> None:
    diagnostic = build_uncomputable_diagnostic(
        "本周与上周相比，PSD增加最多的Top10门店？",
        'LLM verifier rejected result: ["用户明确要求PSD和门店粒度，但PSD_row和门店名称字段全为空，无法安全计算。"]',
    )

    assert diagnostic is not None
    assert "无法安全计算" in diagnostic["direct_answer"]
    assert diagnostic["columns"] == [
        "requested_metric",
        "requested_dimension",
        "blocking_field",
        "evidence",
        "status",
        "next_step",
    ]
    assert any(row["blocking_field"] == "PSD_row" for row in diagnostic["rows"])
    assert any(row["blocking_field"] == "门店名称" for row in diagnostic["rows"])


def test_prompt_promotes_uploaded_business_guidelines(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    data_path = write_csv(tmp_path)
    guideline_path = tmp_path / "sheet1.csv"
    guideline_path.write_text(
        "主题,说明\n"
        "订单明细表,【订单明细表】历史订单明细表适用场景；全局筛选（考核口径）：商品类型='成品' AND 行销类目 IN ('水','饮料')。\n"
        "分销目标表,【分销目标表】核心提取规则：根据岗位判断主任目标或业代目标。\n",
        encoding="utf-8",
    )
    dataset = store.save_uploads([data_path, guideline_path], ["sales.csv", "sheet1.csv"])

    prompt = build_prompt(dataset=dataset, question="2026年5月分销目标达成率是多少？")
    verifier_prompt = build_verifier_prompt(
        dataset=dataset,
        question="2026年5月分销目标达成率是多少？",
        conversation_history=[],
        llm_payload={"semantic_interpretation": {"operation_type": "aggregation"}},
        execution={"direct_answer": "ok", "rows": [{"metric": "x", "value": 1}], "columns": ["metric", "value"]},
        pandas_code="def analyze(tables):\n    return {'direct_answer': 'ok', 'rows': [{'metric': 'x', 'value': 1}], 'columns': ['metric', 'value']}",
    )

    assert "业务口径 / guideline（高优先级，优先于默认规则）" in prompt
    assert prompt.find("业务口径 / guideline") < prompt.find("字段 profile：")
    assert "业务数据表包括" in prompt
    assert "口径/规则/说明表包括" in prompt
    assert "普通数据分析只能聚合、筛选、join 业务数据表" in prompt
    assert '"business_data_tables"' in prompt
    assert '"guideline_tables"' in prompt
    assert '"table_role": "business_data"' in prompt
    assert '"table_role": "guideline"' in prompt
    assert "guideline tables are rule/metadata context and must not be treated as fact data" in prompt
    assert "全局筛选（考核口径）" in prompt
    assert "核心提取规则" in prompt
    assert "用户问题中的“口径提示/答案格式/计算公式”和上传文件中的业务口径" in prompt
    assert "业务口径 / guideline（高优先级，优先于默认规则）" in verifier_prompt
    assert "全局筛选（考核口径）" in verifier_prompt
    assert "guideline 优先于默认校验规则" in verifier_prompt


def test_markdown_upload_becomes_guideline_context(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    data_path = write_csv(tmp_path)
    guideline_path = tmp_path / "规则说明.md"
    guideline_path.write_text(
        "# 分销口径\n"
        "业务口径：所有销售额分析必须排除退货订单。\n"
        "答案格式：先给直接答案，再列证据字段。\n",
        encoding="utf-8",
    )

    dataset = store.save_uploads([data_path, guideline_path], ["sales.csv", "规则说明.md"])
    prompt = build_prompt(dataset=dataset, question="销售额是多少？")

    assert dataset.profile["dataset_kind"] == "multi_file"
    assert any(entry["original_filename"] == "规则说明.md" for entry in dataset.profile["tables"])
    assert "doc_" in next(name for name in dataset.tables if "规则说明" in name)
    assert "业务口径：所有销售额分析必须排除退货订单" in prompt
    assert '"table_role": "guideline"' in prompt
    assert "口径/规则/说明表包括" in prompt


def test_overview_question_uses_dedicated_table_relationship_prompt(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    sales_path = write_csv(tmp_path)
    customers_path = tmp_path / "customers.csv"
    customers_path.write_text(
        "customer_id,segment,account_owner\n"
        "C-001,Strategic,Ada\n"
        "C-002,Growth,Ben\n"
        "C-003,Strategic,Ada\n",
        encoding="utf-8",
    )
    guideline_path = tmp_path / "数据表说明.csv"
    guideline_path.write_text(
        "表名,说明,粒度,关联键\n"
        "sales,订单明细表,订单+商品,customer_id/product/order_date\n"
        "customers,客户维表,客户,customer_id\n",
        encoding="utf-8",
    )
    dataset = store.save_uploads(
        [sales_path, customers_path, guideline_path],
        ["sales.csv", "customers.csv", "数据表说明.csv"],
    )
    llm = StubLlmClient(
        json_payload(
            intent="dataset overview",
            pandas_code=(
                "def analyze(tables):\n"
                "    rows = [\n"
                "        {'表': 'sales', '角色': '业务数据表', '含义': '订单明细表', '粒度': '订单+商品', '主要用途': '销售额、退货、产品分析', '关键关联键': 'customer_id'},\n"
                "        {'表': 'customers', '角色': '业务数据表', '含义': '客户维表', '粒度': '客户', '主要用途': '客户分群和负责人分析', '关键关联键': 'customer_id'},\n"
                "    ]\n"
                "    return {'direct_answer': '这是订单到客户维表的多表数据，可通过 customer_id 串联。', 'rows': rows, 'columns': list(rows[0].keys())}"
            ),
            expected_output="表级概览、关联键和业务链路",
            chart_spec={"chart_type": "none", "title": "", "x": "", "y": "", "reason": "概览解释不需要图表", "confidence": 0.0},
        )
    )
    agent = LlmPandasAgent(llm_client=llm)

    result = agent.ask(dataset, "给我研究一下这个数据，各个表之间的联系以及各个表讲的什么")

    assert result["execution_error"] is None
    assert "数据概览专用" in llm.last_prompt
    assert "不要默认输出业代TopN/排名" in llm.last_prompt
    assert "每张表讲什么" in llm.last_prompt
    assert "表之间怎么连" in llm.last_prompt
    assert "核心关联键" in llm.last_prompt
    assert "业务链路" in llm.last_prompt
    assert "rows 应返回表级清单" in llm.last_prompt
    assert "业务数据表和 guideline/说明表必须分开说明" in llm.last_prompt
    assert result["columns"] == ["表", "角色", "含义", "粒度", "主要用途", "关键关联键"]


def test_prompt_requires_business_date_progress_and_growth_contribution_guards(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")

    prompt = build_prompt(
        dataset=dataset,
        question="以2026-05-19为业务日期，谁当天分销进度最落后？如果按平均每单金额估算需要补多少单？",
    )
    repair_prompt = build_repair_prompt(
        original_prompt=prompt,
        previous_raw="{}",
        previous_code="math.ceil(float('nan'))",
        error="ValueError: cannot convert float NaN to integer",
    )

    assert "必须优先按精确业务日期过滤事实数据" in prompt
    assert "时间进度表应优先用 date_id == YYYYMMDD" in prompt
    assert "禁止直接用 df['sign_time'] == 'YYYY-MM-DD'" in prompt
    assert ".dt.date == 目标日期" in prompt
    assert "默认只在当天有已签收事实记录且可计算分母的对象中排名" in prompt
    assert "不要让目标表中当天无订单、实际为 0、平均单额为 NaN/0 的对象" in prompt
    assert "用户说“每位业代/各业代”只表示需要逐业代计算" in prompt
    assert "只有用户或 guideline 明确说“包括无订单/0销售/无分销/目标表所有人”" in prompt
    assert "必须按订单号先汇总订单金额，再按订单求平均" in prompt
    assert "不得抛 ValueError" in prompt
    assert "signed contribution = 本期指标 - 上期指标" in prompt
    assert "Pandas 会生成 _x/_y 后缀" in prompt
    assert "必须改为优先按 date_id/date_fmt 精确业务日期取数" in repair_prompt
    assert "仅对有当天事实且分母可计算的对象排名" in repair_prompt
    assert "用户说“每位业代/各业代”不等于要求包含目标表中当天无事实记录的人员" in repair_prompt
    assert "检查 pd.notna、np.isfinite 和分母 > 0" in repair_prompt
    assert "不要按两期合计金额或本期单期金额排序" in repair_prompt
    assert "是否因为左右表同名列被 Pandas 改成 _x/_y 后缀" in repair_prompt
    assert "df['sign_time'] == 'YYYY-MM-DD'" in repair_prompt


def test_verifier_prompt_rejects_no_daily_fact_progress_winner(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")

    prompt = build_verifier_prompt(
        dataset=dataset,
        question="以2026-05-19为业务日期，哪位业代当天分销进度最落后？",
        conversation_history=[],
        llm_payload={"semantic_interpretation": {"operation_type": "top_n_ranking"}},
        execution={
            "direct_answer": "分销进度最落后的是曹献慷，当天无已签收订单，进度为0%。",
            "rows": [{"业代": "曹献慷", "当日分销金额": 0, "分销进度": 0}],
            "columns": ["业代", "当日分销金额", "分销进度"],
        },
        pandas_code=(
            "df_today = df_today[df_today['sign_time'] == '2026-05-19']\n"
            "df_target.merge(df_today, on='emp_code', how='left').fillna(0)"
        ),
    )

    assert "结果第一名不能是被目标表 left join 后填 0" in prompt
    assert "当天无已签收事实或平均单额不可计算的对象" in prompt
    assert "应 ok=false" in prompt
    assert "只在有当天事实且分母可计算的对象中排名" in prompt
    assert "用户说“每位业代/各业代”只表示逐业代计算" in prompt
    assert "df['sign_time'] == 'YYYY-MM-DD'" in prompt


def test_chart_renderer_uses_llm_spec_with_execution_rows() -> None:
    chart = build_rendered_chart(
        {
            "chart_type": "line",
            "title": "月销售额趋势",
            "x": "month",
            "y": "sales",
            "reason": "The user asked for a trend.",
        },
        {
            "direct_answer": "ok",
            "columns": ["month", "sales"],
            "rows": [
                {"month": "2025-10", "sales": 130.0},
                {"month": "2025-11", "sales": 398.0},
                {"month": "2025-12", "sales": 120.0},
            ],
        },
    )

    assert chart["chart_type"] == "line"
    assert chart["x"] == "month"
    assert chart["y"] == "sales"
    assert chart["image_data_uri"].startswith("data:image/svg+xml;base64,")


def test_chart_renderer_tolerates_reversed_horizontal_bar_axes() -> None:
    chart = build_rendered_chart(
        {
            "chart_type": "horizontal_bar",
            "title": "产品销售额",
            "x": "total_sales",
            "y": "product",
            "reason": "LLM chose a horizontal bar chart.",
        },
        {
            "direct_answer": "ok",
            "columns": ["product", "total_sales"],
            "rows": [
                {"product": "Monitor", "total_sales": 600.0},
                {"product": "Mouse", "total_sales": 216.0},
            ],
        },
    )

    assert chart["x"] == "product"
    assert chart["y"] == "total_sales"
    assert chart["image_data_uri"].startswith("data:image/svg+xml;base64,")


def test_rejects_unsafe_generated_code() -> None:
    with pytest.raises(UnsafeCodeError, match="Import is not allowed"):
        run_pandas_code(
            "import os\n"
            "def analyze(df):\n"
            "    return {'direct_answer': 'bad', 'rows': [], 'columns': []}",
            df=None,
        )


def test_runner_allows_safe_analysis_imports(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")

    result = run_pandas_code(
        "import numpy as np\n"
        "def analyze(df):\n"
        "    value = float(np.round(df['sales'].sum(), 2))\n"
        "    return {'direct_answer': f'total {value}', 'rows': [{'metric': 'sales', 'value': value}], 'columns': ['metric', 'value']}",
        df=dataset.dataframe,
    )

    assert result["rows"] == [{"metric": "sales", "value": 648.0}]


def test_run_pandas_code_allows_safe_isinstance_builtin(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")

    result = run_pandas_code(
        "def analyze(df):\n"
        "    value = 1\n"
        "    ok = isinstance(value, int)\n"
        "    return {'direct_answer': str(ok), 'rows': [{'ok': ok}], 'columns': ['ok']}",
        df=dataset.dataframe,
    )

    assert result["rows"] == [{"ok": True}]


def test_runner_normalizes_list_values_in_result_rows(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")

    result = run_pandas_code(
        "def analyze(df):\n"
        "    return {'direct_answer': 'ok', 'rows': [{'customer_id': 'C-001', 'categories': ['Office', 'Hardware']}], 'columns': ['customer_id', 'categories']}",
        df=dataset.dataframe,
    )

    assert result["rows"] == [{"customer_id": "C-001", "categories": ["Office", "Hardware"]}]


def test_runner_normalizes_timestamp_values_in_result_rows(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")

    result = run_pandas_code(
        "def analyze(df):\n"
        "    value = pd.to_datetime(df['order_date']).min()\n"
        "    return {'direct_answer': 'ok', 'rows': [{'first_order_date': value}], 'columns': ['first_order_date']}",
        df=dataset.dataframe,
    )

    assert result["rows"] == [{"first_order_date": "2025-10-01T00:00:00"}]


def test_runner_accepts_pandas_index_columns_and_scalar_rows(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")

    result = run_pandas_code(
        "def analyze(df):\n"
        "    grouped = df.groupby('product', as_index=False)['sales'].sum()\n"
        "    return {'direct_answer': 'ok', 'rows': grouped.shape[0], 'columns': grouped.columns}",
        df=dataset.dataframe,
    )

    assert result["direct_answer"] == "ok"
    assert result["rows"] == [{"value": 4}]
    assert result["columns"] == ["product", "sales"]


def test_runner_accepts_scalar_rows_with_scalar_columns(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")

    result = run_pandas_code(
        "def analyze(df):\n"
        "    return {'direct_answer': 'ok', 'rows': df.shape[0], 'columns': df.shape[1]}",
        df=dataset.dataframe,
    )

    assert result["direct_answer"] == "ok"
    assert result["rows"] == [{"value": 6}]
    assert result["columns"] == ["value"]


def test_runner_normalizes_period_values_in_result_rows(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")

    result = run_pandas_code(
        "def analyze(df):\n"
        "    period = pd.to_datetime(df['order_date']).dt.to_period('M').iloc[0]\n"
        "    return {'direct_answer': 'ok', 'rows': [{'month': period}], 'columns': ['month']}",
        df=dataset.dataframe,
    )

    assert result["rows"] == [{"month": "2025-10"}]


def test_llm_response_missing_pandas_code_returns_diagnostic_error(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")
    agent = LlmPandasAgent(llm_client=StubLlmClient('{"intent": "total sales"}'))

    result = agent.ask(dataset, "总销售额是多少？")

    assert result["direct_answer"] == ""
    assert result["rows"] == []
    assert result["columns"] == []
    assert "pandas_code" in result["execution_error"]
    assert result["llm_raw"] == '{"intent": "total sales"}'


def test_agent_retries_once_with_failure_feedback_after_unsafe_import(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")
    llm = SequenceLlmClient(
        [
            json_payload(
                intent="unsafe attempt",
                pandas_code="import os\ndef analyze(df):\n    return {'direct_answer': 'bad', 'rows': [], 'columns': []}",
                expected_output="bad",
            ),
            json_payload(
                intent="safe total sales",
                pandas_code="def analyze(df):\n    total = float(df['sales'].sum())\n    return {'direct_answer': f'Total sales is {total:.1f}', 'rows': [{'metric': 'sales', 'value': total}], 'columns': ['metric', 'value']}",
                expected_output="safe total sales",
            ),
        ]
    )
    agent = LlmPandasAgent(llm_client=llm)

    result = agent.ask(dataset, "总销售额是多少？")

    assert result["direct_answer"] == "Total sales is 648.0"
    assert result["execution_error"] is None
    assert result["intent"] == "safe total sales"
    assert len(llm.prompts) == 3
    assert "上一次生成失败" in llm.prompts[1]
    assert "Import is not allowed in generated code: os" in llm.prompts[1]
    assert "可以按需 import 常见分析库" in llm.prompts[1]
    assert result["attempts"][0]["ok"] is False
    assert result["attempts"][1]["ok"] is True


def test_agent_retries_once_with_failure_feedback_after_syntax_error(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")
    llm = SequenceLlmClient(
        [
            json_payload(
                intent="broken syntax",
                pandas_code="def analyze(df):\n    return {'direct_answer': 'bad', 'rows': [}",
                expected_output="bad",
            ),
            json_payload(
                intent="safe count",
                pandas_code="def analyze(df):\n    return {'direct_answer': f'Rows: {len(df)}', 'rows': [{'rows': len(df)}], 'columns': ['rows']}",
                expected_output="row count",
            ),
        ]
    )
    agent = LlmPandasAgent(llm_client=llm)

    result = agent.ask(dataset, "这张表有多少行？")

    assert result["direct_answer"] == "Rows: 6"
    assert result["execution_error"] is None
    assert len(llm.prompts) == 3
    assert "invalid Python syntax" in llm.prompts[1]


def test_agent_retries_once_after_malformed_result_shape(tmp_path: Path) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")
    llm = SequenceLlmClient(
        [
            json_payload(
                intent="bad columns",
                pandas_code="def analyze(df):\n    return {'direct_answer': 'bad', 'rows': [{'value': 1}], 'columns': 1}",
                expected_output="bad",
            ),
            json_payload(
                intent="safe columns",
                pandas_code="def analyze(df):\n    return {'direct_answer': 'ok', 'rows': [{'value': 1}], 'columns': ['value']}",
                expected_output="safe",
            ),
        ]
    )
    agent = LlmPandasAgent(llm_client=llm)

    result = agent.ask(dataset, "返回一个合法表格")

    assert result["direct_answer"] == "ok"
    assert result["execution_error"] is None
    assert len(llm.prompts) == 3
    assert "columns" in llm.prompts[1]
    assert result["attempts"][0]["ok"] is False
    assert result["attempts"][1]["ok"] is True


def test_parse_llm_json_accepts_python_dict_style_expected_output_numeric_keys() -> None:
    payload = parse_llm_json(
        """
        {
          "intent": "compare months",
          "assumptions": [],
          "pandas_code": "def analyze(df):\\n    return {'direct_answer': 'ok', 'rows': [], 'columns': []}",
          "expected_output": {
            "rows": [
              {"product": "Monitor", 10: 0.0, 11: 360.0}
            ]
          }
        }
        """
    )

    assert payload["intent"] == "compare months"
    assert "def analyze" in payload["pandas_code"]


def test_parse_llm_json_repairs_common_filter_value_missing_bracket() -> None:
    payload = parse_llm_json(
        r'''
        {
          "intent": "decompose March sales",
          "semantic_interpretation": {
            "filters": [{"field": "sign_time", "operator": "between", "value": ["2026-03-01", "2026-04-01)"}]
          },
          "assumptions": [],
          "pandas_code": "def analyze(df):\n    return {'direct_answer': 'ok', 'rows': [], 'columns': []}",
          "expected_output": "empty diagnostic"
        }
        '''
    )

    assert payload["semantic_interpretation"]["filters"][0]["value"] == ["2026-03-01", "2026-04-01)"]
    assert "def analyze" in payload["pandas_code"]


@pytest.mark.parametrize(
    ("intent", "code", "expected_answer"),
    [
        (
            "summary total sales",
            "def analyze(df):\n"
            "    total = float(df['sales'].sum())\n"
            "    return {'direct_answer': f'Total sales is {total:.1f}', 'rows': [{'metric': 'sales', 'value': total}], 'columns': ['metric', 'value']}",
            "Total sales is 648.0",
        ),
        (
            "monthly trend",
            "def analyze(df):\n"
            "    data = df.copy()\n"
            "    data['month'] = pd.to_datetime(data['order_date']).dt.strftime('%Y-%m')\n"
            "    rows = data.groupby('month', as_index=False)['sales'].sum().sort_values('month')\n"
            "    return {'direct_answer': 'Monthly sales trend calculated', 'rows': rows.to_dict(orient='records'), 'columns': list(rows.columns)}",
            "Monthly sales trend calculated",
        ),
        (
            "return filter",
            "def analyze(df):\n"
            "    rows = df[df['is_return'] == True].groupby('product', as_index=False)['quantity'].sum().sort_values('quantity')\n"
            "    return {'direct_answer': f\"Most returned product is {rows.iloc[0]['product']}\", 'rows': rows.to_dict(orient='records'), 'columns': list(rows.columns)}",
            "Most returned product is Notebook",
        ),
        (
            "top share",
            "def analyze(df):\n"
            "    rows = df.groupby('product', as_index=False)['sales'].sum().sort_values('sales', ascending=False).head(2)\n"
            "    share = float(rows['sales'].sum() / df['sales'].sum())\n"
            "    rows['share_of_total'] = rows['sales'] / df['sales'].sum()\n"
            "    return {'direct_answer': f'Top 2 products account for {share:.1%}', 'rows': rows.to_dict(orient='records'), 'columns': list(rows.columns)}",
            "Top 2 products account for 82.6%",
        ),
        (
            "country gap",
            "def analyze(df):\n"
            "    rows = df.groupby('country', as_index=False)['sales'].sum()\n"
            "    uk = float(rows.loc[rows['country'] == 'UK', 'sales'].iloc[0])\n"
            "    rows['gap_vs_uk'] = rows['sales'] - uk\n"
            "    return {'direct_answer': 'Country gap vs UK calculated', 'rows': rows.to_dict(orient='records'), 'columns': list(rows.columns)}",
            "Country gap vs UK calculated",
        ),
        (
            "data quality",
            "def analyze(df):\n"
            "    rows = [{'column': col, 'missing_count': int(df[col].isna().sum())} for col in df.columns]\n"
            "    return {'direct_answer': 'Data quality scan completed', 'rows': rows, 'columns': ['column', 'missing_count']}",
            "Data quality scan completed",
        ),
    ],
)
def test_backend_executes_llm_chosen_generated_code_examples(
    tmp_path: Path,
    intent: str,
    code: str,
    expected_answer: str,
) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")
    llm = StubLlmClient(
        json_payload(intent=intent, pandas_code=code, expected_output="llm chosen analysis result")
    )
    agent = LlmPandasAgent(llm_client=llm)

    result = agent.ask(dataset, "请你自己判断这张表应该如何分析")

    assert result["direct_answer"] == expected_answer
    assert result["execution_error"] is None
    assert result["rows"]
    assert result["columns"]


def test_ask_persists_run_debug_record_for_lookup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    project_store = ProjectStore(path=tmp_path / "storage" / "chat_state.json")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")
    monkeypatch.setattr(chat_api, "store", store)
    monkeypatch.setattr(chat_api, "project_store", project_store)
    monkeypatch.setattr(
        chat_api,
        "create_llm_client",
        lambda: StubLlmClient(
            """
            {
              "intent": "total sales",
              "assumptions": [],
              "pandas_code": "def analyze(df):\\n    total = float(df['sales'].sum())\\n    return {'direct_answer': f'Total sales is {total:.1f}', 'rows': [{'metric': 'sales', 'value': total}], 'columns': ['metric', 'value']}",
              "expected_output": "total sales"
            }
            """
        ),
    )

    response = chat_api.ask(AskPayload(dataset_id=dataset.dataset_id, question="总销售额是多少？"))
    lookup = chat_api.run(response["run_id"])

    assert lookup["status"] == "completed"
    assert lookup["payload"]["direct_answer"] == "Total sales is 648.0"
    assert "pandas_code" in lookup["payload"]
    assert response["project_id"] == ""
    assert project_store.list_projects() == []
    assert project_store.list_conversations()[0]["conversation_id"] == response["conversation_id"]


def test_project_conversation_inherits_project_dataset_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = CsvDatasetStore(root_dir=tmp_path / "storage")
    project_store = ProjectStore(path=tmp_path / "storage" / "chat_state.json")
    dataset = store.save_upload(write_csv(tmp_path), original_filename="sales.csv")
    project = project_store.create_project("Project Context")
    project_store.update_project_dataset(project["project_id"], dataset.dataset_id, dataset.profile)
    conversation = project_store.create_conversation(project_id=project["project_id"], title="新对话")
    monkeypatch.setattr(chat_api, "store", store)
    monkeypatch.setattr(chat_api, "project_store", project_store)
    monkeypatch.setattr(
        chat_api,
        "create_llm_client",
        lambda: StubLlmClient(
            json_payload(
                intent="total sales",
                pandas_code=(
                    "def analyze(df):\n"
                    "    total = float(df['sales'].sum())\n"
                    "    return {'direct_answer': f'Total sales is {total:.1f}', 'rows': [{'metric': 'sales', 'value': total}], 'columns': ['metric', 'value']}"
                ),
                expected_output="total sales",
            )
        ),
    )

    response = chat_api.ask(
        AskPayload(
            project_id=project["project_id"],
            conversation_id=conversation["conversation_id"],
            question="总销售额是多少？",
        )
    )
    stored_conversation = project_store.get_conversation(conversation["conversation_id"])

    assert response["dataset_id"] == dataset.dataset_id
    assert response["project_id"] == project["project_id"]
    assert response["conversation_id"] == conversation["conversation_id"]
    assert response["direct_answer"] == "Total sales is 648.0"
    assert stored_conversation is not None
    assert stored_conversation["dataset_id"] == dataset.dataset_id
    assert len(stored_conversation["turns"]) == 1


def json_payload(
    intent: str,
    pandas_code: str,
    expected_output: str,
    data_brief: dict | None = None,
    semantic_interpretation: dict | None = None,
    response_sections: dict | None = None,
    chart_spec: dict | None = None,
) -> str:
    import json

    return json.dumps(
        {
            "data_brief": data_brief or {"dataset_summary": "stub data brief"},
            "semantic_interpretation": semantic_interpretation or {
                "operation_type": "aggregate",
                "target_table": None,
                "target_tables": [],
                "metric": "sales",
                "metric_formula_or_assumption": "stub metric assumption",
                "aggregation": "sum",
                "dimension": None,
                "filters": [],
                "time_field": None,
                "time_grain": None,
                "sort": None,
                "top_n": None,
                "required_join_path": [],
                "expected_output_shape": "table",
                "context_inheritance": {},
                "ambiguity_notes": [],
                "confidence": 0.8,
            },
            "intent": intent,
            "assumptions": [],
            "response_sections": response_sections or {
                "result_summary": "stub result summary",
                "analysis": ["stub analysis"],
                "insights": ["stub insight"],
                "next_steps": ["stub next step"],
            },
            "chart_spec": chart_spec or {
                "chart_type": "kpi",
                "title": "stub chart",
                "x": "metric",
                "y": "value",
                "reason": "stub chart spec",
                "confidence": 0.5,
            },
            "pandas_code": pandas_code,
            "expected_output": expected_output,
        },
        ensure_ascii=False,
    )
