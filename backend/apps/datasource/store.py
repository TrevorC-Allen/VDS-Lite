from __future__ import annotations

import hashlib
import json
import difflib
import re
import warnings
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import pandas as pd


MAX_UPLOAD_BYTES = 256 * 1024 * 1024
FULL_CONTEXT_ROW_LIMIT = 40
HEAD_CONTEXT_ROWS = 12
TAIL_CONTEXT_ROWS = 8
RANDOM_CONTEXT_ROWS = 12
DOCUMENT_EXTENSIONS = {".md", ".markdown", ".txt", ".pdf", ".docx", ".doc", ".pages", ".rtf"}
DOCUMENT_CHUNK_CHARS = 1600
PROFILE_FULL_SCAN_ROW_LIMIT = 5000
PROFILE_SAMPLE_ROWS = 5000
RELATION_VALUE_SAMPLE_LIMIT = 5000
RELATION_COLUMN_LIMIT_PER_TABLE = 24
RELATION_KEY_TOKENS = (
    "id",
    "code",
    "key",
    "no",
    "cust",
    "customer",
    "sku",
    "prod",
    "product",
    "store",
    "shop",
    "route",
    "emp",
    "mgr",
    "org",
    "user",
    "客户",
    "终端",
    "商品",
    "门店",
    "路线",
    "员工",
    "经理",
)


@dataclass(frozen=True)
class CsvDataset:
    dataset_id: str
    original_filename: str
    csv_path: Path
    csv_text: str
    dataframe: pd.DataFrame
    profile: dict[str, Any]
    tables: dict[str, pd.DataFrame]
    csv_texts: dict[str, str]
    profiles_by_table: dict[str, dict[str, Any]]


