"""SQLite 持久化：当前原稿 + 待确认的预览。"""

import hashlib
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
    token        TEXT PRIMARY KEY,
    input_json   TEXT NOT NULL,
    result_json  TEXT NOT NULL,
    base_version INTEGER NOT NULL,
    created_at   TEXT NOT NULL
);
"""

# 原子确认的结果状态
PREVIEW_OK = "ok"                         # 确认成功，原稿已覆盖、令牌已消费
PREVIEW_MISSING = "missing"               # 令牌不存在或已被消费
PREVIEW_INPUT_MISMATCH = "input_mismatch"  # 草稿与预览输入不一致
PREVIEW_VERSION_CHANGED = "version_changed"  # 预览生成后原稿版本已被推进

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


def fingerprint(obj):
    """规范化 JSON 的 SHA-256，用于预览输入一致性比对。"""
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _design_from_row(row):
    return {
        "rows": row["rows"],
        "cols": row["cols"],
        "grid": json.loads(row["grid"]),
        "locks": json.loads(row["locks"]),
        "k": row["k"],
        "version": row["version"],
    }


class Database:
    def __init__(self, path):
        self.path = path
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        with self._lock, self._connect() as conn:
            conn.executescript(SCHEMA)
            # 旧库迁移：预览表补充 base_version（旧令牌该列为 NULL，
            # 确认时按原稿版本已变化处理，拒绝并要求重新预览）
            cols = {r["name"] for r in conn.execute(
                'PRAGMA table_info(preview)').fetchall()}
            if "base_version" not in cols:
                conn.execute(
                    "ALTER TABLE preview ADD COLUMN base_version INTEGER")
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
        return _design_from_row(row)

    def save_design(self, rows, cols, grid, locks, k):
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE design SET rows = ?, cols = ?, grid = ?, locks = ?,"
                " k = ?, version = version + 1, updated_at = ? WHERE id = 1",
                (rows, cols, json.dumps(grid), json.dumps(locks), k, _now()),
            )
        return self.get_design()

    def save_preview(self, token, input_obj, result_obj, base_version):
        """保存待确认预览，并绑定生成时的原稿版本号。"""
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO preview (token, input_json,"
                " result_json, base_version, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (token, json.dumps(input_obj), json.dumps(result_obj),
                 base_version, _now()),
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
            "base_version": row["base_version"],
        }

    def delete_preview(self, token):
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM preview WHERE token = ?", (token,))

    def confirm_preview(self, token, input_obj, rows, cols, locks, k):
        """原子确认预览。

        在同一个 SQLite 写事务（进程内另以互斥锁串行化）内依次校验：
        1. 令牌存在且未被消费；
        2. 提交草稿与预览生成时的输入一致；
        3. 预览绑定的原稿版本与当前原稿版本相同。
        全部通过才覆盖原稿（version 只递增一次）并删除令牌；
        任一失败立即回滚，原稿与令牌均不变。

        返回 (status, design)：status 为 PREVIEW_* 常量；
        仅 PREVIEW_OK 时 design 为确认后的新原稿，其余为 None。
        """
        input_fp = fingerprint(input_obj)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                prow = conn.execute(
                    "SELECT input_json, result_json, base_version"
                    " FROM preview WHERE token = ?",
                    (token,)).fetchone()
                if prow is None:
                    conn.rollback()
                    return PREVIEW_MISSING, None

                if fingerprint(json.loads(prow["input_json"])) != input_fp:
                    conn.rollback()
                    return PREVIEW_INPUT_MISMATCH, None

                drow = conn.execute(
                    "SELECT version FROM design WHERE id = 1").fetchone()
                base_version = prow["base_version"]
                if base_version is None or base_version != drow["version"]:
                    conn.rollback()
                    return PREVIEW_VERSION_CHANGED, None

                result = json.loads(prow["result_json"])
                conn.execute(
                    "UPDATE design SET rows = ?, cols = ?, grid = ?,"
                    " locks = ?, k = ?, version = version + 1,"
                    " updated_at = ? WHERE id = 1",
                    (rows, cols, json.dumps(result["repaired"]),
                     json.dumps(locks), k, _now()),
                )
                conn.execute("DELETE FROM preview WHERE token = ?", (token,))
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM design WHERE id = 1").fetchone()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        return PREVIEW_OK, _design_from_row(row)
