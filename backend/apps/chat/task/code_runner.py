from __future__ import annotations

import ast
import inspect
import multiprocessing as mp
import queue
import re
from typing import Any
from datetime import date, datetime

import pandas as pd


class UnsafeCodeError(ValueError):
    pass


class CodeExecutionError(RuntimeError):
    pass


FORBIDDEN_NAMES = {
    "__import__",
    "compile",
    "eval",
    "exec",
    "globals",
    "input",
    "locals",
    "open",
}
FORBIDDEN_ATTR_ROOTS = {"os", "pathlib", "shutil", "socket", "subprocess", "sys"}
SAFE_IMPORT_ROOTS = {
    "calendar",
    "collections",
    "datetime",
    "dateutil",
    "decimal",
    "math",
    "numpy",
    "pandas",
    "pytz",
    "re",
    "time",
    "zoneinfo",
}


def _safe_import(name: str, globals: Any = None, locals: Any = None, fromlist: tuple[str, ...] = (), level: int = 0) -> Any:
    root = str(name).split(".", 1)[0]
    if root not in SAFE_IMPORT_ROOTS:
        raise ImportError(f"Import is not allowed in generated code: {name}")
    return __import__(name, globals, locals, fromlist, level)


ALLOWED_BUILTINS = {
    "__import__": _safe_import,
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "float": float,
    "int": int,
    "isinstance": isinstance,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "range": range,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
}


def run_pandas_code(
    pandas_code: str,
    df: pd.DataFrame | None,
    timeout_seconds: int = 15,
    tables: dict[str, pd.DataFrame] | None = None,
) -> dict[str, Any]:
    pandas_code = repair_common_llm_code_syntax(pandas_code)
    validate_pandas_code(pandas_code)
    if df is None:
        df = pd.DataFrame()
    copied_tables = {name: table.copy() for name, table in (tables or {}).items()}
    output: mp.Queue = mp.Queue()
    process = mp.Process(target=_worker, args=(pandas_code, df.copy(), copied_tables, output))
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(1)
        raise CodeExecutionError(f"Generated code timed out after {timeout_seconds} seconds.")
    try:
        status, payload = output.get_nowait()
    except queue.Empty as exc:
        raise CodeExecutionError("Generated code did not return a result.") from exc
    if status == "error":
        raise CodeExecutionError(str(payload))
    return normalize_result(payload)


