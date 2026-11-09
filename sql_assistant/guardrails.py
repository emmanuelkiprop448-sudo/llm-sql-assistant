"""Checks every generated query must pass before it runs, and the query runner itself."""

import re
import sqlite3
import time
from dataclasses import dataclass, field

BLOCKED_KEYWORDS = (
    "insert", "update", "delete", "drop", "alter", "create", "attach", "detach",
    "pragma", "vacuum", "reindex", "begin", "commit", "rollback", "savepoint", "release",
)
_BLOCKED = re.compile(r"\b(" + "|".join(BLOCKED_KEYWORDS) + r")\b", re.IGNORECASE)
_FENCE = re.compile(r"```(?:sql|sqlite)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Validation:
    sql: str
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)

    @property
    def first_failure(self) -> Check | None:
        return next((c for c in self.checks if not c.passed), None)


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    truncated: bool
    seconds: float


def extract_sql(text: str) -> str:
    """Pull the SQL out of a model reply: the first fenced block if there is one, else the whole reply."""
    match = _FENCE.search(text or "")
    return (match.group(1) if match else (text or "")).strip()


def _code_only(sql: str) -> str:
    """The query with string literals, quoted identifiers and comments blanked out,
    so keywords or semicolons inside them are not mistaken for code."""
    out, i, n = [], 0, len(sql)
    while i < n:
        ch = sql[i]
        if sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end == -1 else end
        elif sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
        elif ch in "'\"`[":
            close = "]" if ch == "[" else ch
            j = i + 1
            while j < n:
                if sql[j] == close:
                    if close != "]" and j + 1 < n and sql[j + 1] == close:  # doubled quote escape
                        j += 2
                        continue
                    break
                j += 1
            out.append(" ")
            i = j + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def validate(sql: str, conn: sqlite3.Connection) -> Validation:
    """Run the checks in order; later checks are skipped once one fails."""
    cleaned = sql.strip().rstrip(";").strip()
    result = Validation(sql=cleaned)
    code = _code_only(cleaned).strip()

    steps = [
        ("Query is not empty", lambda: (bool(code), "No SQL was produced.")),
        ("Single statement", lambda: (";" not in code, "Only one statement can run at a time.")),
        ("Starts with SELECT or WITH", lambda: (
            bool(re.match(r"(select|with)\b", code, re.IGNORECASE)),
            "Only read queries are allowed.",
        )),
        ("No data-changing keywords", lambda: (
            (m := _BLOCKED.search(code)) is None,
            f"Contains the keyword {m.group(1).upper()}." if m else "",
        )),
    ]
    for name, check in steps:
        passed, detail = check()
        result.checks.append(Check(name, passed, "" if passed else detail))
        if not passed:
            return result

    # Compile without running: catches unknown tables or columns and syntax errors.
    try:
        conn.execute(f"EXPLAIN {cleaned}")
        result.checks.append(Check("Compiles against the schema", True))
    except sqlite3.Error as exc:
        result.checks.append(Check("Compiles against the schema", False, str(exc)))
    return result


def run_query(conn: sqlite3.Connection, sql: str, max_rows: int = 500, timeout_s: float = 5.0) -> QueryResult:
    """Execute a validated query with a row cap and a time limit."""
    deadline = time.monotonic() + timeout_s
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    started = time.monotonic()
    try:
        cursor = conn.execute(sql)
        columns = [d[0] for d in cursor.description or []]
        rows = cursor.fetchmany(max_rows + 1)
    except sqlite3.OperationalError as exc:
        if "interrupted" in str(exc).lower():
            raise TimeoutError(f"Query stopped after {timeout_s:.0f} seconds.") from exc
        raise
    finally:
        conn.set_progress_handler(None, 0)
    return QueryResult(columns, rows[:max_rows], len(rows) > max_rows, time.monotonic() - started)
