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
            CREATE TABLE IF NOT EXISTS activity (
                chat_key TEXT PRIMARY KEY, last_input REAL NOT NULL,
                last_output REAL NOT NULL DEFAULT 0, generation INTEGER NOT NULL DEFAULT 1,
                consumed_generation INTEGER NOT NULL DEFAULT -1,
                day TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS delivery (
                chat_key TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                message_seq INTEGER NOT NULL, context_seq INTEGER NOT NULL,
                persona_sent INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS searches (
                dispatch_id INTEGER PRIMARY KEY, chat_key TEXT NOT NULL,
                created REAL NOT NULL, stage TEXT NOT NULL);
        """)
        # An interrupted request is not blindly re-sent after restart.
        with self.db:
            self.db.execute("UPDATE sessions SET suspended=1 WHERE chat_key IN "
                            "(SELECT chat_key FROM dispatches WHERE status='inflight')")
            self.db.execute("UPDATE dispatches SET status='interrupted' WHERE status='inflight'")
            self.db.execute("UPDATE searches SET stage='interrupted' WHERE stage IN "
                            "('searching','results_ready','answering')")

    def append(self, message):
        with self.db:
            cur = self.db.execute("INSERT OR IGNORE INTO messages(chat_key,message_id,payload,created) VALUES(?,?,?,?)",
                                  (message.key, message.message_id, json.dumps(message.payload(), ensure_ascii=False), time.time()))
            self.db.execute("DELETE FROM messages WHERE chat_key=? AND seq NOT IN "
                            "(SELECT seq FROM messages WHERE chat_key=? ORDER BY seq DESC LIMIT ?)",
                            (message.key, message.key, self.history_limit))
            if cur.rowcount == 1 and abs(time.time() - message.timestamp) <= 120:
                self.db.execute("INSERT INTO activity(chat_key,last_input) VALUES(?,?) "
                                "ON CONFLICT(chat_key) DO UPDATE SET last_input=excluded.last_input, "
                                "generation=activity.generation+1", (message.key, time.time()))
        return cur.rowcount == 1

    def recent(self, key, count):
        rows = self.db.execute("SELECT payload FROM messages WHERE chat_key=? ORDER BY seq DESC LIMIT ?", (key, count)).fetchall()
        return [json.loads(row[0]) for row in reversed(rows)]

    def pending_messages(self, key, count, after=0):
        """Freeze the delivered input boundary before any network await."""
        rows = self.db.execute("SELECT seq,payload FROM messages WHERE chat_key=? AND seq>? "
                               "ORDER BY seq DESC LIMIT ?", (key, after, count)).fetchall()
        return ([json.loads(row[1]) for row in reversed(rows)], rows[0][0] if rows else after)

    def delivery(self, key, session_id):
        return self.db.execute("SELECT message_seq,context_seq,persona_sent FROM delivery "
                               "WHERE chat_key=? AND session_id=?", (key, session_id)).fetchone()

    def delivered(self, key, session_id, message_seq, context_seq, persona_sent):
        # Only called after DSH confirms a completed turn, including deliberate silence.
        with self.db:
            self.db.execute("INSERT INTO delivery VALUES(?,?,?,?,?) ON CONFLICT(chat_key) DO UPDATE SET "
                            "session_id=excluded.session_id,message_seq=excluded.message_seq,"
                            "context_seq=excluded.context_seq,persona_sent=excluded.persona_sent",
                            (key, session_id, message_seq, context_seq, int(persona_sent)))

    def session(self, key):
        return self.db.execute("SELECT session_id,policy,suspended FROM sessions WHERE chat_key=?", (key,)).fetchone()

    def bind(self, key, session_id, policy):
        with self.db:
            self.db.execute("DELETE FROM delivery WHERE chat_key=?", (key,))
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
            self.db.execute("DELETE FROM searches WHERE created<?", (time.time() - 7 * 86400,))
        return cur.lastrowid

    def search_count(self, key):
        return self.db.execute("SELECT COUNT(*) FROM searches WHERE chat_key=? AND created>?",
                               (key, time.time() - 3600)).fetchone()[0]

    def begin_search(self, key, dispatch, limit):
        # Includes cache hits/failures; reset does not replenish the budget.
        with self.db:
            cur = self.db.execute("INSERT INTO searches SELECT ?,?,?,'searching' WHERE "
                "(SELECT COUNT(*) FROM searches WHERE chat_key=? AND created>?) < ?",
                (dispatch, key, time.time(), key, time.time() - 3600, limit))
        return cur.rowcount == 1

    def search_stage(self, dispatch, stage):
        with self.db:
            self.db.execute("UPDATE searches SET stage=? WHERE dispatch_id=?", (stage, dispatch))

    def finish(self, dispatch, status):
        with self.db:
            self.db.execute("UPDATE dispatches SET status=? WHERE id=?", (status, dispatch))

    def reset(self, key):
        with self.db:
            self.db.execute("DELETE FROM delivery WHERE chat_key=?", (key,))
            self.db.execute("DELETE FROM sessions WHERE chat_key=?", (key,))
            self.db.execute("DELETE FROM messages WHERE chat_key=?", (key,))
            # Preserve daily budget, and do not revive an idle opportunity after reset.
            self.db.execute("UPDATE activity SET consumed_generation=generation WHERE chat_key=?", (key,))

    def activities(self):
        return self.db.execute("SELECT chat_key,last_input,last_output,generation,consumed_generation,day,attempts FROM activity").fetchall()

    def activity(self, key):
        return self.db.execute("SELECT chat_key,last_input,last_output,generation,consumed_generation,day,attempts FROM activity WHERE chat_key=?", (key,)).fetchone()

    def claim_proactive(self, key, generation, day, limit):
        with self.db:
            cur = self.db.execute("UPDATE activity SET consumed_generation=generation,day=?, "
                "attempts=CASE WHEN day=? THEN attempts+1 ELSE 1 END "
                "WHERE chat_key=? AND generation=? AND consumed_generation<>generation "
                "AND (day<>? OR attempts<?)", (day, day, key, generation, day, limit))
        return cur.rowcount == 1

    def mark_output(self, key):
        with self.db:
            self.db.execute("UPDATE activity SET last_output=? WHERE chat_key=?", (time.time(), key))

    def close(self):
        self.db.close()
