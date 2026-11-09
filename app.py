"""Ask the Chinook music-store database questions in plain English.

    streamlit run app.py
"""

from pathlib import Path

import pandas as pd
import streamlit as st

from sql_assistant import db, guardrails, llm

st.set_page_config(page_title="Chinook SQL Assistant", page_icon=":material/database:", layout="wide")

EXAMPLES = [
    "Which five countries have the most customers?",
    "What are the ten best-selling tracks by quantity sold?",
    "How much revenue did each genre bring in during 2024?",
    "Which employees report to the general manager?",
    "What is the average invoice total for each country?",
]
PICK_EXAMPLE = "Choose an example question"


@st.cache_resource
def database_path() -> str:
    return str(db.ensure_database())


@st.cache_data
def schema_text(path: str) -> str:
    return db.describe_schema(Path(path))


@st.cache_data
def tables(path: str) -> dict:
    return db.list_tables(Path(path))


def read_secrets() -> dict:
    try:
        return dict(st.secrets)
    except Exception:  # no secrets file: fall back to environment variables
        return {}


path = database_path()
config = llm.load_config(read_secrets())

defaults = {"question": "", "sql": "", "reply": "", "error": "", "validation": None, "result": None, "log": []}
for key, value in defaults.items():
    st.session_state.setdefault(key, value)


def use_example():
    if st.session_state.example != PICK_EXAMPLE:
        st.session_state.question = st.session_state.example


def generate():
    st.session_state.update(error="", validation=None, result=None)
    try:
        reply = llm.generate_sql(st.session_state.question, schema_text(path), config)
    except Exception as exc:
        st.session_state.error = f"The model call failed: {exc}. Check the model settings."
        return
    st.session_state.reply = reply
    sql = guardrails.extract_sql(reply)
    if sql.upper().startswith("UNANSWERABLE"):
        st.session_state.sql = ""
        st.session_state.error = "The model says this question can't be answered from this database."
    else:
        st.session_state.sql = sql


def run_sql():
    st.session_state.update(error="", result=None)
    conn = db.connect_guarded(Path(path))
    try:
        validation = guardrails.validate(st.session_state.sql, conn)
        st.session_state.validation = validation
        if validation.ok:
            st.session_state.result = guardrails.run_query(conn, validation.sql)
    except Exception as exc:
        st.session_state.error = f"The query failed: {exc}"
    finally:
        conn.close()


def add_to_log():
    result = st.session_state.result
    st.session_state.log.append({
        "question": st.session_state.question,
        "sql": st.session_state.validation.sql if st.session_state.validation else st.session_state.sql,
        "rows": len(result.rows) if result else 0,
        "verdict": st.session_state.verdict,
        "note": st.session_state.note,
    })


# Sidebar: model status and schema browser
with st.sidebar:
    st.subheader("Model")
    if config:
        st.markdown(f"Using `{config.model}`")
        if config.base_url:
            st.caption(config.base_url)
    else:
        st.warning("No model is configured, so SQL can't be generated. You can still write and run SQL yourself.")
        st.caption("Set LLM_MODEL and LLM_API_KEY (and LLM_BASE_URL if needed) in .streamlit/secrets.toml "
                   "or as environment variables. See the README.")
    st.subheader("Database tables")
    for table, columns in tables(path).items():
        with st.expander(table):
            st.write(", ".join(columns))

st.title("Ask the Chinook database")
st.caption("Chinook is a sample music store: artists, albums, tracks, customers, invoices and employees. "
           "Type a question, let the model write the SQL, check it, then run it. "
           "Every query passes read-only guardrails before it touches the data.")

st.selectbox("Example questions", [PICK_EXAMPLE, *EXAMPLES], key="example", on_change=use_example)
st.text_area("Your question", key="question", height=80)
st.button("Generate SQL", type="primary", on_click=generate,
          disabled=config is None or not st.session_state.question.strip())

st.text_area("SQL (edit it before running if you need to)", key="sql", height=170)
st.button("Run query", on_click=run_sql, disabled=not st.session_state.sql.strip())

if st.session_state.error:
    st.error(st.session_state.error)

validation = st.session_state.validation
if validation:
    st.subheader("Guardrail checks")
    for check in validation.checks:
        if check.passed:
            st.markdown(f":green[✓] {check.name}")
        else:
            st.markdown(f":red[✗] {check.name}: {check.detail}")

result = st.session_state.result
if result:
    st.subheader("Result")
    st.dataframe(pd.DataFrame(result.rows, columns=result.columns), use_container_width=True, hide_index=True)
    note = f"{len(result.rows):,} row(s) in {result.seconds * 1000:.0f} ms"
    if result.truncated:
        note += ". Only the first 500 rows are shown."
    st.caption(note)

    st.subheader("Review")
    st.radio("Did the query answer the question?", ["Correct", "Incorrect", "Not sure"], key="verdict", horizontal=True)
    st.text_input("Note (optional)", key="note")
    st.button("Add to review log", on_click=add_to_log)

if st.session_state.log:
    st.subheader("Review log")
    log = pd.DataFrame(st.session_state.log)
    st.dataframe(log, use_container_width=True, hide_index=True)
    st.download_button("Download review log (CSV)", log.to_csv(index=False), "review_log.csv", "text/csv")
