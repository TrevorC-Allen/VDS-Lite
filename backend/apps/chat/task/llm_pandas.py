from __future__ import annotations

import json
import os
import re
import uuid
import ast
from dataclasses import dataclass, is_dataclass, replace
from typing import Any, Protocol

import pandas as pd

from backend.apps.chat.task.chart_renderer import build_rendered_chart
from backend.apps.chat.task.code_runner import CodeExecutionError, UnsafeCodeError, run_pandas_code
from backend.apps.datasource.store import CsvDataset

PROMPT_PROFILE_ROW_LIMIT = 1
PROMPT_SAMPLE_COLUMN_LIMIT = 14
PROMPT_SAMPLE_VALUE_LIMIT = 3
PROMPT_RELATION_LIMIT = 18
PROMPT_FILE_CONTEXT_LIMIT = 22000
PROMPT_TABLE_CONTEXT_LIMIT = 1000
PROMPT_CANDIDATE_COLUMN_LIMIT = 24
PROMPT_MEASURE_DETAIL_LIMIT = 20
PROMPT_GUIDELINE_LIMIT = 6000


class LlmClient(Protocol):
    def complete(self, prompt: str) -> str:
        ...


@dataclass(frozen=True)
class AgentRun:
    run_id: str
    payload: dict[str, Any]


class SemanticSanityError(ValueError):
    pass


class LlmPandasAgent:
    def __init__(self, llm_client: LlmClient, max_attempts: int = 3):
        self.llm_client = llm_client
        self.max_attempts = max_attempts

    def ask(
        self,
        dataset: CsvDataset,
        question: str,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        original_prompt = build_prompt_for_question(dataset=dataset, question=question, conversation_history=conversation_history)
        prompt = original_prompt
        attempts: list[dict[str, Any]] = []
        llm_raw = ""
        llm_payload: dict[str, Any] = {}
        pandas_code = ""
        execution = {"direct_answer": "", "rows": [], "columns": []}
        response_sections: dict[str, Any] = {}
        chart: dict[str, Any] = {}
        sanity_checks: dict[str, Any] = {"ok": True, "checks": [], "errors": []}
        execution_error: str | None = None

        for attempt_index in range(1, self.max_attempts + 1):
            try:
                llm_raw = self.llm_client.complete(prompt)
            except Exception as exc:  # Provider/network failures must be returned as diagnostics, not HTTP 500.
                execution_error = f"{type(exc).__name__}: {exc}"
                fallback = build_deterministic_trend_fallback(
                    dataset=dataset,
                    question=question,
                    execution_error=execution_error,
                    require_provider_error=True,
                )
                if fallback:
                    execution = fallback["execution"]
                    llm_payload = fallback["llm_payload"]
                    response_sections = normalize_response_sections(fallback.get("response_sections") or {}, execution)
                    chart = build_rendered_chart(fallback.get("chart_spec") or {}, execution)
                    sanity_checks = {
                        "ok": True,
                        "checks": [{"name": "deterministic_timeout_fallback", "ok": True}],
                        "errors": [],
                    }
                    execution_error = None
                    attempts.append(
                        {
                            "attempt": attempt_index,
                            "ok": True,
                            "llm_raw": "",
                            "pandas_code": "",
                            "error": None,
                            "fallback": "deterministic_trend",
                        }
                    )
                else:
                    attempts.append(
                        {
                            "attempt": attempt_index,
                            "ok": False,
                            "llm_raw": llm_raw,
                            "pandas_code": pandas_code,
                            "error": execution_error,
                        }
                    )
                break
            try:
                llm_payload = parse_llm_json(llm_raw)
                pandas_code = str(llm_payload["pandas_code"])
                execution = run_pandas_code(pandas_code, dataset.dataframe, tables=dataset.tables)
                sanity_checks = run_llm_semantic_verifier(
                    dataset=dataset,
                    question=question,
                    conversation_history=conversation_history or [],
                    llm_payload=llm_payload,
                    execution=execution,
                    pandas_code=pandas_code,
                    llm_client=self.llm_client,
                )
                base_response_sections = normalize_response_sections(
                    execution.get("response_sections") or llm_payload.get("response_sections") or {},
                    execution,
                )
                chart = build_rendered_chart(llm_payload.get("chart_spec") or {}, execution)
                response_sections = generate_result_response_sections(
                    dataset=dataset,
                    question=question,
                    conversation_history=conversation_history or [],
                    llm_payload=llm_payload,
                    execution=execution,
                    chart=chart,
                    fallback_sections=base_response_sections,
                    llm_client=self.llm_client,
                )
                execution_error = None
                attempts.append(
                    {
                        "attempt": attempt_index,
                        "ok": True,
                        "llm_raw": llm_raw,
                        "pandas_code": pandas_code,
                        "error": None,
                    }
                )
                break
            except (KeyError, json.JSONDecodeError, UnsafeCodeError, CodeExecutionError, ValueError, SemanticSanityError) as exc:
                if "llm_payload" not in locals() or not isinstance(llm_payload, dict):
                    llm_payload = {}
                pandas_code = str(llm_payload.get("pandas_code") or "")
                execution_error = str(exc)
                attempts.append(
                    {
                        "attempt": attempt_index,
                        "ok": False,
                        "llm_raw": llm_raw,
                        "pandas_code": pandas_code,
                        "error": execution_error,
                    }
                )
                if attempt_index < self.max_attempts and llm_raw:
                    prompt = build_repair_prompt(
                        original_prompt=original_prompt,
                        previous_raw=llm_raw,
                        previous_code=pandas_code,
                        error=execution_error,
                    )

        if execution_error:
            fallback = build_deterministic_trend_fallback(
                dataset=dataset,
                question=question,
                execution_error=execution_error,
                require_provider_error=False,
            )
            if fallback:
                execution = fallback["execution"]
                llm_payload = fallback["llm_payload"]
                response_sections = normalize_response_sections(fallback.get("response_sections") or {}, execution)
                chart = build_rendered_chart(fallback.get("chart_spec") or {}, execution)
                sanity_checks = {
                    "ok": True,
                    "checks": [{"name": "deterministic_trend_fallback", "ok": True}],
                    "errors": [],
                }
                llm_raw = ""
                pandas_code = ""
                execution_error = None
                attempts = [
                    {
                        "attempt": len(attempts) + 1,
                        "ok": True,
                        "llm_raw": "",
                        "pandas_code": "",
                        "error": None,
                        "fallback": "deterministic_trend",
                    }
                ]

        uncomputable_diagnostic = build_uncomputable_diagnostic(question, execution_error)
        if uncomputable_diagnostic:
            execution = uncomputable_diagnostic
            response_sections = normalize_response_sections({}, execution)
            chart = {}
            sanity_checks = {
                "ok": True,
                "checks": [{"name": "uncomputable_field_diagnostic", "ok": True}],
                "errors": [],
            }
            execution_error = None

        return {
            "run_id": run_id,
            "direct_answer": execution["direct_answer"],
            "rows": execution["rows"],
            "columns": execution["columns"],
            "intent": llm_payload.get("intent", ""),
            "data_brief": llm_payload.get("data_brief", {}),
            "semantic_interpretation": llm_payload.get("semantic_interpretation", {}),
            "assumptions": llm_payload.get("assumptions", []),
            "expected_output": llm_payload.get("expected_output", ""),
            "response_sections": response_sections,
            "chart": chart,
            "pandas_code": pandas_code,
            "llm_raw": llm_raw,
            "sanity_checks": sanity_checks,
            "execution_error": execution_error,
            "attempts": attempts,
        }


def build_prompt_for_question(
    dataset: CsvDataset,
    question: str,
    conversation_history: list[dict[str, Any]] | None = None,
) -> str:
    if is_dataset_overview_question(question):
        return build_overview_prompt(dataset=dataset, question=question, conversation_history=conversation_history)
    return build_prompt(dataset=dataset, question=question, conversation_history=conversation_history)


def is_dataset_overview_question(question: str) -> bool:
    normalized = re.sub(r"\s+", "", question)
    if not normalized:
        return False
    overview_phrases = [
        "看一下这个数据文件",
        "看下这个数据文件",
        "看一下这个数据",
        "看下这个数据",
        "研究一下这个数据",
        "研究下这个数据",
        "数据概览",
        "数据集概览",
        "整体概览",
    ]
    if any(phrase in normalized for phrase in overview_phrases):
        return True
    table_scope = any(token in normalized for token in ["各个表", "每张表", "所有表", "表结构"])
    table_relationship = any(token in normalized for token in ["关系", "联系", "怎么连", "关联", "讲的什么", "是什么", "用途"])
    return table_scope and table_relationship


def build_uncomputable_diagnostic(question: str, execution_error: str | None) -> dict[str, Any] | None:
    if not execution_error:
        return None
    if "LLM verifier rejected result" not in execution_error:
        return None
    if not any(token in execution_error for token in ["全为空", "字段全空", "无法安全计算"]):
        return None

    issues = _extract_verifier_issues(execution_error)
    useful_issues = [
        issue
        for issue in issues
        if any(token in issue for token in ["全为空", "无法安全计算", "字段", "粒度", "门店", "PSD", "UPT", "AT"])
    ]
    reason = "；".join(useful_issues[:3]) or "相关指标字段或对象粒度字段为空，无法安全计算。"
    requested_metric = _first_match(question, ["PSD", "UPT", "AT", "HW", "RSI", "AWT", "ASP"]) or "用户请求指标"
    requested_dimension = _first_match(question, ["门店", "站点", "院区", "校区", "客户", "城市"]) or "用户请求对象"
    blocking_fields = []
    for field in ["PSD_row", "UPT_row", "AT_row", "门店名称", requested_metric, requested_dimension]:
        if field and field not in blocking_fields and field in execution_error:
            blocking_fields.append(field)
    if not blocking_fields:
        blocking_fields = [requested_metric, requested_dimension]

    rows = [
        {
            "requested_metric": requested_metric,
            "requested_dimension": requested_dimension,
            "blocking_field": field,
            "evidence": "字段为空或缺少可安全计算该口径所需的数据",
            "status": "无法安全计算",
            "next_step": "补充该字段，或提供明确可推导公式及所需分母/对象粒度字段",
        }
        for field in blocking_fields
    ]
    return {
        "direct_answer": f"这个问题无法安全计算。原因：{reason}",
        "rows": rows,
        "columns": ["requested_metric", "requested_dimension", "blocking_field", "evidence", "status", "next_step"],
    }


def _extract_verifier_issues(execution_error: str) -> list[str]:
    match = re.search(r"LLM verifier rejected result:\s*(\[.*\])", execution_error, flags=re.S)
    if match:
        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            pass
    return [execution_error]


def build_deterministic_trend_fallback(
    dataset: CsvDataset,
    question: str,
    execution_error: str,
    *,
    require_provider_error: bool,
) -> dict[str, Any] | None:
    if require_provider_error and not any(token in execution_error for token in ("TimeoutError", "timed out", "ConnectionError")):
        return None
    if not any(token in question for token in ("走势", "趋势", "折线", "每月", "按月")):
        return None
    date_range = _extract_yyyymm_range(question)
    for table_name, df in dataset.tables.items():
        if df.empty or _table_role(table_name, dataset.csv_texts.get(table_name, "")) == "guideline":
            continue
        category = _find_question_value_column(df, question)
        if not category:
            continue
        category_col, category_values = category
        time_col = _find_time_column(df)
        metric_col = _find_metric_column(df, question, exclude={category_col, time_col or ""})
        if not time_col or not metric_col:
            continue
        working = df[[time_col, category_col, metric_col]].copy()
        working["__年月"] = _series_to_yyyymm(working[time_col])
        working["__metric"] = pd.to_numeric(working[metric_col], errors="coerce")
        working = working[working[category_col].astype(str).isin(category_values)]
        working = working.dropna(subset=["__年月", "__metric"])
        if date_range:
            start, end = date_range
            working = working[(working["__年月"] >= start) & (working["__年月"] <= end)]
        if working.empty:
            continue
        grouped = (
            working.groupby(["__年月", category_col], as_index=False)["__metric"]
            .sum()
            .sort_values(["__年月", category_col])
        )
        grouped = grouped.rename(columns={"__年月": "年月", category_col: "陈列类别", "__metric": "执行量"})
        rows = grouped[["年月", "陈列类别", "执行量"]].to_dict(orient="records")
        answer = f"已按月聚合返回{len(rows)}条趋势记录。"
        execution = {
            "direct_answer": answer,
            "rows": _fallback_json_rows(rows),
            "columns": ["年月", "陈列类别", "执行量"],
        }
        return {
            "execution": execution,
            "llm_payload": {
                "intent": "deterministic monthly trend fallback",
                "semantic_interpretation": {
                    "operation_type": "monthly_trend",
                    "target_table": table_name,
                    "metric": metric_col,
                    "dimension": category_col,
                    "time_field": time_col,
                    "filters": {"mentioned_values": category_values},
                    "execution_path": "deterministic_trend_aggregation",
                },
                "assumptions": [f"使用表 {table_name}，按 {time_col}、{category_col} 聚合 {metric_col}。"],
                "expected_output": "monthly trend rows",
            },
            "response_sections": {
                "result_summary": answer,
                "analysis": [
                    f"使用 {table_name} 表，按 {time_col} 转换年月，筛选问题中点名的类别：{', '.join(category_values)}。",
                    f"按年月和 {category_col} 聚合 {metric_col}，生成趋势表和折线图。",
                ],
                "insights": _fallback_trend_insights(rows),
                "next_steps": ["继续查看峰值月份的门店或业代拆分。", "结合销售金额对比陈列执行量和分销表现。"],
            },
            "chart_spec": {
                "chart_type": "line",
                "title": "月度趋势",
                "x": "年月",
                "y": "执行量",
                "reason": "Deterministic trend aggregation rendered from execution rows.",
                "confidence": 0.75,
            },
        }
    return None


def _extract_yyyymm_range(question: str) -> tuple[int, int] | None:
    match = re.search(r"(20\d{2})年(\d{1,2})月.*?(?:至|到|-|~)(20\d{2})年(\d{1,2})月", question)
    if not match:
        return None
    start = int(match.group(1)) * 100 + int(match.group(2))
    end = int(match.group(3)) * 100 + int(match.group(4))
    return (start, end) if start <= end else (end, start)


def _find_question_value_column(df: pd.DataFrame, question: str) -> tuple[str, list[str]] | None:
    best: tuple[str, list[str]] | None = None
    for column in df.columns:
        if not _looks_categorical_series(df[column]):
            continue
        values: list[str] = []
        for value in df[column].dropna().astype(str).drop_duplicates().head(500):
            text = value.strip()
            if len(text) >= 2 and text in question and text not in values:
                values.append(text)
        if len(values) >= 2 and (best is None or len(values) > len(best[1])):
            best = (str(column), values)
    return best


def _looks_categorical_series(series: pd.Series) -> bool:
    if not (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series) or isinstance(series.dtype, pd.CategoricalDtype)):
        return False
    non_null = series.dropna()
    return not non_null.empty and non_null.astype(str).nunique() <= 500


