import sqlite3

import pytest

from sql_assistant import db, guardrails


@pytest.fixture(scope="module")
def conn():
    connection = db.connect_guarded(db.ensure_database())
    yield connection
    connection.close()


def test_extract_sql_from_fenced_reply():
    reply = "Here you go:\n```sql\nSELECT COUNT(*) FROM Customer;\n```\nThis counts customers."
    assert guardrails.extract_sql(reply) == "SELECT COUNT(*) FROM Customer;"


def test_extract_sql_without_fence():
    assert guardrails.extract_sql("  SELECT 1  ") == "SELECT 1"


def test_valid_select_passes(conn):
    result = guardrails.validate("SELECT Name FROM Artist LIMIT 3;", conn)
    assert result.ok
    assert result.sql == "SELECT Name FROM Artist LIMIT 3"


def test_cte_passes(conn):
    sql = "WITH t AS (SELECT GenreId, COUNT(*) n FROM Track GROUP BY GenreId) SELECT MAX(n) FROM t"
    assert guardrails.validate(sql, conn).ok


@pytest.mark.parametrize("sql", [
    "DELETE FROM Track",
    "DROP TABLE Track",
    "UPDATE Track SET UnitPrice = 0",
    "PRAGMA table_info(Track)",
    "ATTACH DATABASE 'x.db' AS x",
    "SELECT 1; DELETE FROM Track",
    "WITH x AS (SELECT 1) DELETE FROM Track",
])
def test_unsafe_queries_are_rejected(conn, sql):
    assert not guardrails.validate(sql, conn).ok


def test_unknown_table_fails_compile_check(conn):
    result = guardrails.validate("SELECT * FROM Customers", conn)
    assert not result.ok
    assert result.first_failure.name == "Compiles against the schema"


def test_keywords_and_semicolons_inside_strings_are_allowed(conn):
    sql = "SELECT Name FROM Track WHERE Name = 'Drop; Delete' OR Name LIKE '%update%'"
    assert guardrails.validate(sql, conn).ok


def test_replace_function_is_allowed(conn):
    assert guardrails.validate("SELECT replace(Name, ' ', '_') FROM Artist LIMIT 1", conn).ok


def test_connection_refuses_writes_even_without_validation(conn):
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM Track")


def test_row_cap(conn):
    result = guardrails.run_query(conn, "SELECT TrackId FROM Track", max_rows=10)
    assert len(result.rows) == 10 and result.truncated


def test_time_limit(conn):
    slow = ("WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n) "
            "SELECT COUNT(*) FROM n")
    with pytest.raises(TimeoutError):
        guardrails.run_query(conn, slow, timeout_s=0.5)
