"""Measure how often the configured model writes SQL that returns the right answer.

    python -m sql_assistant.evaluate            # all questions in eval/questions.json
    python -m sql_assistant.evaluate --limit 3  # quick check

Each question has a hand-written reference query. The model's query is checked by
the same guardrails the app uses, run, and its result compared with the reference
result (see compare.py). Results go to eval/results/.
"""

import argparse
import csv
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from sql_assistant import db, guardrails, llm
from sql_assistant.compare import lenient_match, strict_match

PROJECT_DIR = Path(__file__).resolve().parent.parent
QUESTIONS = PROJECT_DIR / "eval" / "questions.json"
RESULTS_DIR = PROJECT_DIR / "eval" / "results"

OUTCOMES = {
    "correct": "Correct",
    "correct_extra_columns": "Correct answer with extra columns",
    "wrong_result": "Runs, wrong result",
    "query_error": "Failed when run",
    "blocked": "Rejected by guardrails",
    "no_sql": "No SQL returned",
}


def _read_secrets_file() -> dict:
    """Use the same .streamlit/secrets.toml as the app, if it exists."""
    path = PROJECT_DIR / ".streamlit" / "secrets.toml"
    if not path.exists():
        return {}
    import tomllib

    return tomllib.loads(path.read_text(encoding="utf-8"))


def evaluate_question(item: dict, schema: str, config: llm.LLMConfig, conn, client=None) -> dict:
    record = {"id": item["id"], "question": item["question"], "generated_sql": "", "outcome": "", "detail": ""}
    started = time.monotonic()
    try:
        reply = llm.generate_sql(item["question"], schema, config, client=client)
    except Exception as exc:  # network, auth or provider errors
        record.update(outcome="no_sql", detail=f"Model call failed: {exc}")
        return record
    record["seconds"] = round(time.monotonic() - started, 2)

    sql = guardrails.extract_sql(reply)
    record["generated_sql"] = sql
    if not sql or sql.upper().startswith("UNANSWERABLE"):
        record.update(outcome="no_sql", detail="Model returned no query.")
        return record

    check = guardrails.validate(sql, conn)
    if not check.ok:
        failure = check.first_failure
        record.update(outcome="blocked", detail=f"{failure.name}: {failure.detail}")
        return record

    try:
        predicted = guardrails.run_query(conn, check.sql, max_rows=10_000).rows
    except Exception as exc:
        record.update(outcome="query_error", detail=str(exc))
        return record
    reference = guardrails.run_query(conn, item["reference_sql"], max_rows=10_000).rows

    if strict_match(reference, predicted):
        record["outcome"] = "correct"
    elif lenient_match(reference, predicted):
        record["outcome"] = "correct_extra_columns"
    else:
        record.update(outcome="wrong_result",
                      detail=f"Expected {len(reference)} row(s), got {len(predicted)}.")
    return record


def write_summary(records: list[dict], config: llm.LLMConfig, path: Path) -> None:
    total = len(records)
    counts = Counter(r["outcome"] for r in records)
    strict = counts["correct"]
    lenient = strict + counts["correct_extra_columns"]
    lines = [
        "# Text-to-SQL evaluation results",
        "",
        f"- Model: `{config.model}`",
        f"- Run: {datetime.now():%Y-%m-%d %H:%M}",
        f"- Questions: {total}",
        f"- **Strict accuracy: {strict}/{total} ({100 * strict / total:.0f}%)**",
        f"- Lenient accuracy (extra columns allowed): {lenient}/{total} ({100 * lenient / total:.0f}%)",
        "",
        "| Outcome | Questions |",
        "| --- | --- |",
        *[f"| {label} | {counts.get(key, 0)} |" for key, label in OUTCOMES.items()],
        "",
        "| ID | Question | Outcome | Detail |",
        "| --- | --- | --- | --- |",
        *[f"| {r['id']} | {r['question']} | {OUTCOMES[r['outcome']]} | {r['detail'].replace('|', '/')} |"
          for r in records],
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the configured model on the benchmark questions")
    parser.add_argument("--limit", type=int, help="Only run the first N questions")
    parser.add_argument("--pause", type=float, default=0.0,
                        help="Seconds to wait between questions, to stay within a free plan's rate limits")
    args = parser.parse_args()

    config = llm.load_config(_read_secrets_file())
    if config is None:
        print("Set LLM_MODEL and LLM_API_KEY (and LLM_BASE_URL if needed) before running the evaluation.",
              file=sys.stderr)
        return 1

    path = db.ensure_database()
    schema = db.describe_schema(path)
    conn = db.connect_guarded(path)
    items = json.loads(QUESTIONS.read_text(encoding="utf-8"))[: args.limit]

    records = []
    for number, item in enumerate(items):
        if number and args.pause:
            time.sleep(args.pause)
        record = evaluate_question(item, schema, config, conn)
        print(f"{record['id']}: {OUTCOMES[record['outcome']]}")
        records.append(record)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_DIR / "results.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "question", "outcome", "detail", "generated_sql", "seconds"],
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    write_summary(records, config, RESULTS_DIR / "summary.md")
    print(f"Summary written to {RESULTS_DIR / 'summary.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
