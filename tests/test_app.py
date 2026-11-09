"""Smoke test: the app loads and runs a hand-written query without a model configured."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def test_app_runs_a_query(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    app = AppTest.from_file(APP, default_timeout=30).run()
    assert not app.exception

    app.text_area(key="sql").set_value("SELECT Name FROM Genre ORDER BY Name LIMIT 5").run()
    app.button[1].click().run()  # "Run query"
    assert not app.exception
    assert len(app.dataframe) == 1
    assert app.dataframe[0].value.shape == (5, 1)


def test_app_blocks_unsafe_query(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    app = AppTest.from_file(APP, default_timeout=30).run()
    app.text_area(key="sql").set_value("DROP TABLE Track").run()
    app.button[1].click().run()
    assert not app.exception
    assert len(app.dataframe) == 0
    assert any("Starts with SELECT or WITH" in m.value for m in app.markdown)
