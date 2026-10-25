"""Bounded local history and durable session/dispatch state (no API credentials)."""
import json
import sqlite3
import time
from pathlib import Path


class Store:
    def __init__(self, path, history_limit=200):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=5)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.history_limit = history_limit
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                chat_key TEXT PRIMARY KEY, session_id TEXT UNIQUE NOT NULL,
                policy TEXT NOT NULL, suspended INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS messages (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, chat_key TEXT NOT NULL,
                message_id TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL,
                UNIQUE(chat_key, message_id));
            CREATE TABLE IF NOT EXISTS dispatches (
                id INTEGER PRIMARY KEY AUTOINCREMENT, chat_key TEXT NOT NULL,
                created REAL NOT NULL, status TEXT NOT NULL);
        """)
        # An interrupted request is not blindly re-sent after restart.
        with self.db:
            self.db.execute("UPDATE sessions SET suspended=1 WHERE chat_key IN "
                            "(SELECT chat_key FROM dispatches WHERE status='inflight')")
            self.db.execute("UPDATE dispatches SET status='interrupted' WHERE status='inflight'")

    def append(self, message):
        with self.db:
            cur = self.db.execute("INSERT OR IGNORE INTO messages(chat_key,message_id,payload,created) VALUES(?,?,?,?)",
                                  (message.key, message.message_id, json.dumps(message.payload(), ensure_ascii=False), time.time()))
            self.db.execute("DELETE FROM messages WHERE chat_key=? AND seq NOT IN "
                            "(SELECT seq FROM messages WHERE chat_key=? ORDER BY seq DESC LIMIT ?)",
                            (message.key, message.key, self.history_limit))
        return cur.rowcount == 1

    def recent(self, key, count):
        rows = self.db.execute("SELECT payload FROM messages WHERE chat_key=? ORDER BY seq DESC LIMIT ?", (key, count)).fetchall()
        return [json.loads(row[0]) for row in reversed(rows)]

    def session(self, key):
        return self.db.execute("SELECT session_id,policy,suspended FROM sessions WHERE chat_key=?", (key,)).fetchone()

    def bind(self, key, session_id, policy):
        with self.db:
            self.db.execute("INSERT INTO sessions VALUES(?,?,?,0) ON CONFLICT(chat_key) DO UPDATE SET "
                            "session_id=excluded.session_id,policy=excluded.policy,suspended=0", (key, session_id, policy))

    def suspend(self, key):
        with self.db:
            self.db.execute("UPDATE sessions SET suspended=1 WHERE chat_key=?", (key,))

    def calls(self, key, since):
        return self.db.execute("SELECT COUNT(*),MAX(created) FROM dispatches WHERE chat_key=? AND created>?", (key, since)).fetchone()

    def begin(self, key):
        with self.db:
            cur = self.db.execute("INSERT INTO dispatches(chat_key,created,status) VALUES(?,?,'inflight')", (key, time.time()))
            self.db.execute("DELETE FROM dispatches WHERE created<?", (time.time() - 7 * 86400,))
        return cur.lastrowid

    def finish(self, dispatch, status):
        with self.db:
            self.db.execute("UPDATE dispatches SET status=? WHERE id=?", (status, dispatch))

    def reset(self, key):
        with self.db:
            self.db.execute("DELETE FROM sessions WHERE chat_key=?", (key,))
            self.db.execute("DELETE FROM messages WHERE chat_key=?", (key,))

    def close(self):
        self.db.close()
