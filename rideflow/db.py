"""Thin SQLite persistence for plans.

The plan is stored as a JSON document keyed by id; the nested stages live
inside that document rather than in a separate table.
"""

import json
import sqlite3
from contextlib import closing


class Database:
    def __init__(self, path: str):
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS plans (id TEXT PRIMARY KEY, data TEXT NOT NULL)"
        )
        return conn

    def put(self, plan: dict) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO plans (id, data) VALUES (?, ?)",
                (plan["id"], json.dumps(plan, ensure_ascii=False)),
            )
            conn.commit()

    def get(self, plan_id: str) -> dict | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT data FROM plans WHERE id = ?", (plan_id,)
            ).fetchone()
        return json.loads(row[0]) if row else None