def _find_time_column(df: pd.DataFrame) -> str | None:
    preferred = ["execute_ym", "stat_month", "year_month", "month_id", "年月", "ymd", "date", "date_fmt"]
    lower_lookup = {str(column).lower(): str(column) for column in df.columns}
    for name in preferred:
        if name.lower() in lower_lookup:
            return lower_lookup[name.lower()]
    for column in df.columns:
        lowered = str(column).lower()
        if any(token in lowered for token in ("ym", "month", "date", "time", "年月", "日期")):
            return str(column)
    return None


def _find_metric_column(df: pd.DataFrame, question: str, *, exclude: set[str]) -> str | None:
    numeric_columns = [str(column) for column in df.columns if str(column) not in exclude and pd.api.types.is_numeric_dtype(df[column])]
    if not numeric_columns:
        return None
    keywords: list[str]
    if any(token in question for token in ("执行量", "次数", "陈列")):
        keywords = ["unit_cnt", "exec", "times", "load_cnt", "cnt", "nums", "数量"]
    elif any(token in question for token in ("金额", "销售", "分销")):
        keywords = ["amt", "amount", "sales", "target", "金额"]
    else:
        keywords = ["amt", "amount", "cnt", "count", "qty", "value"]
    scored: list[tuple[int, str]] = []
    for column in numeric_columns:
        lowered = column.lower()
        nonzero = pd.to_numeric(df[column], errors="coerce").fillna(0).abs().sum() > 0
        score = (10 if nonzero else 0) + sum(5 for keyword in keywords if keyword in lowered)
        if lowered in {"execute_ym", "stat_month", "year_id", "month_id"}:
            score -= 20
        scored.append((score, column))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored[0][1] if scored and scored[0][0] > 0 else None


