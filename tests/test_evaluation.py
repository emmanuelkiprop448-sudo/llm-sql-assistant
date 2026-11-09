"""Checks the benchmark and the scoring without calling a real model."""

import json
from types import SimpleNamespace

import pytest

from sql_assistant import db, evaluate, llm


@pytest.fixture(scope="module")
def setup():
    path = db.ensure_database()
    conn = db.connect_guarded(path)
    yield db.describe_schema(path), conn
    conn.close()


class FakeClient:
    """Stands in for the OpenAI client and returns a fixed reply."""

    def __init__(self, reply: str):
        message = SimpleNamespace(content=reply)
        response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response))


CONFIG = llm.LLMConfig(model="fake", api_key="fake")
ITEMS = json.loads(evaluate.QUESTIONS.read_text(encoding="utf-8"))


@pytest.mark.parametrize("item", ITEMS, ids=[i["id"] for i in ITEMS])
def test_reference_answers_score_correct(setup, item):
    schema, conn = setup
    reply = f"```sql\n{item['reference_sql']}\n```"
    record = evaluate.evaluate_question(item, schema, CONFIG, conn, client=FakeClient(reply))
    assert record["outcome"] == "correct"


def test_wrong_answer_is_scored_wrong(setup):
    schema, conn = setup
    record = evaluate.evaluate_question(ITEMS[0], schema, CONFIG, conn,
                                        client=FakeClient("```sql\nSELECT COUNT(*) FROM Employee\n```"))
    assert record["outcome"] == "wrong_result"


def test_unsafe_answer_is_blocked(setup):
    schema, conn = setup
    record = evaluate.evaluate_question(ITEMS[0], schema, CONFIG, conn,
                                        client=FakeClient("```sql\nDELETE FROM Customer\n```"))
    assert record["outcome"] == "blocked"


def test_unanswerable_reply(setup):
    schema, conn = setup
    record = evaluate.evaluate_question(ITEMS[0], schema, CONFIG, conn, client=FakeClient("UNANSWERABLE"))
    assert record["outcome"] == "no_sql"