def repair_common_llm_code_syntax(pandas_code: str) -> str:
    """Normalize narrow, common formatting glitches in LLM-generated Python."""

    code = re.sub(r"([A-Za-z_][A-Za-z0-9_]*)\[\\\"([^\"\n]+)\\\"\]", r"\1['\2']", pandas_code)
    code = re.sub(r"([A-Za-z_][A-Za-z0-9_]*)\[\"([^\"\n]+)\"\]", r"\1['\2']", code)
    repaired_lines: list[str] = []
    for line in code.splitlines():
        stripped = line.lstrip(" ")
        leading = len(line) - len(stripped)
        if leading and leading % 4 and stripped:
            leading = ((leading // 4) + 1) * 4
            line = " " * leading + stripped
        repaired_lines.append(line)
    return "\n".join(repaired_lines)


def validate_pandas_code(pandas_code: str) -> None:
    try:
        tree = ast.parse(pandas_code)
    except SyntaxError as exc:
        raise UnsafeCodeError(f"Generated code has invalid Python syntax: {exc}") from exc

    has_analyze = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _validate_import_name(alias.name)
        if isinstance(node, ast.ImportFrom):
            if node.module is None:
                raise UnsafeCodeError("Relative imports are not allowed in generated code.")
            _validate_import_name(node.module)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_NAMES:
                raise UnsafeCodeError(f"Forbidden call in generated code: {node.func.id}")
            if isinstance(node.func, ast.Attribute) and _root_name(node.func) in FORBIDDEN_ATTR_ROOTS:
                raise UnsafeCodeError(f"Forbidden module access in generated code: {_root_name(node.func)}")
        if isinstance(node, ast.FunctionDef) and node.name == "analyze":
            has_analyze = True
        if isinstance(node, ast.Name) and node.id in {"__import__", "compile", "eval", "exec", "open", "os", "sys", "subprocess", "socket"}:
            raise UnsafeCodeError(f"Forbidden name in generated code: {node.id}")
    if not has_analyze:
        raise UnsafeCodeError("Generated code must define analyze(df).")


def _validate_import_name(name: str) -> None:
    root = str(name).split(".", 1)[0]
    if root not in SAFE_IMPORT_ROOTS:
        raise UnsafeCodeError(f"Import is not allowed in generated code: {name}")


def normalize_result(result: Any) -> dict[str, Any]:
    if isinstance(result, pd.DataFrame):
        rows = result.to_dict(orient="records")
        return {"direct_answer": "", "rows": _json_rows(rows), "columns": [str(c) for c in result.columns]}
    if not isinstance(result, dict):
        raise CodeExecutionError("analyze(df) must return a dict.")
    rows = result.get("rows", [])
    rows_was_scalar = False
    if isinstance(rows, pd.DataFrame):
        rows = rows.to_dict(orient="records")
    elif isinstance(rows, dict):
        rows = [rows]
    elif isinstance(rows, pd.Series):
        rows = [rows.to_dict()]
    elif rows is not None and not isinstance(rows, list):
        rows_was_scalar = True
        rows = [{"value": rows}]
    columns = result.get("columns")
    if columns is None and rows:
        columns = list(rows[0].keys())
    elif isinstance(columns, str):
        columns = [columns]
    elif isinstance(columns, pd.Index):
        columns = columns.tolist()
    elif rows_was_scalar and columns is not None and not isinstance(columns, (list, tuple)):
        columns = ["value"]
    elif columns is not None and not isinstance(columns, (list, tuple)):
        raise CodeExecutionError("analyze(df) result field 'columns' must be a list of column names.")
    normalized = {
        "direct_answer": str(result.get("direct_answer") or ""),
        "rows": _json_rows(rows if isinstance(rows, list) else []),
        "columns": [str(col) for col in (columns or [])],
    }
    response_sections = result.get("response_sections")
    if isinstance(response_sections, dict):
        normalized["response_sections"] = _json_value(response_sections)
    return normalized


def _worker(pandas_code: str, df: pd.DataFrame, tables: dict[str, pd.DataFrame], output: mp.Queue) -> None:
    namespace: dict[str, Any] = {
        "__builtins__": ALLOWED_BUILTINS,
        "pd": pd,
    }
    try:
        exec(pandas_code, namespace, namespace)  # noqa: S102 - sandboxed after AST validation, isolated process.
        analyze = namespace.get("analyze")
        if not callable(analyze):
            raise CodeExecutionError("Generated code must define callable analyze(df).")
        if tables and _wants_tables_argument(analyze):
            output.put(("ok", analyze(tables)))
        else:
            output.put(("ok", analyze(df)))
    except Exception as exc:  # pragma: no cover - surfaced to parent process.
        output.put(("error", f"{type(exc).__name__}: {exc}"))


def _root_name(node: ast.Attribute) -> str:
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        current = current.value
    return current.id if isinstance(current, ast.Name) else ""


def _wants_tables_argument(analyze: Any) -> bool:
    try:
        parameters = list(inspect.signature(analyze).parameters)
    except (TypeError, ValueError):
        return False
    return bool(parameters) and parameters[0] in {"tables", "dfs", "dataframes"}


def _json_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            normalized.append({str(key): _json_value(value) for key, value in row.items()})
        else:
            normalized.append({"value": _json_value(row)})
    return normalized


def _json_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, pd.Period):
        return str(value)
    if isinstance(value, pd.Timedelta):
        return value.isoformat()
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value
