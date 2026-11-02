"""Request log: SQLite at data/requests.db (stdlib sqlite3). One connection per call, so threads are safe."""
import contextlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bridge.config import ROOT

SCHEMA = """CREATE TABLE IF NOT EXISTS requests (
    id TEXT PRIMARY KEY, ts TEXT NOT NULL, text TEXT, text_norm TEXT, mode TEXT, final_tier TEXT,
    provider TEXT, model TEXT, jev_choice TEXT, jev_p REAL, jev_usd REAL DEFAULT 0, path_json TEXT,
    answer TEXT, feedback TEXT, night_label TEXT, parent_id TEXT);
CREATE INDEX IF NOT EXISTS requests_norm ON requests(text_norm, ts);"""

FIELDS = ("text", "mode", "final_tier", "provider", "model", "jev_choice", "jev_p", "jev_usd", "path", "answer",
          "feedback", "parent_id")


def normalise(text):
    return re.sub(r"\s+", " ", (text or "").lower()).strip().rstrip("?!. ")


def _now():
    return datetime.now(timezone.utc)


class Log:
    def __init__(self, path=None):
        self.path = str(path or ROOT / "data" / "requests.db")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with contextlib.closing(self._db()) as db:
            db.executescript(SCHEMA)

    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def _run(self, sql, args=()):
        with contextlib.closing(self._db()) as db, db:  # closing() closes; sqlite3's own `with` only commits
            return db.execute(sql, args).fetchall()

    def insert(self, **row):
        """Keys from FIELDS; `path` is a list of step dicts. Returns the new id."""
        unknown = set(row) - set(FIELDS)
        if unknown:
            raise ValueError(f"unknown log fields: {sorted(unknown)}")
        rid = str(uuid.uuid4())
        self._run(
            "INSERT INTO requests (id, ts, text, text_norm, mode, final_tier, provider, model, jev_choice, jev_p,"
            " jev_usd, path_json, answer, feedback, parent_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, _now().isoformat(), row.get("text"), normalise(row.get("text")), row.get("mode"),
             row.get("final_tier"), row.get("provider"), row.get("model"), row.get("jev_choice"), row.get("jev_p"),
             row.get("jev_usd") or 0.0, json.dumps(row.get("path") or []), row.get("answer"), row.get("feedback"),
             row.get("parent_id")))
        return rid

    def get(self, rid):
        rows = self._run("SELECT * FROM requests WHERE id = ?", (rid,))
        if not rows:
            return None
        d = dict(rows[0])
        d["path"] = json.loads(d.pop("path_json") or "[]")
        return d

    def set_feedback(self, rid, verdict):
        if verdict not in ("up", "down", "escalated", None):
            raise ValueError("verdict must be up, down or escalated")
        self._run("UPDATE requests SET feedback = ? WHERE id = ?", (verdict, rid))

    def set_night_label(self, rid, tier):
        self._run("UPDATE requests SET night_label = ? WHERE id = ?", (tier, rid))

    def recent_confirmed(self, text_norm, days=30):
        """Tier of the newest confirmed request (feedback up, or a night-school label) with this exact normalised
        text in the last `days` days. A night label wins over final_tier: it is the tier Opus said was right."""
        since = (_now() - timedelta(days=days)).isoformat()
        rows = self._run(
            "SELECT final_tier, night_label FROM requests WHERE text_norm = ? AND ts >= ?"
            " AND (feedback = 'up' OR night_label IS NOT NULL) ORDER BY ts DESC LIMIT 1", (text_norm, since))
        return (rows[0]["night_label"] or rows[0]["final_tier"]) if rows else None

    def stats(self):
        """Usage counters for /api/usage: Jev $ this calendar month (UTC), Ollama calls today (UTC): every T2 step
        plus every local check (the checker is the Ollama model)."""
        now = _now()
        month = now.strftime("%Y-%m")
        jev = self._run("SELECT COALESCE(SUM(jev_usd), 0) AS s FROM requests WHERE substr(ts, 1, 7) = ?", (month,))
        calls = 0
        for r in self._run("SELECT path_json FROM requests WHERE substr(ts, 1, 10) = ?", (now.strftime("%Y-%m-%d"),)):
            for step in json.loads(r["path_json"] or "[]"):
                calls += (step.get("tier") == "T2") + (step.get("check") is not None)
        return {"jev_usd_month": round(jev[0]["s"], 6), "ollama_calls_today": calls}

    def asked_by_tier(self, days=7):
        """{final_tier: count} for requests in the last `days` days (all rows, escalation children included)."""
        since = (_now() - timedelta(days=days)).isoformat()
        rows = self._run("SELECT final_tier AS t, COUNT(*) AS n FROM requests WHERE ts >= ? AND final_tier IS NOT NULL"
                         " GROUP BY final_tier", (since,))
        return {r["t"]: r["n"] for r in rows}