def _series_to_yyyymm(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().any() and numeric.dropna().between(190001, 219912).mean() > 0.8:
        return numeric.astype("Int64")
    parsed = pd.to_datetime(series, errors="coerce")
    return (parsed.dt.year * 100 + parsed.dt.month).astype("Int64")


def _fallback_trend_insights(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["本地聚合没有返回可用趋势点。"]
    by_category: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_category.setdefault(str(row.get("陈列类别")), []).append(row)
    insights: list[str] = []
    for category, items in list(by_category.items())[:3]:
        values = [float(item.get("执行量") or 0) for item in items]
        months = [item.get("年月") for item in items]
        if not values:
            continue
        max_index = max(range(len(values)), key=lambda index: values[index])
        insights.append(f"{category}在{months[max_index]}达到最高执行量{values[max_index]:.2f}。")
    return insights or ["已按类别生成月度趋势，可继续下钻峰值月份。"]


def _fallback_json_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{str(key): _json_prompt_safe(value) for key, value in row.items()} for row in rows]


def _first_match(text: str, tokens: list[str]) -> str | None:
    for token in tokens:
        if token in text:
            return token
    return None


def build_overview_prompt(
    dataset: CsvDataset,
    question: str,
    conversation_history: list[dict[str, Any]] | None = None,
) -> str:
    profile_json = json.dumps(_compact_profile_for_prompt(dataset, question=question, overview=True), ensure_ascii=False, separators=(",", ":"))
    evidence_pack_json = json.dumps(_compact_evidence_pack_for_prompt(dataset, question=question, overview=True), ensure_ascii=False, separators=(",", ":"))
    business_guidelines = _business_guidelines_for_prompt(dataset=dataset, question=question)
    file_context = _file_context(dataset)
    analyze_contract = _analyze_contract(dataset)
    history_context = _history_context(conversation_history or [])
    analyze_function = "analyze(tables)" if len(dataset.tables) > 1 else "analyze(df)"
    return f"""你是一个 CSV / Excel 数据分析 Agent。当前任务是【数据概览专用】，不是普通 TopN、排名、KPI 或趋势题。

你必须先扫字段 profile、Evidence Pack、文件内容摘要、样例值和上传 guideline，给用户一版 GPT-like 的数据理解说明：每张表讲什么、表之间怎么连、核心关联键、业务链路和关键业务口径。

要求：
1. 只输出一个 JSON 对象，不要输出 markdown。
2. JSON 字段必须包含 data_brief、semantic_interpretation、intent、assumptions、response_sections、chart_spec、pandas_code、expected_output。
3. 这是数据概览专用 prompt。不要默认输出业代TopN/排名、客户TopN、品类TopN、单一汇总值或图表作为主答案。
4. 你必须回答“每张表讲什么”和“表之间怎么连”，不要把数据概览降级成某一张事实表的销售额汇总。
5. direct_answer 第一屏必须先说明数据域/业务主线，例如“门店 -> 人员 -> 拜访 -> 订单 -> 陈列/稽查 -> 目标达成”这类从数据证据推断出的业务链路；没有足够证据时要说明不确定性。
6. response_sections 必须包含：
   - result_summary：数据整体是什么业务域、主业务链路是什么。
   - analysis：每张业务数据表和 guideline/说明表的角色、粒度、用途。
   - insights：表之间怎么连、核心关联键、可安全 join 路径和不确定关系。
   - next_steps：用户可以继续问的分析方向。
7. rows 应返回表级清单；columns 建议为 ['表', '角色', '含义', '粒度', '主要用途', '关键关联键']。可以额外加行数、字段数、时间字段、候选指标等列，但必须保持每行是一张表。
8. 业务数据表和 guideline/说明表必须分开说明。guideline/说明表可用于解释表含义、字段、规则和答案格式，但除非用户明确问规则本身，不要把它当事实数据参与 join/groupby/sum/count。
9. 对每张表的“含义/粒度/主要用途/关键关联键”，优先综合使用上传的“数据表说明/字段说明/问题示例/sheet1”等 guideline、字段名、样例值、候选指标/维度/时间字段和 relation_evidence；不要编造不存在的表或字段。
10. pandas_code 必须定义 {analyze_function} -> dict，并返回 direct_answer、rows、columns；多表数据使用 tables dict，单表数据使用 df。
11. 概览里的表含义、粒度、用途、关联键属于 schema/profile/guideline 描述，可以来自 prompt 证据；行数、字段数、日期范围、distinct 数等数值如出现在答案中，必须由 Pandas 代码计算。
12. 如果生成 response_sections，必须和 direct_answer、rows 一致；不要在 direct_answer 说 A 表是事实表，rows 里又写成规则表。
13. chart_spec 默认选择 {{"chart_type": "none", "title": "", "x": "", "y": "", "reason": "数据概览以表级解释和关系说明为主，不需要默认图表", "confidence": 0.0}}；只有用户明确要求图时才画。
14. expected_output 必须是短字符串，只描述输出形态，不要放 rows、columns、示例表格或嵌套对象。
15. 安全边界是硬约束：禁止使用 open、eval、exec、__import__、os、sys、subprocess、socket、pathlib、shutil，禁止读写文件、访问网络、调用 shell。
16. {analyze_contract}

用户问题：
{question}

对话历史：
{history_context}

业务口径 / guideline（高优先级，优先于默认规则）：
{business_guidelines}

字段 profile：
{profile_json}

Evidence Pack：
{evidence_pack_json}

文件内容摘要与代表性样本：
{file_context}
"""


def build_prompt(
    dataset: CsvDataset,
    question: str,
    conversation_history: list[dict[str, Any]] | None = None,
) -> str:
    profile_json = json.dumps(_compact_profile_for_prompt(dataset, question=question), ensure_ascii=False, separators=(",", ":"))
    evidence_pack_json = json.dumps(_compact_evidence_pack_for_prompt(dataset, question=question), ensure_ascii=False, separators=(",", ":"))
    business_guidelines = _business_guidelines_for_prompt(dataset=dataset, question=question)
    file_context = _file_context(dataset, question=question)
    analyze_contract = _analyze_contract(dataset)
    history_context = _history_context(conversation_history or [])
    return f"""你是一个 CSV 数据分析 Agent。你必须阅读字段 profile、文件内容摘要和代表性样本，然后生成 Pandas 代码。

要求：
1. 只输出一个 JSON 对象，不要输出 markdown。
2. JSON 字段必须包含 data_brief、semantic_interpretation、intent、assumptions、response_sections、chart_spec、pandas_code、expected_output。
3. expected_output 必须是短字符串，只描述输出形态，不要放 rows、columns、示例表格或嵌套对象。
4. 你必须自己决定分析意图、分析步骤和 Pandas 代码；不要从后端预设菜单中选择。
5. 后端不会替你选择任何分析操作；你必须根据用户问题和 CSV 内容自行判断应该做什么。
6. {analyze_contract}
7. analyze(df) 返回 dict，至少包含 direct_answer、rows、columns；如果能写出更好的分段回复，可以额外返回 response_sections。
8. rows 必须是 list[dict]，例如 result_df.to_dict(orient='records')；不要把 rows 写成 shape[0]、len(result_df)、字符串或单个数字。
9. columns 必须是列名列表，例如 list(result_df.columns)；不要把 columns 写成 shape[1] 或列数。
10. 如果只有一个汇总值，也要返回 rows=[{{'metric': '...', 'value': 数字}}] 和 columns=['metric', 'value']。
11. 最终数字必须由 Pandas 代码计算，不能直接把你心算的数字写成答案。
12. 允许按需 import 常见分析库，例如 pandas、numpy、math、datetime、re、dateutil、calendar；如果没有必要，也可以直接使用后端已提供的 pd。
13. 安全边界是硬约束：禁止使用 open、eval、exec、__import__、os、sys、subprocess、socket、pathlib、shutil，禁止读写文件、访问网络、调用 shell。
14. 如果违反这些边界，后端会拒绝执行，并要求你重写安全的 Pandas 代码。
15. df 或 tables 已经由后端传入，列名和表名必须严格使用 CSV context 中给出的名字。
16. 如果用户问题是追问、代词、省略问法或“继续/这个/它/变化率/占比”等上下文相关问题，必须结合对话历史理解指代对象、筛选条件、指标和时间粒度。
17. data_brief 必须由你基于 Evidence Pack 生成，说明数据集、表、行粒度、候选指标、候选维度、候选时间字段、候选 join 关系和不确定性；不要编造字段或关系。
18. semantic_interpretation 必须由你基于用户问题、data_brief、Evidence Pack 和对话历史生成，至少包含 operation_type、target_table、target_tables、metric、metric_formula_or_assumption、aggregation、dimension、filters、time_field、time_grain、sort、top_n、required_join_path、expected_output_shape、context_inheritance、ambiguity_notes、confidence。
18a. 用户问题中的“口径提示/答案格式/计算公式”和上传文件中的业务口径、字段说明、数据表说明、问题示例、guideline 是高优先级上下文。默认防错规则只在这些高优先级上下文没有明确规定时生效；如果存在冲突，必须优先遵守用户口径和上传 guideline，并在 assumptions 说明取舍。
19. 两期/多期变化 TopN 是高优先级硬约束：如果用户问“本周与上周相比/上周较上上周/按月变化/增加最多/减少最多/增长最多/下降最多”，必须先明确指标类型和变化方向。金额、收入、销量、订单数、客户数等可加总指标，可以保留对象并集并把缺失周期按 0 处理；但率、均值、得分、客单价、人均/单均指标、PSD/UPT/AT/HW/RSI/AWT/ASP 等非可加总指标，不能把缺失周期填 0 当成真实下降或上升，必须只比较两期都有事实记录且分母有效的对象，或明确返回“无足够两期事实”。只有用户或 guideline 明确说“缺失按0/包括无记录对象”才允许对非可加总指标填 0。
20. 金额/收入/销售额不要只用 quantity；销量/件数不要和金额混淆；订单数、客户数、商品数要区分 count rows 和 count distinct entity；明细查询不要压成单行摘要；TopN 必须有 metric/dimension/sort/top_n；trend 必须有 time_field/time_grain；gap 必须说明比较对象和差值口径。
21. response_sections 必须用于更完整的用户回复，结构为 {{"result_summary": "先给结果", "analysis": ["分析点1", "分析点2"], "insights": ["洞察1", "洞察2"], "next_steps": ["下一步问题1", "下一步问题2"]}}。如果 analyze() 返回 response_sections，内容必须由代码基于真实执行结果生成。
22. chart_spec 必须由你根据用户问题、上下文和预期结果选择，结构为 {{"chart_type": "kpi|bar|horizontal_bar|line|pie|donut|none", "title": "...", "x": "结果列名", "y": "结果列名", "reason": "为什么这样画", "confidence": 0.0}}。
23. 只在明细记录、纯文本解释、没有可视化价值或结果不可画时选择 chart_type="none"；其他情况下尽量选择一个能回答问题的图。TopN/排名通常用 bar 或 horizontal_bar，趋势通常用 line，构成/占比通常用 pie 或 donut，单一汇总值用 kpi。
24. chart_spec 只决定图表类型和编码列，图表数据必须来自 Pandas 执行后的 rows，不能在 chart_spec 中手写或编造数字。
25. 对“增加最多/增长最多/减少最多/下降最多/差额最大/变化最大/排名变化最大”这类 TopN 变化问题，默认先计算所有对象的 signed change 或 gap。用户问“增加最多/增长最多”时必须优先筛选 change > 0 并降序；用户问“减少最多/下降最多”时必须优先筛选 change < 0 并升序，结果中不能混入正值并称为下降/减少。如果实际正增长或负下降对象不足 N 个，可以返回少于 N 行，但 direct_answer 必须说明“符合条件的对象不足 N 个”；如果没有符合方向的对象，可以返回最接近候选，但必须单独标注“非实际增长/非实际下降候选”，不得把反方向变化说成增长或下降。
26. 生成代码必须防御空结果：在访问 rows[0]、rows[-1]、iloc[0]、max/min 前必须判断结果是否为空；空结果时返回可诊断 direct_answer、rows=[]、columns=预期列名，不要抛 IndexError。
27. 周/月/上周/上上周/本周对比要优先使用数据中的真实时间字段、周序号、周标签或日期推导；如果自然语言标签列没有“上上周”等值，不要直接构造不存在的标签导致空表，应改用周序号或日期排序推导最近几个周期。
28. 如果用户问题中出现“类别A/客户A/门店A/项目A/某品类/XX”等明显占位符，且字段样例中不存在该精确值，不要直接按占位符过滤成空表；应从 Evidence Pack 或样例值中选择一个真实存在的代表值进行分析，并在 assumptions、direct_answer 中说明“将占位符按某真实值处理”。如果无法安全选择，返回可诊断问题而不是硬算空结果。
29. 如果用户使用的业务维度词对应字段缺失或全为空，例如“校区”对应的“校区名称”在目标记录中为空，但存在“学区/区域/城市/门店名称/站点名称/院区名称”等语义相近且有值的字段，必须选择最接近的有值字段继续分析，并在 assumptions 和 direct_answer 中说明替代口径；不要因为首选字段全空直接返回空结果。
30. 如果多个数值字段都可能对应用户说的“次数/数量/金额/达成/执行”等指标，必须阅读 profile.candidate_columns.measure_details 里的 min/max、numeric_nonzero_count、numeric_nonzero_rate、sample_nonzero_values。优先选择语义匹配且有非零证据的字段；如果初选字段全 0 或过滤后全 0，应在代码中检查同表相邻候选指标并改用更能回答问题的非零字段，同时在 assumptions/direct_answer 说明口径选择。不要把全 0 字段的任意对象说成“最高”，除非确认所有相关候选指标都为 0。用户泛称“陈列”时，如果确认金额/核销金额在过滤后全 0 或无法区分，应优先改用陈列执行量、陈列签约金额、陈列单位数、装载数、执行次数等非零陈列执行指标。
31. 生成 rows 前必须保证 DataFrame 的实际列名、rows 的 key、columns 列表和 direct_answer/response_sections 引用的 key 完全一致。如果想把 ctg_name 显示成“品类”、把“本周”显示成“本周OPD”，必须先 rename DataFrame，再 to_dict；不要在 rows 仍是原列名时访问 top['品类'] 或 row['本周OPD']。
32. 明细查询或“列出关键明细”不能返回无限行。默认返回前 100 行关键明细，并在 direct_answer 里说明总命中行数和“仅展示前100行”；除非用户明确要求导出全量，否则不要把全部明细转成 rows。
33. 文本枚举筛选必须先找精确值：如果用户说的品类、客户、商品、城市、人员等值在 Evidence Pack、字段样例或实际列值中存在精确匹配，代码必须优先使用 == 或 isin 做精确匹配；不要用 contains/regex/startswith 把“苏打天然水”这类包含同词的其他枚举也算进去。只有用户明确说“包含/带有/相关/所有含XX”，或精确值不存在但有合理模糊候选时，才允许 contains，并必须在 assumptions/direct_answer 说明这是模糊包含口径。
34. 指标字段必须尊重字段注释的精确口径：如果字段说明里同时存在“分销金额”和“分销金额.T / 含税分销金额 / 净价金额”等相近字段，用户只说“分销金额”时优先选择注释精确等于“分销金额”的字段；只有用户明确说“.T/含税/净价/供价”等限定时，才选择带限定词的字段，并在 semantic_interpretation.metric_formula_or_assumption 中写清楚。
35. 按月筛选日期必须使用半开区间 [月初, 下月初) 或 dt.to_period('M')；不要用 <= 当月最后一天 00:00:00，避免漏掉最后一天带时分秒的记录。
36. 如果用户给出“业务日期/当天/某日”，且时间进度表、目标表或事实表中存在 date_id/date_fmt/sign_time/create_time 等日期字段，必须优先按精确业务日期过滤事实数据；时间进度表应优先用 date_id == YYYYMMDD 或 date_fmt == YYYY-MM-DD，只有没有日级字段时才退回 month_id。事实表的时间字段如果包含时分秒，禁止直接用 df['sign_time'] == 'YYYY-MM-DD'；必须用 pd.to_datetime 后 .dt.date == 目标日期，或使用 [当日00:00, 次日00:00) 半开区间。
37. “当天分销进度/日目标达成/落后/补多少单”这类问题如果依赖当天实际分销、当天已签收订单或当天平均单额，默认只在当天有已签收事实记录且可计算分母的对象中排名；不要让目标表中当天无订单、实际为 0、平均单额为 NaN/0 的对象因为填 0 成为“最落后/需补最多”的答案。用户说“每位业代/各业代”只表示需要逐业代计算，不等于要求把目标表中当天无事实记录的人员纳入排名；只有用户或 guideline 明确说“包括无订单/0销售/无分销/目标表所有人”时，才可以把这些 target-only 对象纳入排名，并必须说明这个口径。可以在 assumptions/direct_answer 中单独说明无当天订单的对象未纳入可估算排名。
38. “约等于多少单/平均每单金额”必须按订单号先汇总订单金额，再按订单求平均；不要用明细行平均冒充订单平均。任何除法或 math.ceil/int/round 前必须先检查分母、结果是否非空且 finite；遇到 NaN/inf/0 分母时返回“无法估算单数”或改用明确说明的总体平均，不得抛 ValueError。
39. 两期增长的“主要由谁贡献”必须计算每个贡献对象的 signed contribution = 本期指标 - 上期指标，再排序；不要用两期合计金额、单期金额或占总额最高者替代增长贡献者。
39a. YYYYMM 月份序列必须用 pd.period_range、pd.date_range(freq='MS') 或 PeriodIndex 生成真实月份；禁止使用 range(202512, 202606) 这类整数递增来生成月份，因为会产生 202513、202514 等无效月份。代码返回 rows 前必须保证月份字段的月份部分在 01-12 之间。
40. merge/join 后如果左右表都有同名列，例如 emp_name、cust_name、ctg_name，Pandas 会生成 _x/_y 后缀；代码必须在 merge 后显式选择、coalesce 或 rename 展示列，不要继续访问不存在的无后缀列名。
41. “高销售低陈列/高陈列低销售/高投入低产出/低投入高产出”这类象限或错配问题，不能只用中位数硬分后回答“未发现”。必须同时计算至少两个指标及其比例/效率，例如 销售金额、陈列执行量、销售/陈列、陈列/销售；即使没有严格落入象限的对象，也要返回最接近的 Top 候选并说明“按效率排名识别候选”。direct_answer 不能只说“未发现”，必须分别点名“高销售低陈列候选”和“高陈列低销售候选”；rows 必须包含 category/候选类型 或 销售陈列效率/陈列销售比例 等可解释列。若用户未指定月份/日期，不要擅自只取最新月；应按全量可用期间或可解释的共同期间聚合。若某个陈列指标在当前过滤后全 0，必须检查并改用非零陈列执行指标，不能用全 0 指标做象限分类。默认图表选择 bar 或 horizontal_bar，不要返回 chart_type="none"。
42. “确认金额/分销金额、陈列费率、投入产出错配风险”默认口径：比例越高代表陈列确认金额相对分销金额越高，更可能是投入偏高或产出不足风险；比例为 0 或很低通常表示陈列投入低，不应直接说成“投入产出风险最高”，除非用户明确问“投入不足/陈列不足”。response_sections 和 direct_answer 必须保持这个方向一致。
43. “有陈列确认金额但历史分销金额较低/历史销售低/产出低”的门店或对象风险问题，默认按 确认金额/历史分销金额 比例从高到低排序；比例最高才是更需要优先检查的候选。不要把比例升序结果说成“风险排序”，除非用户明确要求找比例最低或投入不足对象。
44. 如果用户问题没有明确时间范围，不要为了减少数据量默认选择最新月、最近一天或任意单月；应使用全量数据或所有相关表可对齐的共同时间范围，并在 assumptions 说明。如果必须选择代表性期间，必须说明选择原因，且不能选择会让关键指标全 0、无法回答问题的期间。
45. 如果用户明确要求“门店TopN/站点TopN/院区TopN/校区TopN/客户TopN”，不能擅自降级成城市、区域或学区聚合。首选对应名称字段；名称字段全空时，寻找对应编码/ID/记录主体字段作为替代并说明；只有确实没有任何同粒度字段时才返回可诊断说明。不要把“门店”改成“城市”后继续声称回答了门店TopN。
46. 如果用户点名的指标字段或对象粒度字段存在但全为空（例如 PSD_row/UPT_row/AT_row 或 门店名称 全为空），不要用销售额、城市汇总或其他未授权口径硬替代。除非 guideline 明确给出可推导公式且所需分母/对象粒度字段都可用，否则应返回“无法安全计算”的字段级诊断，而不是返回空 rows 或错误 TopN。诊断 rows 建议包含 requested_metric、requested_dimension、blocking_field、evidence、status、next_step；direct_answer 第一屏必须说明缺少哪个字段、候选字段是什么、为什么不能安全计算。
47. 如果数据中存在“是否本周/上周”、周标签、周序号等明确业务周期字段，回答“本周/上周/上上周”优先使用这些业务周期字段；不要自行用最大日期向前推 ISO 周，除非没有任何周标签/周序号字段。

用户问题：
{question}

对话历史：
{history_context}

业务口径 / guideline（高优先级，优先于默认规则）：
{business_guidelines}

字段 profile：
{profile_json}

Evidence Pack：
{evidence_pack_json}

文件内容摘要与代表性样本：
{file_context}
"""


def build_repair_prompt(original_prompt: str, previous_raw: str, previous_code: str, error: str) -> str:
    return f"""{original_prompt}

上一次生成失败。请根据失败点重新生成一次完整 JSON 对象。
上一段 pandas_code 视为无效草稿；不要只做文字解释，必须重写 pandas_code，并确保新代码直接修复失败点。

失败点：
{error}

上一次 LLM 原始输出：
{previous_raw}

上一次 pandas_code：
{previous_code}

修复要求：
1. 只输出一个 JSON 对象，不要输出 markdown。
2. 必须保留 data_brief、semantic_interpretation、intent、assumptions、response_sections、chart_spec、pandas_code、expected_output。
3. expected_output 必须是短字符串，只描述输出形态，不要放 rows、columns、示例表格或嵌套对象。
4. pandas_code 必须按原 prompt 定义 analyze(df) 或 analyze(tables) -> dict，并返回 direct_answer、rows、columns。
5. rows 必须是 list[dict]，不要返回行数、列数、字符串或单个数字；columns 必须是列名列表。
6. 可以按需 import 常见分析库，例如 pandas、numpy、math、datetime、re、dateutil、calendar。
7. 禁止使用 open、eval、exec、__import__、os、sys、subprocess、socket、pathlib、shutil。
8. 不要读写文件、不要访问网络、不要调用 shell。
9. 只使用 df、pd 和普通 Python 内置函数完成分析。
10. 如果失败点是 LLM verifier，必须修正 semantic_interpretation 和 pandas_code，使用户问题、上下文继承、代码、结果形状和回答语义一致。
10a. 修复时必须重新阅读原 prompt 中的“业务口径 / guideline”和用户问题里的“口径提示/答案格式”；如果它们和默认防错规则冲突，优先遵守用户口径和 guideline，不要为了通过某条默认规则牺牲业务口径。
11. 如果需要图表，chart_spec 的 x/y 必须引用 analyze() 返回 rows/columns 中存在的列；不要把图表数据写死在 chart_spec 里。
12. 如果失败点是 TopN 变化问题返回空 rows，不要简单回答“没有增长/没有下降”。应计算所有对象的 signed change/gap 并按问题方向处理：增加/增长优先返回 change > 0，减少/下降优先返回 change < 0。符合方向的对象不足 N 时要说明不足；没有符合方向对象时可以给最接近候选，但必须标注为“非实际增长/非实际下降候选”，不得把反方向值混入增长/下降排名。
13. 修复代码时必须删除所有未保护的 rows[0]、rows[-1]、iloc[0]、max/min 访问；先判断 DataFrame 或 rows 是否为空，再构造 response_sections。
14. 如果失败点是两期对比后没有共同对象，先判断指标类型。金额、收入、销量、订单数、客户数等可加总指标可改为 outer join 或 pivot_table(fill_value=0) 并说明缺失按0；率、均值、得分、客单价、人均/单均指标、PSD/UPT/AT/HW/RSI/AWT/ASP 等非可加总指标不能用缺失填0制造下降/上升，应只保留两期都有事实记录且分母有效的对象，或输出可诊断说明。
15. 如果上一段代码包含 pd.merge(..., how='inner') 且用户问题是周期对比/变化 TopN，不要机械改成 outer。对可加总指标可用 outer + fillna(0)；对非可加总指标必须保持共同对象比较，并防止 0 分母、NaN、缺失周期被当成真实变化。
16. 如果失败点或上一段代码出现“同时有本周和上周/共同对象/inner join/rows为空/未返回TopN”，新的 pandas_code 必须重新检查时间字段、对象维度和指标口径；可加总指标优先对象并集，非可加总指标优先有效共同对象。不得为了凑 TopN 把缺失事实填 0 后当成下降/减少。
17. 如果失败点是占位符值不存在，例如“项目类别A/客户A/XX”过滤后为空，必须改为从该字段真实取值中选择一个存在的代表值，或使用口径提示中给出的可替换值；不要继续过滤不存在的占位符。
18. 如果失败点是维度字段全为空或缺失，例如“校区名称字段全部为空”，必须选择语义最接近且非空的替代字段继续分析，如学区/区域/城市/门店名称/站点名称/院区名称，并在 assumptions 中记录替代关系。
19. 如果失败点是“结果全 0 / 最高为 0 / 指标口径可能选错”，必须重新查看 candidate_columns.measure_details，检查同表语义相近的数值候选字段；优先使用过滤后有非零值、且字段名/样例更贴近用户问题的指标。不要继续用全 0 字段输出误导性 Top1。用户泛称“陈列”时，确认金额全 0 就改用陈列执行量、签约金额、单位数、装载数或执行次数等非零陈列执行指标。
20. 如果失败点是 KeyError，且 key 是你自己创造的中文展示列名或派生列名，必须把 DataFrame rename 到该展示列名后再 to_dict，或改用 rows 里真实存在的 key；columns、rows、direct_answer 三者必须一致。
20a. 如果失败点是 KeyError，且 key 看起来是业务字段名，必须回到原 prompt 的字段 profile、Evidence Pack 和文件样本核对真实列名；不得继续访问缺失列。若当前表没有该字段或用户点名的枚举值，必须换到包含该字段或枚举值的真实表，或改用同表真实存在且语义等价的字段，并在 assumptions/direct_answer 说明替代口径。代码中访问字段前要用 columns 判断并给出可读诊断，不能再次抛 KeyError。
21. 如果失败点是 timeout 且问题要求明细，必须限制 rows 数量，例如 head(100)，同时保留总笔数、总金额或聚合结果；不要把全部明细转成 JSON。
22. 如果上一段代码用 contains/regex/startswith 筛选用户给出的文本枚举值，但 Evidence Pack、样例或实际列值中存在精确匹配，必须改为 == 或 isin 精确匹配；只有用户明确要求“包含/带有/相关”才保留模糊包含。
23. 如果上一段代码选择了带“.T/含税/净价/供价”等限定的金额字段，而用户只问普通“金额/分销金额/销售额”，必须重新按字段注释选择精确匹配的普通金额字段；除非用户明确要求限定口径。
24. 如果上一段代码用 <= 当月最后一天筛选月份，必须改为 [月初, 下月初) 或 dt.to_period('M')。
25. 如果上一段代码在业务日期问题中只按 month_id 取时间进度，必须改为优先按 date_id/date_fmt 精确业务日期取数；事实表也必须按该业务日期过滤。如果上一段代码用 df['sign_time'] == 'YYYY-MM-DD' 直接比较时间戳字符串，必须改成 pd.to_datetime 后 .dt.date 比较或 [当日00:00, 次日00:00) 半开区间。
26. 如果上一段代码把无当天已签收事实、平均单额为 NaN/0 的对象填 0 后纳入“进度最落后/补单估算”排名，必须改为仅对有当天事实且分母可计算的对象排名，并把无法估算对象放入说明而不是作为第一名。用户说“每位业代/各业代”不等于要求包含目标表中当天无事实记录的人员；只有明确说“包括无订单/0销售/无分销/目标表所有人”才纳入 target-only 对象。
27. 如果失败点包含 cannot convert float NaN to integer、NaN、inf、division by zero，必须在所有 math.ceil/int/round 前检查 pd.notna、np.isfinite 和分母 > 0；无法估算时返回可读诊断，不要抛异常。
28. 如果问题问“增长主要由哪位/哪个对象贡献”，必须按贡献对象分别计算本期 - 上期的增长贡献并排序，不要按两期合计金额或本期单期金额排序。
28a. YYYYMM 月份序列必须用 pd.period_range、pd.date_range(freq='MS') 或 PeriodIndex 生成真实月份；禁止使用 range(202512, 202606) 这类整数递增来生成月份，因为会产生 202513、202514 等无效月份。修复后要过滤或重建无效月份。
29. 如果失败点是 KeyError 且上一段代码刚做过 merge/join，必须检查是否因为左右表同名列被 Pandas 改成 _x/_y 后缀；新代码要在 merge 后显式生成展示列，例如 emp_name = emp_name_x.combine_first(emp_name_y)，或在 merge 前只保留一个名称列。
30. 如果失败点涉及“高销售低陈列/高陈列低销售/高投入低产出/低投入高产出”，新代码必须返回效率或比例排名候选，不得继续回答“未发现”；如果严格象限为空，也要给出最接近候选和判断口径。direct_answer 必须分别点名两类候选，rows 必须包含候选类型或效率/比例解释列。不得在用户未指定时间时只取最新月；不得用过滤后全 0 的陈列指标继续分类，必须改用非零陈列执行指标或全量可用期间。
31. 如果失败点涉及“确认金额/分销金额、陈列费率、投入产出错配风险”，必须把高比例解释为投入偏高或产出不足风险，把低比例解释为投入低或陈列不足；不得把 0 或低比例直接说成投入产出风险最高。
32. 如果失败点涉及“有陈列确认金额但历史分销金额较低/历史销售低/产出低”，必须按确认金额/历史分销金额比例降序返回候选；不得继续使用升序排序把低风险对象排在最前。
33. 如果失败点显示“无明确时间却取了最新月/某月导致关键指标全 0 或无法区分类别”，必须改为全量可用期间或共同期间聚合，并在 assumptions 中说明时间口径。
34. 如果失败点显示用户要求门店/站点/院区/校区/客户 TopN，但上一段代码按城市/区域/学区等更粗维度聚合，必须改回用户要求的对象粒度；名称字段全空时用对应 ID/编码替代并说明，不得继续用粗维度冒充。
35. 如果失败点显示 PSD_row/UPT_row/AT_row、门店名称或用户点名字段全为空，不得继续用销售额或城市汇总近似。若没有 guideline 明确公式和可用分母/对象粒度字段，必须返回字段级诊断 rows，说明 blocking_field、空值证据、候选字段和下一步需要补充的数据；这不是要硬算答案，而是要告诉用户为什么无法计算。
36. 如果失败点显示“本周/上周无数据”但数据有“是否本周/上周”、周标签或周序号字段，必须优先改用这些业务周期字段，不得继续用最大日期推导周。
"""


def _analyze_contract(dataset: CsvDataset) -> str:
    if len(dataset.tables) > 1:
        guideline_tables = _guideline_table_names(dataset)
        business_tables = [name for name in dataset.tables if name not in set(guideline_tables)]
        table_names = ", ".join(f"tables['{name}']" for name in dataset.tables)
        business_table_names = ", ".join(f"tables['{name}']" for name in business_tables) or "无"
        guideline_table_names = ", ".join(f"tables['{name}']" for name in guideline_tables) or "无"
        return (
            "pandas_code 必须定义函数 analyze(tables) -> dict。"
            f"tables 是 dict，可用表包括：{table_names}。"
            f"业务数据表包括：{business_table_names}。"
            f"口径/规则/说明表包括：{guideline_table_names}。"
            "你必须自己决定是否 merge/join、用哪个 key、如何聚合。"
            "普通数据分析只能聚合、筛选、join 业务数据表；口径/规则/说明表只能用于理解字段含义、业务规则、答案格式和计算口径。"
            "除非用户明确询问规则文件、字段说明或示例问题本身，否则不要把口径/规则/说明表当作事实数据参与 join、groupby、sum/count。"
        )
    return "pandas_code 必须定义函数 analyze(df) -> dict。"


def _file_context(dataset: CsvDataset, question: str | None = None) -> str:
    if len(dataset.tables) <= 1:
        return _limit_text(dataset.csv_text, PROMPT_FILE_CONTEXT_LIMIT)
    parts: list[str] = ["多文件数据集。后端会把每个文件或 sheet 作为 tables[表名] 传入 analyze(tables)。"]
    relevant_tables = set(_relevant_table_names(dataset, question or "", overview=False))
    for table_name, context_text in dataset.csv_texts.items():
        table_limit = PROMPT_TABLE_CONTEXT_LIMIT if table_name in relevant_tables else 420
        parts.append(f"引用方式: tables['{table_name}']\n{_limit_text(context_text, table_limit)}")
    return _limit_text("\n\n---\n\n".join(parts), PROMPT_FILE_CONTEXT_LIMIT)


def _compact_profile_for_prompt(dataset: CsvDataset, question: str | None = None, overview: bool = False) -> dict[str, Any]:
    profile = dataset.profile
    tables = []
    relevant_tables = set(_relevant_table_names(dataset, question or "", overview=overview))
    for entry in profile.get("tables", []):
        table_name = str(entry.get("table_name") or "")
        table_profile = dataset.profiles_by_table.get(table_name) or profile.get("tables_by_name", {}).get(table_name, entry)
        role = _table_role(table_name, dataset.csv_texts.get(table_name, ""))
        tables.append(_compact_table_profile(table_name, table_profile, entry, role, detailed=overview or table_name in relevant_tables))
    if not tables and dataset.profiles_by_table:
        for table_name, table_profile in dataset.profiles_by_table.items():
            role = _table_role(table_name, dataset.csv_texts.get(table_name, ""))
            tables.append(_compact_table_profile(table_name, table_profile, table_profile, role, detailed=overview or table_name in relevant_tables))
    guideline_tables = [table["table_name"] for table in tables if table.get("table_role") == "guideline"]
    business_tables = [table["table_name"] for table in tables if table.get("table_role") == "business_data"]
    return {
        "dataset_id": dataset.dataset_id,
        "dataset_kind": profile.get("dataset_kind"),
        "table_count": len(tables),
        "business_data_tables": business_tables,
        "guideline_tables": guideline_tables,
        "table_role_policy": (
            "business_data tables may be filtered, grouped, joined and aggregated; "
            "guideline tables are rule/metadata context and must not be treated as fact data unless the user explicitly asks about rules"
        ),
        "prompt_context_policy": (
            "compact schema/profile for LLM prompt; stored DataFrames are complete at execution time; "
            "row samples are representative, not full data unless table is tiny"
        ),
        "column_key_legend": "n=name, t=dtype; candidate_columns are evidence hints only, not business conclusions",
        "tables": tables,
    }


def _compact_table_profile(
    table_name: str,
    table_profile: dict[str, Any],
    entry: dict[str, Any],
    table_role: str,
    *,
    detailed: bool = True,
) -> dict[str, Any]:
    columns = table_profile.get("columns", [])
    payload = {
        "table_name": table_name,
        "table_role": table_role,
        "original_filename": entry.get("original_filename") or table_profile.get("original_filename"),
        "workbook_name": table_profile.get("workbook_name"),
        "sheet_name": table_profile.get("sheet_name"),
        "row_count": table_profile.get("row_count"),
        "column_count": table_profile.get("column_count"),
        "llm_context_mode": table_profile.get("llm_context_mode"),
        "columns": [{"n": column.get("name"), "t": column.get("dtype")} for column in columns],
    }
    if detailed:
        payload["candidate_columns"] = _candidate_columns_for_prompt(columns)
    else:
        payload["context_note"] = "summary_only_for_prompt; full DataFrame and all columns are still available in tables during execution"
    return payload


def _candidate_columns_for_prompt(columns: list[dict[str, Any]]) -> dict[str, list[str]]:
    candidates = {"id": [], "measure": [], "dimension": [], "time": []}
    measure_details: list[dict[str, Any]] = []
    for column in columns:
        name = str(column.get("name") or "")
        evidence = column.get("evidence") if isinstance(column.get("evidence"), dict) else {}
        if evidence.get("candidate_id_evidence"):
            candidates["id"].append(name)
        if evidence.get("candidate_measure_evidence"):
            candidates["measure"].append(name)
            if len(measure_details) < PROMPT_MEASURE_DETAIL_LIMIT:
                measure_details.append(_measure_detail_for_prompt(column, evidence))
        if evidence.get("candidate_categorical_evidence"):
            candidates["dimension"].append(name)
        if evidence.get("candidate_time_evidence"):
            candidates["time"].append(name)
    for key in ("id", "measure", "dimension", "time"):
        candidates[key] = candidates[key][:PROMPT_CANDIDATE_COLUMN_LIMIT]
    if measure_details:
        candidates["measure_details"] = measure_details
    return {key: values for key, values in candidates.items() if values}


def _measure_detail_for_prompt(column: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    detail = {
        "n": column.get("name"),
        "t": column.get("dtype"),
        "min": evidence.get("min"),
        "max": evidence.get("max"),
        "null_rate": evidence.get("null_rate"),
        "numeric_nonzero_count": evidence.get("numeric_nonzero_count"),
        "numeric_nonzero_rate": evidence.get("numeric_nonzero_rate"),
        "numeric_zero_rate": evidence.get("numeric_zero_rate"),
        "sample_nonzero_values": (evidence.get("sample_nonzero_values") or [])[:PROMPT_SAMPLE_VALUE_LIMIT],
    }
    return {key: value for key, value in detail.items() if value not in (None, [], "")}


def _compact_evidence_pack_for_prompt(dataset: CsvDataset, question: str | None = None, overview: bool = False) -> dict[str, Any]:
    evidence_pack = dataset.profile.get("evidence_pack", {})
    relation_evidence = evidence_pack.get("relation_evidence") if isinstance(evidence_pack, dict) else []
    guideline_tables = set(_guideline_table_names(dataset))
    business_tables = [name for name in dataset.tables if name not in guideline_tables]
    relevant_tables = set(_relevant_table_names(dataset, question or "", overview=overview))
    filtered_relations = [
        relation
        for relation in (relation_evidence or [])
        if relation.get("left_table") not in guideline_tables and relation.get("right_table") not in guideline_tables
    ]
    return {
        "dataset_id": dataset.dataset_id,
        "evidence_policy": "facts_and_candidate_evidence_only_no_business_conclusions",
        "business_data_tables": business_tables,
        "guideline_tables": list(guideline_tables),
        "table_role_policy": "relation evidence excludes guideline tables; guideline tables provide rule context, not fact joins.",
        "tables": [
            {
                "table_name": table_name,
                "table_role": "guideline" if table_name in guideline_tables else "business_data",
                "row_count": int(len(df)),
                "column_count": int(len(df.columns)),
                **(
                    {
                        "head_rows": _limit_rows(df.head(PROMPT_PROFILE_ROW_LIMIT).to_dict(orient="records"), PROMPT_PROFILE_ROW_LIMIT),
                        "random_sample_rows": _limit_rows(
                            df.sample(n=min(PROMPT_PROFILE_ROW_LIMIT, len(df)), random_state=0).to_dict(orient="records")
                            if len(df)
                            else [],
                            PROMPT_PROFILE_ROW_LIMIT,
                        ),
                    }
                    if overview or table_name in relevant_tables
                    else {"sample_note": "omitted_from_prompt_for_speed; full DataFrame remains available"}
                ),
            }
            for table_name, df in dataset.tables.items()
        ],
        "relation_evidence": filtered_relations[:PROMPT_RELATION_LIMIT],
        "relation_evidence_note": "candidate relations only; LLM must decide whether a join is needed and code must use real table/column names.",
    }


def _relevant_table_names(dataset: CsvDataset, question: str, *, overview: bool) -> list[str]:
    if overview or not question or len(dataset.tables) <= 1:
        return list(dataset.tables)
    guideline_tables = set(_guideline_table_names(dataset))
    question_text = question.lower()
    scored: list[tuple[int, str]] = []
    for table_name, df in dataset.tables.items():
        if table_name in guideline_tables:
            scored.append((2, table_name))
            continue
        score = 0
        lowered_name = table_name.lower()
        if lowered_name and lowered_name in question_text:
            score += 8
        context = dataset.csv_texts.get(table_name, "")
        profile = dataset.profiles_by_table.get(table_name, {})
        column_names = [str(column.get("name") or "") for column in profile.get("columns", [])]
        for token in _question_terms(question):
            if token in lowered_name:
                score += 4
            if any(token in column.lower() for column in column_names):
                score += 3
            if token in context.lower()[:4000]:
                score += 2
        if score:
            scored.append((score, table_name))
    scored.sort(key=lambda item: (-item[0], item[1]))
    selected = [name for _, name in scored[:6]]
    for name in dataset.tables:
        if name in guideline_tables and name not in selected:
            selected.append(name)
    return selected or list(dataset.tables)[:6]


def _question_terms(question: str) -> list[str]:
    chunks = re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d{4,8}|[\u4e00-\u9fff]{2,}", question.lower())
    terms: list[str] = []
    for chunk in chunks:
        if len(chunk) <= 1:
            continue
        terms.append(chunk)
        if re.search(r"[\u4e00-\u9fff]", chunk) and len(chunk) > 3:
            for size in (2, 3, 4):
                terms.extend(chunk[index : index + size] for index in range(0, len(chunk) - size + 1))
    stop_terms = {"什么", "多少", "如何", "一下", "这些", "文件", "展示", "分析", "每月", "分别", "是否", "一个"}
    output: list[str] = []
    for term in terms:
        if term in stop_terms or term in output:
            continue
        output.append(term)
    return output[:80]


def _business_guidelines_for_prompt(dataset: CsvDataset, question: str) -> str:
    parts: list[str] = []
    if "口径提示" in question or "答案格式" in question:
        parts.append(f"用户问题内置口径:\n{question}")

    guideline_table_names = _guideline_table_names(dataset)
    for table_name in guideline_table_names:
        context = dataset.csv_texts.get(table_name, "")
        if not context:
            continue
        parts.append(f"上传文件 guideline 表: {table_name}\n{context}")

    if not parts:
        return "无明确上传 guideline；按用户问题、字段 profile、Evidence Pack 和对话历史判断。"
    return _limit_text("\n\n---\n\n".join(parts), PROMPT_GUIDELINE_LIMIT)


def _guideline_table_names(dataset: CsvDataset) -> list[str]:
    return [
        name
        for name in dataset.tables
        if _table_role(name, dataset.csv_texts.get(name, "")) == "guideline"
    ]


def _table_role(table_name: str, context: str) -> str:
    if _looks_like_guideline_table_name(table_name) or _table_context_has_guideline(context):
        return "guideline"
    return "business_data"


def _looks_like_guideline_table_name(table_name: str) -> bool:
    lowered = table_name.lower()
    guideline_keywords = [
        "说明",
        "示例",
        "规则",
        "口径",
        "字典",
        "字段",
        "guideline",
        "doc_",
        "readme",
        "metadata",
    ]
    return any(keyword in lowered for keyword in guideline_keywords)


def _table_context_has_guideline(context: str) -> bool:
    if not context:
        return False
    guideline_keywords = [
        "口径提示",
        "考核口径",
        "业务口径",
        "适用场景",
        "答案格式",
        "财年定义",
        "核心提取规则",
        "SQL构建规则",
        "字段说明",
        "数据表说明",
        "文档/规则文件",
        "严禁",
    ]
    return any(keyword in context for keyword in guideline_keywords)


def _limit_rows(rows: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    limited: list[dict[str, Any]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        compact_row: dict[str, Any] = {}
        items = list(row.items())
        for key, value in items[:PROMPT_SAMPLE_COLUMN_LIMIT]:
            compact_row[str(key)] = _json_prompt_safe(value)
        if len(items) > PROMPT_SAMPLE_COLUMN_LIMIT:
            compact_row["__truncated_columns__"] = len(items) - PROMPT_SAMPLE_COLUMN_LIMIT
        limited.append(compact_row)
    return limited


def _limit_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = text[: int(limit * 0.7)]
    tail = text[-int(limit * 0.3):]
    omitted = len(text) - len(head) - len(tail)
    return (
        f"{head}\n\n"
        f"...[prompt context truncated by backend: {omitted} characters omitted; full DataFrame is available during Pandas execution]...\n\n"
        f"{tail}"
    )


def _json_prompt_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def _history_context(history: list[dict[str, Any]]) -> str:
    if not history:
        return "无。"
    parts: list[str] = []
    for index, turn in enumerate(history[-8:], start=1):
        question = str(turn.get("question") or "")
        answer = str(turn.get("direct_answer") or "")
        intent = str(turn.get("intent") or "")
        columns = turn.get("columns") or []
        rows = turn.get("rows") or []
        code = str(turn.get("pandas_code") or "")
        parts.append(
            "\n".join(
                [
                    f"第 {index} 轮用户问题: {question}",
                    f"第 {index} 轮系统意图: {intent}",
                    f"第 {index} 轮系统回答: {answer}",
                    f"第 {index} 轮结果列: {json.dumps(columns, ensure_ascii=False)}",
                    f"第 {index} 轮结果样例: {json.dumps(rows[:5] if isinstance(rows, list) else [], ensure_ascii=False)}",
                    f"第 {index} 轮生成代码摘要: {code[:1200]}",
                ]
            )
        )
    return "\n\n".join(parts)


def normalize_response_sections(sections: Any, execution: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(sections, dict):
        sections = {}
    direct_answer = str(execution.get("direct_answer") or "").strip()
    rows = execution.get("rows") or []
    columns = execution.get("columns") or []
    normalized = {
        "result_summary": str(sections.get("result_summary") or direct_answer or "已完成分析。"),
        "analysis": _section_list(sections.get("analysis")),
        "insights": _section_list(sections.get("insights")),
        "next_steps": _section_list(sections.get("next_steps")),
    }
    if not normalized["analysis"]:
        normalized["analysis"] = [
            f"本次结果返回 {len(rows)} 行、{len(columns)} 列，表格字段为：{', '.join(str(column) for column in columns[:8]) or '无'}。",
            "数值结论来自本次 Pandas 执行结果，未直接采用 LLM 心算数字。",
        ]
    if not normalized["insights"]:
        normalized["insights"] = ["可以继续围绕排名、趋势、占比、差距或异常点追问。"]
    if not normalized["next_steps"]:
        normalized["next_steps"] = ["继续下钻 Top 项的时间变化。", "对比关键对象之间的差距或占比。"]
    return normalized


def generate_result_response_sections(
    *,
    dataset: CsvDataset,
    question: str,
    conversation_history: list[dict[str, Any]],
    llm_payload: dict[str, Any],
    execution: dict[str, Any],
    chart: dict[str, Any],
    fallback_sections: dict[str, Any],
    llm_client: LlmClient,
) -> dict[str, Any]:
    prompt = build_result_sections_prompt(
        dataset=dataset,
        question=question,
        conversation_history=conversation_history,
        llm_payload=llm_payload,
        execution=execution,
        chart=chart,
        fallback_sections=fallback_sections,
    )
    try:
        section_client = _llm_client_with_timeout(
            llm_client,
            int(os.getenv("VDS_LITE_RESPONSE_LLM_TIMEOUT_SECONDS", "20")),
        )
        raw = section_client.complete(prompt)
        payload = parse_json_object(raw)
    except Exception:
        return fallback_sections
    if "pandas_code" in payload or "chart_spec" in payload:
        return fallback_sections
    sections = payload.get("response_sections") if isinstance(payload.get("response_sections"), dict) else payload
    return normalize_response_sections(sections, execution)


def _llm_client_with_timeout(llm_client: LlmClient, timeout_seconds: int) -> LlmClient:
    if timeout_seconds <= 0:
        return llm_client
    if is_dataclass(llm_client) and hasattr(llm_client, "timeout_seconds"):
        try:
            return replace(llm_client, timeout_seconds=timeout_seconds)
        except Exception:
            return llm_client
    return llm_client


def build_result_sections_prompt(
    *,
    dataset: CsvDataset,
    question: str,
    conversation_history: list[dict[str, Any]],
    llm_payload: dict[str, Any],
    execution: dict[str, Any],
    chart: dict[str, Any],
    fallback_sections: dict[str, Any],
) -> str:
    result_context = {
        "direct_answer": execution.get("direct_answer"),
        "columns": execution.get("columns") or [],
        "rows_sample": (execution.get("rows") or [])[:30],
        "row_count": len(execution.get("rows") or []),
        "chart": {
            "chart_type": chart.get("chart_type"),
            "title": chart.get("title"),
            "x": chart.get("x"),
            "y": chart.get("y"),
            "reason": chart.get("reason"),
        },
        "semantic_interpretation": llm_payload.get("semantic_interpretation"),
        "assumptions": llm_payload.get("assumptions"),
        "fallback_sections": fallback_sections,
    }
    profile_context = {
        "dataset_id": dataset.dataset_id,
        "tables": [
            {
                "table_name": table.get("table_name"),
                "table_role": table.get("table_role"),
                "row_count": table.get("row_count"),
                "column_count": table.get("column_count"),
                "candidate_columns": table.get("candidate_columns"),
            }
            for table in _compact_profile_for_prompt(dataset, question=question).get("tables", [])[:12]
        ],
    }
    history_context = _history_context(conversation_history[-4:])
    return f"""你是 VDS Lite 的结果解读器。你不写代码、不重新计算、不改数字；你的任务是基于已经执行完成的 Pandas 结果，写出更像资深数据分析师的用户可见说明。

硬约束：
1. 只输出 JSON 对象，不要 markdown。
2. JSON 必须只有 result_summary、analysis、insights、next_steps 四个字段。
3. result_summary 第一屏先给直接结论，不要重复“已完成分析”。
4. analysis 写清楚用了什么口径、筛选、聚合、排序或图表编码，但不要泛泛描述。
5. insights 必须从真实 rows_sample、direct_answer、图表和问题中提炼，点名关键对象、峰值、低谷、差距、异常或趋势；不能写“可观察趋势”这种空话。
6. next_steps 给 2-4 个自然追问，必须贴合当前结果中的对象、时间、指标或异常点。
7. 不允许编造 rows_sample 中没有的数字；如果需要提到数字，只能使用 result_context 中已有数字。

用户问题：
{question}

对话历史：
{history_context}

执行结果和现有说明：
{json.dumps(result_context, ensure_ascii=False, indent=2)}

数据结构摘要：
{json.dumps(profile_context, ensure_ascii=False, indent=2)}
"""


def _section_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return [item for item in value if item not in (None, "")]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def run_llm_semantic_verifier(
    *,
    dataset: CsvDataset,
    question: str,
    conversation_history: list[dict[str, Any]],
    llm_payload: dict[str, Any],
    execution: dict[str, Any],
    pandas_code: str,
    llm_client: LlmClient,
) -> dict[str, Any]:
    prompt = build_verifier_prompt(
        dataset=dataset,
        question=question,
        conversation_history=conversation_history,
        llm_payload=llm_payload,
        execution=execution,
        pandas_code=pandas_code,
    )
    try:
        raw = llm_client.complete(prompt)
        verdict = parse_json_object(raw)
    except Exception as exc:
        return {
            "ok": True,
            "verifier": "llm",
            "checks": [{"name": "llm_semantic_verifier_unavailable", "ok": False}],
            "errors": [],
            "raw": "",
            "warning": f"{type(exc).__name__}: {exc}",
        }
    ok = bool(verdict.get("ok"))
    checks = [
        {
            "name": "llm_semantic_verifier",
            "ok": ok,
            "confidence": verdict.get("confidence"),
            "verdict": verdict.get("verdict") or verdict.get("summary") or "",
        }
    ]
    result = {
        "ok": ok,
        "verifier": "llm",
        "checks": checks,
        "errors": verdict.get("issues") if isinstance(verdict.get("issues"), list) else [],
        "repair_instructions": verdict.get("repair_instructions") or "",
        "raw": raw,
    }
    if not ok:
        issues = result["errors"] or [result["repair_instructions"] or "LLM verifier rejected semantic correctness."]
        raise SemanticSanityError("LLM verifier rejected result: " + json.dumps(issues, ensure_ascii=False))
    return result


def build_verifier_prompt(
    *,
    dataset: CsvDataset,
    question: str,
    conversation_history: list[dict[str, Any]],
    llm_payload: dict[str, Any],
    execution: dict[str, Any],
    pandas_code: str,
) -> str:
    profile_json = json.dumps(_compact_profile_for_prompt(dataset, question=question), ensure_ascii=False, separators=(",", ":"))
    evidence_pack_json = json.dumps(_compact_evidence_pack_for_prompt(dataset, question=question), ensure_ascii=False, separators=(",", ":"))
    business_guidelines = _business_guidelines_for_prompt(dataset=dataset, question=question)
    history_context = _history_context(conversation_history)
    result_json = json.dumps(
        {
            "direct_answer": execution.get("direct_answer"),
            "columns": execution.get("columns"),
            "rows_sample": (execution.get("rows") or [])[:30],
            "row_count": len(execution.get("rows") or []),
        },
        ensure_ascii=False,
        indent=2,
    )
    llm_payload_json = json.dumps(
        {
            "data_brief": llm_payload.get("data_brief"),
            "semantic_interpretation": llm_payload.get("semantic_interpretation"),
            "intent": llm_payload.get("intent"),
            "assumptions": llm_payload.get("assumptions"),
            "expected_output": llm_payload.get("expected_output"),
            "response_sections": llm_payload.get("response_sections"),
            "chart_spec": llm_payload.get("chart_spec"),
        },
        ensure_ascii=False,
        indent=2,
    )
    return f"""你是 VDS Lite 的语义校验器。你不能写代码，也不能重新计算全部数据；你只判断本次 LLM 分析结果是否回答了用户问题。

你必须基于用户问题、对话历史、业务口径 / guideline、字段 profile、Evidence Pack、LLM 的语义理解、生成代码和实际执行结果进行判断。

只输出一个 JSON 对象，不要 markdown。JSON schema:
{{
  "ok": true/false,
  "confidence": 0.0,
  "verdict": "一句话结论",
  "issues": ["如果失败，列出具体失败点"],
  "repair_instructions": "如果失败，给下一次生成代码和语义理解的修复指令"
}}

判断原则：
1. 用户问题和上下文优先。追问、省略问法、这个/它/按时间/按维度/差额/变化率必须结合历史理解。
1a. 用户问题中的“口径提示/答案格式/计算公式”和上传文件中的业务口径、字段说明、数据表说明、问题示例、guideline 优先于默认校验规则。默认规则只在这些高优先级上下文没有明确规定时生效；如果冲突，按用户口径和 guideline 判断。
2. 只要代码执行结果确实回答了问题，就应该 ok=true；不要因为 semantic_interpretation 里 dimension/metric 写了“InvoiceDate（按月）”这类自然语言注释而拒绝。
3. 如果代码执行结果列名是派生字段，例如 Month、Sales、Difference，只要代码来源于真实字段且符合问题，就应该 ok=true。
4. 如果回答对象错了、上下文继承错了、指标错了、过滤条件错了、把明细压成标量、TopN 数量明显不对、趋势/差额/变化率没有计算对应字段，才 ok=false。
5. 安全问题、Python 语法、字段 KeyError、超时已经由执行器处理；你只做语义和回答质量判断。
6. 最终数字以执行结果 rows/direct_answer 为准，不以 LLM 心算为准。
7. 如果用户问“业务日期/当天/某日”的分销进度、日目标达成、落后、补多少单，代码必须按该具体业务日期过滤事实表；如果有 date_id/date_fmt/sign_time 等日级字段，却只按 month_id 或月份粗筛，应 ok=false。若代码出现 df['sign_time'] == 'YYYY-MM-DD'、df["create_time"] == 'YYYY-MM-DD' 这类直接用日期字符串比较可能带时分秒的时间戳字段，也应 ok=false，必须要求改为 pd.to_datetime(...).dt.date 或 [当日00:00, 次日00:00)。
8. 如果问题依赖“当天已签收订单/当天平均每单金额/当天分销进度”，结果第一名不能是被目标表 left join 后填 0、且当天无已签收事实或平均单额不可计算的对象，除非用户明确要求把无订单对象也纳入排名。用户说“每位业代/各业代”只表示逐业代计算，不等于要求包含目标表中当天无事实记录的人员；只有明确说“包括无订单/0销售/无分销/目标表所有人”才可纳入 target-only 对象。看到代码同时存在 how='left'、fillna(0)、按 progress/进度 升序排序，并且 rows_sample 第一行实际金额为 0 或 direct_answer 说进度 0%，应 ok=false，要求先确认事实表日期过滤没有误筛空，再只在有当天事实且分母可计算的对象中排名，或单独说明无订单对象。
9. 如果用户问“约等于多少单/平均每单金额”，而结果没有给出可计算的单数、或用明细行平均替代订单平均、或代码可能对 NaN/inf 做 int/math.ceil，应 ok=false。
10. 如果用户问“两期增长主要由谁贡献”，生成代码必须按贡献对象计算本期 - 上期的 signed contribution；如果代码按两期合计金额或本期单期金额找贡献者，应 ok=false。
11. 如果用户点名的指标或对象粒度字段在 profile / 执行数据中全为空，且没有 guideline 明确可推导公式，返回“无法安全计算”的字段级诊断是正确行为，应 ok=true。诊断结果需要在 direct_answer 或 rows_sample 中说明 blocking_field、空值证据、缺少的对象粒度/指标和 next_step。此时不要要求模型用销售额、城市、区域等未授权口径近似；相反，如果结果用更粗维度或其他指标冒充用户要求的门店/PSD/UPT/AT 等，应 ok=false。

用户问题：
{question}

对话历史：
{history_context}

业务口径 / guideline（高优先级，优先于默认规则）：
{business_guidelines}

字段 profile：
{profile_json}

Evidence Pack：
{evidence_pack_json}

LLM 语义理解与输出计划：
{llm_payload_json}

生成的 pandas_code：
{pandas_code}

Pandas 实际执行结果：
{result_json}
"""


def run_semantic_sanity_checks(
    *,
    dataset: CsvDataset,
    llm_payload: dict[str, Any],
    execution: dict[str, Any] | None,
) -> dict[str, Any]:
    semantic = llm_payload.get("semantic_interpretation") or {}
    if not isinstance(semantic, dict):
        raise SemanticSanityError("semantic sanity check failed: semantic_interpretation must be an object.")
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    if not semantic:
        return {"ok": True, "checks": [{"name": "semantic_interpretation_present", "ok": False}], "errors": []}

    table_columns = _table_columns(dataset)
    target_tables = _target_tables(semantic, dataset)
    for table_name in target_tables:
        if table_name not in table_columns:
            errors.append(f"semantic sanity check failed: target table '{table_name}' does not exist.")

    available_columns = _available_columns(table_columns, target_tables)
    available_column_lookup = {column.lower(): column for column in available_columns}
    formula_missing_refs = _formula_missing_refs(
        str(semantic.get("metric_formula_or_assumption") or ""),
        available_column_lookup,
    )
    metric_refs = _field_names(semantic.get("metric"))
    formula_has_existing_refs = _formula_has_existing_refs(
        str(semantic.get("metric_formula_or_assumption") or ""),
        available_column_lookup,
    )
    for column in metric_refs:
        if column not in available_columns and column.lower() not in available_column_lookup and not formula_has_existing_refs:
            errors.append(f"semantic sanity check failed: metric references missing field '{column}'.")
    for column in formula_missing_refs:
        errors.append(f"semantic sanity check failed: metric formula references missing field '{column}'.")

    for column in _field_names(semantic.get("dimension")):
        if (
            column not in available_columns
            and column.lower() not in available_column_lookup
            and not _dimension_can_be_derived_from_time(column, semantic)
        ):
            errors.append(f"semantic sanity check failed: dimension references missing field '{column}'.")
    for field_name, field_value in {
        "time_field": _field_names(semantic.get("time_field")),
        "filters": _filter_field_refs(semantic.get("filters")),
    }.items():
        for column in field_value:
            if column and column not in available_columns and column.lower() not in available_column_lookup:
                errors.append(
                    f"semantic sanity check failed: {field_name} references missing field '{column}'."
                )

    operation_type = str(semantic.get("operation_type") or "").lower()
    if operation_type == "trend" and not semantic.get("time_field"):
        errors.append("semantic sanity check failed: trend operation requires time_field.")
    if operation_type in {"topn", "group_ranking"} and semantic.get("top_n") and execution is not None:
        if len(execution.get("rows") or []) < min(int(semantic.get("top_n") or 1), 2):
            errors.append("semantic sanity check failed: TopN/ranking result shape is too small.")
    if operation_type in {"detail_lookup", "filter_records"} and execution is not None:
        rows = execution.get("rows") or []
        columns = execution.get("columns") or []
        if len(rows) <= 1 and columns == ["value"]:
            errors.append("semantic sanity check failed: detail lookup appears compressed into a scalar result.")

    for join in _join_path_items(semantic.get("required_join_path")):
        left_table = str(join.get("left_table") or "")
        right_table = str(join.get("right_table") or "")
        left_column = str(join.get("left_column") or "")
        right_column = str(join.get("right_column") or "")
        if left_table and left_table not in table_columns:
            errors.append(f"semantic sanity check failed: join left_table '{left_table}' does not exist.")
        if right_table and right_table not in table_columns:
            errors.append(f"semantic sanity check failed: join right_table '{right_table}' does not exist.")
        if left_table in table_columns and left_column and left_column not in table_columns[left_table]:
            errors.append(f"semantic sanity check failed: join left_column '{left_column}' does not exist.")
        if right_table in table_columns and right_column and right_column not in table_columns[right_table]:
            errors.append(f"semantic sanity check failed: join right_column '{right_column}' does not exist.")
        if left_table and right_table and left_column and right_column:
            relation = _matching_relation(dataset, left_table, left_column, right_table, right_column)
            if relation and relation.get("join_match_ratio", 1.0) < 0.05:
                errors.append("semantic sanity check failed: join match ratio is too low.")

    checks.append({"name": "semantic_fields_exist", "ok": not errors})
    if errors:
        raise SemanticSanityError("; ".join(errors))
    return {"ok": True, "checks": checks, "errors": []}


def _table_columns(dataset: CsvDataset) -> dict[str, set[str]]:
    return {table_name: {str(column) for column in df.columns} for table_name, df in dataset.tables.items()}


def _target_tables(semantic: dict[str, Any], dataset: CsvDataset) -> list[str]:
    raw_tables = semantic.get("target_tables")
    tables: list[str] = []
    if isinstance(raw_tables, list):
        tables.extend(str(table) for table in raw_tables if table)
    target_table = semantic.get("target_table")
    if target_table:
        tables.append(str(target_table))
    if not tables:
        tables = list(dataset.tables)
    return list(dict.fromkeys(tables))


def _available_columns(table_columns: dict[str, set[str]], target_tables: list[str]) -> set[str]:
    columns: set[str] = set()
    for table_name in target_tables:
        columns.update(table_columns.get(table_name, set()))
    return columns


def _filter_field_refs(filters: Any) -> list[str]:
    filter_columns: list[str] = []
    if isinstance(filters, list):
        for item in filters:
            if isinstance(item, dict):
                filter_columns.extend(_field_names(item.get("field") or item.get("column")))
            else:
                filter_columns.extend(_field_names(item))
    elif isinstance(filters, dict):
        filter_columns.extend(_field_names(filters.get("field") or filters.get("column")))
    return filter_columns


def _field_names(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, str) and _looks_like_field_ref(item)]
    if isinstance(value, str) and _looks_like_field_ref(value):
        return [value]
    return []


def _looks_like_field_ref(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if text.lower() in {"none", "null", "n/a", "na", "not_applicable"} or text in {"无", "不适用", "无字段"}:
        return False
    if any(operator in text for operator in (" ", "+", "-", "*", "/", "(", ")")):
        return False
    return True


def _formula_has_existing_refs(formula: str, available_column_lookup: dict[str, str]) -> bool:
    return any(token.lower() in available_column_lookup for token in _identifier_tokens(formula))


def _formula_missing_refs(formula: str, available_column_lookup: dict[str, str]) -> list[str]:
    if not formula:
        return []
    missing: list[str] = []
    for token in _identifier_tokens(formula):
        lowered = token.lower()
        if lowered in _FORMULA_WORDS or lowered in available_column_lookup:
            continue
        if "_" in token or token.endswith("_id"):
            missing.append(token)
    return missing


def _identifier_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text)


_FORMULA_WORDS = {
    "sum",
    "avg",
    "average",
    "mean",
    "count",
    "distinct",
    "total",
    "monthly",
    "daily",
    "weekly",
    "amount",
    "revenue",
    "sales",
    "quantity",
    "price",
    "rate",
    "ratio",
    "change",
    "percent",
}


def _dimension_can_be_derived_from_time(column: str, semantic: dict[str, Any]) -> bool:
    lowered = column.lower()
    time_field = str(semantic.get("time_field") or "").strip()
    time_grain = str(semantic.get("time_grain") or "").strip().lower()
    if not time_field:
        return False
    if time_field.lower() in lowered:
        return True
    normalized = re.sub(r"[（(].*?[）)]", "", lowered).strip()
    if normalized in {"month", "date", "day", "week", "quarter", "year", "period", "time"}:
        return True
    if column.strip() in {"月份", "月", "日期", "日", "周", "季度", "年", "时间"}:
        return True
    return bool(time_grain and normalized == time_grain)


def _join_path_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _matching_relation(
    dataset: CsvDataset,
    left_table: str,
    left_column: str,
    right_table: str,
    right_column: str,
) -> dict[str, Any] | None:
    for relation in dataset.profile.get("evidence_pack", {}).get("relation_evidence", []):
        if (
            relation.get("left_table") == left_table
            and relation.get("left_column") == left_column
            and relation.get("right_table") == right_table
            and relation.get("right_column") == right_column
        ):
            return relation
    return None


def parse_llm_json(llm_raw: str) -> dict[str, Any]:
    payload = parse_json_object(llm_raw)
    if "pandas_code" not in payload:
        raise ValueError("LLM response missing required field: pandas_code.")
    return payload


def parse_json_object(llm_raw: str) -> dict[str, Any]:
    text = llm_raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        repaired_text = repair_common_llm_json_text(text)
        if repaired_text != text:
            try:
                payload = json.loads(repaired_text)
            except json.JSONDecodeError:
                payload = None
            else:
                if not isinstance(payload, dict):
                    raise ValueError("LLM response must be a JSON object.")
                return payload
        try:
            payload = ast.literal_eval(text)
        except (SyntaxError, ValueError) as exc:
            raise ValueError(f"LLM response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("LLM response must be a JSON object.")
    return payload


def repair_common_llm_json_text(text: str) -> str:
    """Repair narrow, common JSON typos without masking arbitrary malformed output."""
    # LLMs sometimes emit filter values like:
    # "value": ["2026-03-01", "2026-04-01)"}]
    # where the inner array is missing its closing bracket before the filter object closes.
    return re.sub(
        r'("value"\s*:\s*\[\s*"[^"\n]+"\s*,\s*"[^"\n]+"\s*)\}',
        r"\1]}",
        text,
    )