class CsvDatasetStore:
    def __init__(self, root_dir: Path | str):
        self.root_dir = Path(root_dir)
        self.datasets_dir = self.root_dir / "datasets"
        self.datasets_dir.mkdir(parents=True, exist_ok=True)

    def save_upload(self, file_path: Path | str, original_filename: str | None = None) -> CsvDataset:
        return self.save_uploads([file_path], [original_filename] if original_filename else None)

    def save_uploads(
        self,
        file_paths: list[Path | str],
        original_filenames: list[str | None] | None = None,
    ) -> CsvDataset:
        if not file_paths:
            raise ValueError("At least one CSV file is required.")
        original_filenames = original_filenames or [None] * len(file_paths)
        if len(original_filenames) != len(file_paths):
            raise ValueError("original_filenames must match file_paths length.")

        tables: dict[str, pd.DataFrame] = {}
        csv_texts: dict[str, str] = {}
        stored_csv_texts: dict[str, str] = {}
        profiles_by_table: dict[str, dict[str, Any]] = {}
        original_by_table: dict[str, str] = {}
        source_by_table: dict[str, Path] = {}
        combined_parts: list[str] = []

        dataset_kinds: set[str] = set()
        for index, (file_path, original_filename) in enumerate(zip(file_paths, original_filenames, strict=True)):
            source_path = Path(file_path)
            if source_path.stat().st_size > MAX_UPLOAD_BYTES:
                raise ValueError(f"Upload is too large. Limit is {MAX_UPLOAD_BYTES} bytes.")
            filename = original_filename or source_path.name
            suffix = source_path.suffix.lower()
            if suffix == ".csv":
                dataset_kinds.add("csv")
                table_name = _unique_table_name(_table_name(filename, fallback=f"table_{index + 1}"), tables)
                df, csv_text = _read_source_csv(source_path)
                _add_table(
                    table_name=table_name,
                    df=df,
                    csv_text=csv_text,
                    original_filename=filename,
                    source_path=source_path,
                    tables=tables,
                    csv_texts=csv_texts,
                    stored_csv_texts=stored_csv_texts,
                    profiles_by_table=profiles_by_table,
                    original_by_table=original_by_table,
                    source_by_table=source_by_table,
                    combined_parts=combined_parts,
                )
            elif suffix == ".xlsx":
                dataset_kinds.add("excel")
                workbook = pd.read_excel(source_path, sheet_name=None, engine="openpyxl")
                for sheet_index, (sheet_name, df) in enumerate(workbook.items(), start=1):
                    table_name = _unique_table_name(_table_name(sheet_name, fallback=f"sheet_{sheet_index}"), tables)
                    csv_text = df.to_csv(index=False)
                    _add_table(
                        table_name=table_name,
                        df=df,
                        csv_text=csv_text,
                        original_filename=f"{filename} :: sheet: {sheet_name}",
                        source_path=source_path,
                        tables=tables,
                        csv_texts=csv_texts,
                        stored_csv_texts=stored_csv_texts,
                        profiles_by_table=profiles_by_table,
                        original_by_table=original_by_table,
                        source_by_table=source_by_table,
                        combined_parts=combined_parts,
                        workbook_name=filename,
                        sheet_name=str(sheet_name),
                    )
            elif suffix == ".xls":
                raise ValueError("XLS uploads require xlrd; please save the workbook as .xlsx for this MVP.")
            elif suffix in DOCUMENT_EXTENSIONS:
                dataset_kinds.add("document")
                table_name = _unique_table_name(_table_name(f"doc_{filename}", fallback=f"doc_{index + 1}"), tables)
                df, csv_text = _read_document_table(source_path, filename)
                _add_table(
                    table_name=table_name,
                    df=df,
                    csv_text=csv_text,
                    original_filename=filename,
                    source_path=source_path,
                    tables=tables,
                    csv_texts=csv_texts,
                    stored_csv_texts=stored_csv_texts,
                    profiles_by_table=profiles_by_table,
                    original_by_table=original_by_table,
                    source_by_table=source_by_table,
                    combined_parts=combined_parts,
                )
            else:
                raise ValueError("Supported uploads: CSV, XLSX, MD, TXT, PDF, DOCX, DOC, PAGES, RTF.")

        relation_evidence = build_relation_evidence(tables)
        table_evidence = build_evidence_pack(
            dataset_id="pending",
            tables=tables,
            profiles_by_table=profiles_by_table,
            relation_evidence=relation_evidence,
        )
        combined_text = "\n\n---\n\n".join(combined_parts)
        dataset_id = self._dataset_id(combined_text)
        evidence_pack = dict(table_evidence)
        evidence_pack["dataset_id"] = dataset_id
        dataset_dir = self.datasets_dir / dataset_id
        files_dir = dataset_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)

        table_entries: list[dict[str, Any]] = []
        for table_name, source_path in source_by_table.items():
            stored_name = f"{table_name}.csv"
            stored_path = files_dir / stored_name
            stored_path.write_text(stored_csv_texts[table_name], encoding="utf-8")
            table_entries.append(
                {
                    "table_name": table_name,
                    "original_filename": original_by_table[table_name],
                    "stored_filename": stored_name,
                    **profiles_by_table[table_name],
                }
            )

        if len(tables) == 1:
            first_table = next(iter(tables))
            profile = dict(profiles_by_table[first_table])
            if dataset_kinds == {"excel"}:
                profile["dataset_kind"] = "excel_workbook"
            elif dataset_kinds == {"document"}:
                profile["dataset_kind"] = "document_context"
            else:
                profile["dataset_kind"] = "single_csv"
            profile["table_name"] = first_table
            profile["tables"] = table_entries
            profile["tables_by_name"] = {first_table: profiles_by_table[first_table]}
            profile["evidence_pack"] = evidence_pack
        else:
            if dataset_kinds == {"excel"}:
                dataset_kind = "excel_workbook"
            elif dataset_kinds == {"csv"}:
                dataset_kind = "multi_csv"
            elif dataset_kinds == {"document"}:
                dataset_kind = "document_context"
            else:
                dataset_kind = "multi_file"
            profile = {
                "dataset_kind": dataset_kind,
                "table_count": len(tables),
                "tables": table_entries,
                "tables_by_name": profiles_by_table,
                "evidence_pack": evidence_pack,
            }
        (dataset_dir / "profile.json").write_text(
            json.dumps(profile, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        first_table_name = next(iter(tables))
        return CsvDataset(
            dataset_id=dataset_id,
            original_filename=", ".join(original_by_table.values()),
            csv_path=files_dir / f"{first_table_name}.csv",
            csv_text=combined_text if len(tables) > 1 else csv_texts[first_table_name],
            dataframe=tables[first_table_name],
            profile=profile,
            tables=tables,
            csv_texts=csv_texts,
            profiles_by_table=profiles_by_table,
        )

    def load(self, dataset_id: str) -> CsvDataset:
        dataset_dir = self.datasets_dir / dataset_id
        profile_path = dataset_dir / "profile.json"
        if not profile_path.exists():
            raise KeyError(f"Unknown dataset_id: {dataset_id}")
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        files_dir = dataset_dir / "files"
        tables: dict[str, pd.DataFrame] = {}
        csv_texts: dict[str, str] = {}
        profiles_by_table: dict[str, dict[str, Any]] = {}
        original_names: list[str] = []
        combined_parts: list[str] = []
        for entry in profile.get("tables", []):
            table_name = str(entry["table_name"])
            stored_path = files_dir / str(entry["stored_filename"])
            raw_csv_text = stored_path.read_text(encoding="utf-8-sig")
            original_filename = str(entry.get("original_filename") or stored_path.name)
            original_names.append(original_filename)
            profiles_by_table[table_name] = profile.get("tables_by_name", {}).get(table_name, entry)
            tables[table_name] = _read_stored_table(stored_path, profiles_by_table[table_name])
            workbook_name = profiles_by_table[table_name].get("workbook_name")
            sheet_name = profiles_by_table[table_name].get("sheet_name")
            context_text = _build_table_context(
                table_name=table_name,
                df=tables[table_name],
                profile=profiles_by_table[table_name],
                original_filename=original_filename,
                workbook_name=workbook_name if isinstance(workbook_name, str) else None,
                sheet_name=sheet_name if isinstance(sheet_name, str) else None,
            )
            csv_texts[table_name] = context_text
            combined_parts.append(context_text)
        if not tables:
            raise KeyError(f"Dataset has no stored CSV tables: {dataset_id}")
        first_table_name = next(iter(tables))
        return CsvDataset(
            dataset_id=dataset_id,
            original_filename=", ".join(original_names),
            csv_path=files_dir / f"{first_table_name}.csv",
            csv_text="\n\n---\n\n".join(combined_parts) if len(tables) > 1 else csv_texts[first_table_name],
            dataframe=tables[first_table_name],
            profile=profile,
            tables=tables,
            csv_texts=csv_texts,
            profiles_by_table=profiles_by_table,
        )

    @staticmethod
    def _dataset_id(csv_text: str) -> str:
        digest = hashlib.sha256(csv_text.encode("utf-8")).hexdigest()[:12]
        return f"csv_{digest}_{uuid.uuid4().hex[:8]}"


def build_csv_profile(df: pd.DataFrame, csv_text: str, original_filename: str) -> dict[str, Any]:
    columns: list[dict[str, Any]] = []
    for name in df.columns:
        series = df[name]
        profile_series, profile_is_sampled = _profile_series(series)
        sample_values = [
            _json_safe(value)
            for value in profile_series.dropna().head(5).tolist()
        ]
        missing_rate = float(profile_series.isna().mean()) if len(profile_series) else 0.0
        missing_count = int(series.isna().sum()) if not profile_is_sampled else int(round(missing_rate * len(series)))
        columns.append(
            {
                "name": str(name),
                "dtype": str(series.dtype),
                "missing_count": missing_count,
                "missing_rate": missing_rate,
                "profile_sampled": profile_is_sampled,
                "sample_values": sample_values,
                "evidence": _column_evidence(
                    name=str(name),
                    series=profile_series,
                    total_row_count=len(series),
                    sampled=profile_is_sampled,
                ),
            }
        )
    return {
        "original_filename": original_filename,
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "columns": columns,
        "columns_by_name": {column["name"]: column for column in columns},
        "preview_rows": _records(df.head(20)),
        "csv_char_count": len(csv_text),
        "csv_sha256": hashlib.sha256(csv_text.encode("utf-8")).hexdigest(),
        "llm_context_mode": "full" if len(df) <= FULL_CONTEXT_ROW_LIMIT else "sampled",
    }


def build_evidence_pack(
    *,
    dataset_id: str,
    tables: dict[str, pd.DataFrame],
    profiles_by_table: dict[str, dict[str, Any]],
    relation_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id,
        "tables": [
            {
                "table_name": table_name,
                "original_filename": profiles_by_table[table_name].get("original_filename", ""),
                "workbook_name": profiles_by_table[table_name].get("workbook_name"),
                "sheet_name": profiles_by_table[table_name].get("sheet_name"),
                "row_count": int(len(df)),
                "column_count": int(len(df.columns)),
                "columns": [
                    {
                        "name": column["name"],
                        "dtype": column["dtype"],
                        "sample_values": column["sample_values"],
                        "evidence": column["evidence"],
                    }
                    for column in profiles_by_table[table_name]["columns"]
                ],
                "head_rows": _records(df.head(HEAD_CONTEXT_ROWS)),
                "random_sample_rows": _records(_random_rows(df, RANDOM_CONTEXT_ROWS)),
                "tail_rows": _records(df.tail(TAIL_CONTEXT_ROWS)),
            }
            for table_name, df in tables.items()
        ],
        "relation_evidence": relation_evidence,
        "evidence_policy": "facts_and_candidate_evidence_only_no_business_conclusions",
    }


def build_relation_evidence(tables: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    table_items = list(tables.items())
    relation_columns = {
        table_name: _relation_candidate_columns(df)
        for table_name, df in table_items
    }
    for left_index, (left_name, left_df) in enumerate(table_items):
        for right_name, right_df in table_items[left_index + 1:]:
            for left_column in relation_columns[left_name]:
                for right_column in relation_columns[right_name]:
                    if not _should_compare_relation_columns(str(left_column), str(right_column)):
                        continue
                    relation = _relation_candidate(
                        left_table=left_name,
                        left_df=left_df,
                        left_column=str(left_column),
                        right_table=right_name,
                        right_df=right_df,
                        right_column=str(right_column),
                    )
                    if relation is not None:
                        relations.append(relation)
    return sorted(
        relations,
        key=lambda item: (
            item["value_overlap_ratio"],
            item["name_similarity"],
            item["join_match_ratio"],
        ),
        reverse=True,
    )[:24]


def _relation_candidate_columns(df: pd.DataFrame) -> list[str]:
    scored: list[tuple[int, str]] = []
    for column in df.columns:
        name = str(column)
        lowered = name.lower()
        token_score = 1 if any(token in lowered for token in RELATION_KEY_TOKENS) else 0
        dtype_score = 1 if (
            pd.api.types.is_object_dtype(df[column])
            or pd.api.types.is_integer_dtype(df[column])
            or pd.api.types.is_string_dtype(df[column])
        ) else 0
        score = token_score * 2 + dtype_score
        if score:
            scored.append((score, name))
    if not scored:
        scored = [(1, str(column)) for column in list(df.columns)[:8]]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [name for _, name in scored[:RELATION_COLUMN_LIMIT_PER_TABLE]]


def _should_compare_relation_columns(left_column: str, right_column: str) -> bool:
    left = left_column.lower()
    right = right_column.lower()
    if left == right:
        return True
    if any(token in left and token in right for token in RELATION_KEY_TOKENS):
        return True
    return difflib.SequenceMatcher(None, left, right).ratio() >= 0.45


def _table_name(filename: str, fallback: str) -> str:
    stem = Path(filename).stem or fallback
    cleaned = "".join(char if char.isalnum() else "_" for char in stem.lower()).strip("_")
    return cleaned or fallback


def _unique_table_name(base: str, existing: dict[str, Any]) -> str:
    if base not in existing:
        return base
    index = 2
    while f"{base}_{index}" in existing:
        index += 1
    return f"{base}_{index}"


def _add_table(
    *,
    table_name: str,
    df: pd.DataFrame,
    csv_text: str,
    original_filename: str,
    source_path: Path,
    tables: dict[str, pd.DataFrame],
    csv_texts: dict[str, str],
    stored_csv_texts: dict[str, str],
    profiles_by_table: dict[str, dict[str, Any]],
    original_by_table: dict[str, str],
    source_by_table: dict[str, Path],
    combined_parts: list[str],
    workbook_name: str | None = None,
    sheet_name: str | None = None,
) -> None:
    tables[table_name] = df
    stored_csv_texts[table_name] = csv_text
    original_by_table[table_name] = original_filename
    source_by_table[table_name] = source_path
    profile = build_csv_profile(df=df, csv_text=csv_text, original_filename=original_filename)
    if source_path.suffix.lower() in DOCUMENT_EXTENSIONS:
        profile["source_kind"] = "document_guideline"
    if workbook_name:
        profile["workbook_name"] = workbook_name
    if sheet_name:
        profile["sheet_name"] = sheet_name
    context_text = _build_table_context(
        table_name=table_name,
        df=df,
        profile=profile,
        original_filename=original_filename,
        workbook_name=workbook_name,
        sheet_name=sheet_name,
    )
    csv_texts[table_name] = context_text
    profiles_by_table[table_name] = profile
    combined_parts.append(context_text)


def _build_table_context(
    *,
    table_name: str,
    df: pd.DataFrame,
    profile: dict[str, Any],
    original_filename: str,
    workbook_name: str | None = None,
    sheet_name: str | None = None,
) -> str:
    if workbook_name and sheet_name:
        header = f"工作簿: {workbook_name}\nsheet: {sheet_name}\n表名: {table_name}"
    elif profile.get("source_kind") == "document_guideline":
        header = f"文档/规则文件: {original_filename}\n表名: {table_name}\n用途: 上传文档、规则、口径或说明上下文"
    else:
        header = f"文件名: {original_filename}\n表名: {table_name}"

    summary = (
        f"总行数: {profile['row_count']}\n"
        f"总列数: {profile['column_count']}\n"
        f"上下文模式: {profile['llm_context_mode']}\n"
        f"字段: {', '.join(column['name'] for column in profile['columns'])}"
    )

    if len(df) <= FULL_CONTEXT_ROW_LIMIT:
        sample_block = f"完整内容:\n{df.to_csv(index=False)}"
    else:
        sample_df = _sample_rows_for_context(df)
        sample_block = (
            "代表性样本:\n"
            f"{sample_df.to_csv(index=False)}\n"
            "注意: 上面不是全量行，只包含头部、尾部和随机样本；真正执行时后端会把完整 DataFrame 传给 Pandas。"
        )

    return f"{header}\n{summary}\n{sample_block}"


def _sample_rows_for_context(df: pd.DataFrame) -> pd.DataFrame:
    head = df.head(HEAD_CONTEXT_ROWS)
    tail = df.tail(TAIL_CONTEXT_ROWS)
    middle = df.iloc[HEAD_CONTEXT_ROWS:max(len(df) - TAIL_CONTEXT_ROWS, HEAD_CONTEXT_ROWS)]
    if middle.empty:
        return pd.concat([head, tail]).drop_duplicates().reset_index(drop=True)
    random_rows = middle.sample(n=min(RANDOM_CONTEXT_ROWS, len(middle)), random_state=0)
    return pd.concat([head, random_rows, tail]).drop_duplicates().reset_index(drop=True)


def _random_rows(df: pd.DataFrame, count: int) -> pd.DataFrame:
    if df.empty:
        return df
    return df.sample(n=min(count, len(df)), random_state=0).reset_index(drop=True)


def _profile_series(series: pd.Series) -> tuple[pd.Series, bool]:
    if len(series) <= PROFILE_FULL_SCAN_ROW_LIMIT:
        return series, False
    sample = series.sample(n=min(PROFILE_SAMPLE_ROWS, len(series)), random_state=0)
    return sample.reset_index(drop=True), True


def _column_evidence(
    name: str,
    series: pd.Series,
    *,
    total_row_count: int | None = None,
    sampled: bool = False,
) -> dict[str, Any]:
    non_null = series.dropna()
    distinct_count = int(non_null.nunique(dropna=True))
    row_count = int(total_row_count if total_row_count is not None else len(series))
    sample_row_count = int(len(series))
    uniqueness_ratio = float(distinct_count / len(non_null)) if len(non_null) else 0.0
    repeated_value_count = int(non_null.value_counts().loc[lambda values: values > 1].count()) if len(non_null) else 0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        parsed_datetime = (
            pd.to_datetime(non_null.head(200), errors="coerce")
            if len(non_null)
            else pd.Series(dtype="datetime64[ns]")
        )
    datetime_parse_ratio = float(parsed_datetime.notna().mean()) if len(parsed_datetime) else 0.0
    numeric_series = pd.to_numeric(non_null, errors="coerce")
    numeric_parse_ratio = float(numeric_series.notna().mean()) if len(numeric_series) else 0.0

    min_value: Any = None
    max_value: Any = None
    numeric_nonzero_count: int | None = None
    numeric_zero_count: int | None = None
    numeric_nonzero_rate: float | None = None
    numeric_zero_rate: float | None = None
    sample_nonzero_values: list[Any] = []
    if pd.api.types.is_numeric_dtype(series) or numeric_parse_ratio >= 0.9:
        clean_numeric = numeric_series.dropna()
        if len(clean_numeric):
            min_value = _json_safe(clean_numeric.min())
            max_value = _json_safe(clean_numeric.max())
            nonzero = clean_numeric[clean_numeric != 0]
            zero = clean_numeric[clean_numeric == 0]
            numeric_nonzero_count = int(len(nonzero))
            numeric_zero_count = int(len(zero))
            numeric_nonzero_rate = float(len(nonzero) / len(clean_numeric))
            numeric_zero_rate = float(len(zero) / len(clean_numeric))
            sample_nonzero_values = [_json_safe(value) for value in nonzero.head(5).tolist()]
    elif pd.api.types.is_datetime64_any_dtype(series) or datetime_parse_ratio >= 0.9:
        clean_datetime = parsed_datetime.dropna()
        if len(clean_datetime):
            min_value = _json_safe(clean_datetime.min())
            max_value = _json_safe(clean_datetime.max())

    lowered = name.lower()
    format_hints: list[str] = []
    if datetime_parse_ratio >= 0.8 or pd.api.types.is_datetime64_any_dtype(series):
        format_hints.append("date_like_values")
    if numeric_parse_ratio >= 0.9 or pd.api.types.is_numeric_dtype(series):
        format_hints.append("numeric_like_values")
    if any(token in lowered for token in ("id", "no", "code", "key")):
        format_hints.append("name_contains_id_code_key_hint")
    if 0 < distinct_count <= 30:
        format_hints.append("low_cardinality_values")
    if repeated_value_count:
        format_hints.append("has_repeated_values")

    return {
        "distinct_count": distinct_count,
        "uniqueness_ratio": round(uniqueness_ratio, 6),
        "null_rate": float(series.isna().mean()) if sample_row_count else 0.0,
        "profile_sampled": sampled,
        "profile_sample_rows": sample_row_count,
        "profile_total_rows": row_count,
        "min": min_value,
        "max": max_value,
        "numeric_nonzero_count": numeric_nonzero_count,
        "numeric_zero_count": numeric_zero_count,
        "numeric_nonzero_rate": round(numeric_nonzero_rate, 6) if numeric_nonzero_rate is not None else None,
        "numeric_zero_rate": round(numeric_zero_rate, 6) if numeric_zero_rate is not None else None,
        "sample_nonzero_values": sample_nonzero_values,
        "value_format_hints": format_hints,
        "repeated_value_count": repeated_value_count,
        "candidate_id_evidence": _candidate_id_evidence(lowered, uniqueness_ratio),
        "candidate_measure_evidence": _candidate_measure_evidence(series, numeric_parse_ratio),
        "candidate_categorical_evidence": _candidate_categorical_evidence(series, distinct_count),
        "candidate_time_evidence": _candidate_time_evidence(series, datetime_parse_ratio),
    }


def _candidate_id_evidence(lowered_name: str, uniqueness_ratio: float) -> list[str]:
    evidence: list[str] = []
    if any(token in lowered_name for token in ("id", "no", "code", "key")):
        evidence.append("name_hint_id_no_code_key")
    if uniqueness_ratio >= 0.9:
        evidence.append("high_uniqueness_ratio")
    return evidence


def _candidate_measure_evidence(series: pd.Series, numeric_parse_ratio: float) -> list[str]:
    evidence: list[str] = []
    if pd.api.types.is_numeric_dtype(series) or numeric_parse_ratio >= 0.9:
        evidence.append("numeric")
        evidence.append("can_sum_or_average")
    return evidence


def _candidate_categorical_evidence(series: pd.Series, distinct_count: int) -> list[str]:
    if pd.api.types.is_object_dtype(series) or pd.api.types.is_bool_dtype(series) or distinct_count <= 30:
        return ["can_group_or_filter_by_distinct_values"]
    return []


def _candidate_time_evidence(series: pd.Series, datetime_parse_ratio: float) -> list[str]:
    if pd.api.types.is_datetime64_any_dtype(series) or datetime_parse_ratio >= 0.8:
        return ["date_or_datetime_parse_evidence"]
    return []


def _relation_candidate(
    *,
    left_table: str,
    left_df: pd.DataFrame,
    left_column: str,
    right_table: str,
    right_df: pd.DataFrame,
    right_column: str,
) -> dict[str, Any] | None:
    left_values = _string_values(left_df[left_column])
    right_values = _string_values(right_df[right_column])
    if not left_values or not right_values:
        return None
    left_set = set(left_values)
    right_set = set(right_values)
    overlap = left_set & right_set
    name_similarity = difflib.SequenceMatcher(None, left_column.lower(), right_column.lower()).ratio()
    value_overlap_ratio = len(overlap) / max(1, min(len(left_set), len(right_set)))
    if name_similarity < 0.72 and value_overlap_ratio < 0.1:
        return None
    left_unique_ratio = len(left_set) / max(1, len(left_values))
    right_unique_ratio = len(right_set) / max(1, len(right_values))
    join_match_ratio = sum(1 for value in left_values if value in right_set) / max(1, len(left_values))
    estimated_join_row_count = _estimated_join_row_count(left_values, right_values)
    return {
        "left_table": left_table,
        "left_column": left_column,
        "right_table": right_table,
        "right_column": right_column,
        "name_similarity": round(float(name_similarity), 4),
        "dtype_compatible": _dtype_compatible(left_df[left_column], right_df[right_column]),
        "value_overlap_ratio": round(float(value_overlap_ratio), 6),
        "left_unique_ratio": round(float(left_unique_ratio), 6),
        "right_unique_ratio": round(float(right_unique_ratio), 6),
        "join_match_ratio": round(float(join_match_ratio), 6),
        "estimated_join_row_count": int(estimated_join_row_count),
        "left_row_count": int(len(left_df)),
        "right_row_count": int(len(right_df)),
        "evidence_notes": [
            "candidate_relation_evidence_only",
            "name_similarity_or_value_overlap_observed",
        ],
    }


def _string_values(series: pd.Series, limit: int = RELATION_VALUE_SAMPLE_LIMIT) -> list[str]:
    values = series
    if len(values) > limit:
        values = values.sample(n=limit, random_state=0)
    values = values.dropna()
    return [str(value) for value in values.tolist()]


def _dtype_compatible(left: pd.Series, right: pd.Series) -> bool:
    if pd.api.types.is_numeric_dtype(left) and pd.api.types.is_numeric_dtype(right):
        return True
    if pd.api.types.is_datetime64_any_dtype(left) and pd.api.types.is_datetime64_any_dtype(right):
        return True
    return True


def _estimated_join_row_count(left_values: list[str], right_values: list[str]) -> int:
    right_counts: dict[str, int] = {}
    for value in right_values:
        right_counts[value] = right_counts.get(value, 0) + 1
    return sum(right_counts.get(value, 0) for value in left_values)


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {str(key): _json_safe(value) for key, value in row.items()}
        for row in df.to_dict(orient="records")
    ]


def _read_stored_table(stored_path: Path, profile: dict[str, Any]) -> pd.DataFrame:
    df = pd.read_csv(stored_path)
    for column in profile.get("columns", []):
        name = str(column.get("name") or "")
        dtype = str(column.get("dtype") or "")
        if name in df.columns and dtype.startswith("datetime64"):
            df[name] = pd.to_datetime(df[name], errors="coerce")
    return df


def _read_source_csv(source_path: Path) -> tuple[pd.DataFrame, str]:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin1"):
        try:
            df = pd.read_csv(source_path, encoding=encoding)
            csv_text = source_path.read_text(encoding=encoding)
            return df, csv_text
        except UnicodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    df = pd.read_csv(source_path)
    return df, source_path.read_text(encoding="utf-8-sig")


def _read_document_table(source_path: Path, original_filename: str) -> tuple[pd.DataFrame, str]:
    text = _extract_document_text(source_path)
    cleaned = _normalize_document_text(text)
    if not cleaned:
        cleaned = "未能从该文档中提取可读文本；文件已记录为上传文档。"
    chunks = _chunk_document_text(cleaned)
    df = pd.DataFrame(
        [
            {
                "document_name": original_filename,
                "document_type": source_path.suffix.lower().lstrip(".") or "document",
                "chunk_index": index,
                "text": chunk,
            }
            for index, chunk in enumerate(chunks, start=1)
        ]
    )
    csv_text = df.to_csv(index=False)
    return df, csv_text


def _extract_document_text(source_path: Path) -> str:
    suffix = source_path.suffix.lower()
    if suffix in {".md", ".markdown", ".txt", ".rtf"}:
        return _read_text_file(source_path)
    if suffix == ".docx":
        return _extract_docx_text(source_path)
    if suffix == ".pages":
        return _extract_pages_text(source_path)
    if suffix == ".pdf":
        return _extract_pdf_text(source_path)
    if suffix == ".doc":
        return _extract_binary_text(source_path)
    return ""


def _read_text_file(source_path: Path) -> str:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin1"):
        try:
            return source_path.read_text(encoding=encoding)
        except UnicodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return source_path.read_text(encoding="utf-8-sig")


def _extract_docx_text(source_path: Path) -> str:
    with zipfile.ZipFile(source_path) as archive:
        xml_bytes = archive.read("word/document.xml")
    return _xml_text(xml_bytes)


def _extract_pages_text(source_path: Path) -> str:
    texts: list[str] = []
    with zipfile.ZipFile(source_path) as archive:
        for name in archive.namelist():
            lowered = name.lower()
            if not lowered.endswith((".xml", ".iwa")):
                continue
            if lowered.endswith(".iwa"):
                texts.append(_extract_binary_text_from_bytes(archive.read(name)))
                continue
            try:
                texts.append(_xml_text(archive.read(name)))
            except ElementTree.ParseError:
                texts.append(_extract_binary_text_from_bytes(archive.read(name)))
    return "\n".join(part for part in texts if part.strip())


def _extract_pdf_text(source_path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        return _extract_binary_text(source_path)
    reader = PdfReader(str(source_path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_binary_text(source_path: Path) -> str:
    return _extract_binary_text_from_bytes(source_path.read_bytes())


def _extract_binary_text_from_bytes(data: bytes) -> str:
    decoded = data.decode("utf-8", errors="ignore")
    runs = re.findall(r"[\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9\s,.;:!?()\[\]{}<>/@#%&+=_'\"|\-]{3,}", decoded)
    return "\n".join(run.strip() for run in runs if run.strip())


def _xml_text(xml_bytes: bytes) -> str:
    root = ElementTree.fromstring(xml_bytes)
    return "\n".join(text.strip() for text in root.itertext() if text and text.strip())


def _normalize_document_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in str(text or "").splitlines()]
    return "\n".join(line for line in lines if line)


def _chunk_document_text(text: str) -> list[str]:
    if len(text) <= DOCUMENT_CHUNK_CHARS:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + DOCUMENT_CHUNK_CHARS)
        boundary = text.rfind("\n", start, end)
        if boundary <= start + DOCUMENT_CHUNK_CHARS // 2:
            boundary = end
        chunks.append(text[start:boundary].strip())
        start = boundary
    return [chunk for chunk in chunks if chunk]


def _json_safe(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, pd.Timedelta)):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
