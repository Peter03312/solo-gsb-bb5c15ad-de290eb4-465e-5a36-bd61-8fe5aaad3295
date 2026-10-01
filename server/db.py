"""SQLite 持久化：当前原稿 + 待确认的预览。"""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS design (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    rows       INTEGER NOT NULL,
    cols       INTEGER NOT NULL,
    grid       TEXT NOT NULL,
    locks      TEXT NOT NULL,
    k          INTEGER NOT NULL,
    version    INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preview (
    token       TEXT PRIMARY KEY,
    input_json  TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""

# 默认原稿：4x4 交错平纹，无锁定，K=2
DEFAULT_DESIGN = {
    "rows": 4,
    "cols": 4,
    "grid": [[0, 1, 0, 1],
             [1, 0, 1, 0],
             [0, 1, 0, 1],
             [1, 0, 1, 0]],
    "locks": [],
    "k": 2,
}


def _now():
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path):
        self.path = path
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        with self._lock, self._connect() as conn:
            conn.executescript(SCHEMA)
            row = conn.execute("SELECT COUNT(*) AS n FROM design").fetchone()
            if row["n"] == 0:
                conn.execute(
                    "INSERT INTO design (id, rows, cols, grid, locks, k,"
                    " version, updated_at) VALUES (1, ?, ?, ?, ?, ?, 1, ?)",
                    (DEFAULT_DESIGN["rows"], DEFAULT_DESIGN["cols"],
                     json.dumps(DEFAULT_DESIGN["grid"]),
                     json.dumps(DEFAULT_DESIGN["locks"]),
                     DEFAULT_DESIGN["k"], _now()),
                )

    def get_design(self):
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM design WHERE id = 1").fetchone()
        return {
            "rows": row["rows"],
            "cols": row["cols"],
            "grid": json.loads(row["grid"]),
            "locks": json.loads(row["locks"]),
            "k": row["k"],
            "version": row["version"],
        }

    def save_design(self, rows, cols, grid, locks, k):
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE design SET rows = ?, cols = ?, grid = ?, locks = ?,"
                " k = ?, version = version + 1, updated_at = ? WHERE id = 1",
                (rows, cols, json.dumps(grid), json.dumps(locks), k, _now()),
            )
        return self.get_design()

    def save_preview(self, token, input_obj, result_obj):
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO preview (token, input_json,"
                " result_json, created_at) VALUES (?, ?, ?, ?)",
                (token, json.dumps(input_obj), json.dumps(result_obj), _now()),
            )

    def get_preview(self, token):
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM preview WHERE token = ?", (token,)).fetchone()
        if row is None:
            return None
        return {
            "input": json.loads(row["input_json"]),
            "result": json.loads(row["result_json"]),
        }

    def delete_preview(self, token):
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM preview WHERE token = ?", (token,))
