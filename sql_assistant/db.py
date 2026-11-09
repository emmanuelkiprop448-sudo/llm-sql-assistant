"""Database download, connections and schema description."""

import shutil
import sqlite3
import urllib.request
from pathlib import Path

CHINOOK_URL = (
    "https://raw.githubusercontent.com/lerocha/chinook-database/master/"
    "ChinookDatabase/DataSources/Chinook_Sqlite.sqlite"
)
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "chinook.sqlite"

# Operations a query may perform. Everything else (writes, schema changes,
# PRAGMA, ATTACH, transactions) is denied by SQLite itself before it runs.
_ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    sqlite3.SQLITE_RECURSIVE,
}


def ensure_database(path: Path = DB_PATH) -> Path:
    """Download the Chinook sample database on first use."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        with urllib.request.urlopen(CHINOOK_URL) as response, open(tmp, "wb") as out:
            shutil.copyfileobj(response, out)
        tmp.rename(path)
    return path


def _authorizer(action, *_):
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


def connect_guarded(path: Path = DB_PATH) -> sqlite3.Connection:
    """Read-only connection that also refuses anything other than reading data.

    Two independent layers: the file is opened with mode=ro, and an authorizer
    callback denies every operation except SELECT, column reads and functions.
    """
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)
    conn.set_authorizer(_authorizer)
    return conn


def describe_schema(path: Path = DB_PATH) -> str:
    """Compact schema text for the model prompt: tables, columns, keys and row counts."""
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        lines = []
        for table in tables:
            foreign = {row[3]: f"{row[2]}.{row[4]}" for row in conn.execute(f'PRAGMA foreign_key_list("{table}")')}
            cols = []
            for _, name, col_type, _, _, pk in conn.execute(f'PRAGMA table_info("{table}")'):
                note = " primary key" if pk else ""
                if name in foreign:
                    note += f" references {foreign[name]}"
                cols.append(f"  {name} {col_type}{note}")
            rows = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            lines.append(f"{table} ({rows:,} rows)\n" + "\n".join(cols))
        return "\n\n".join(lines)
    finally:
        conn.close()


def list_tables(path: Path = DB_PATH) -> dict[str, list[str]]:
    """Table name -> column names, for the schema browser in the app."""
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        return {t: [r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')] for t in tables}
    finally:
        conn.close()
