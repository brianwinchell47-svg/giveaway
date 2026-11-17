"""SQLite log of entry attempts, used to enforce one entry per period."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    name TEXT,
    status TEXT NOT NULL,   -- entered | submitted_unconfirmed | skipped | needs_manual | failed
    detail TEXT,
    source TEXT,            -- config | feed
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS attempts_url ON attempts(url, ts);
CREATE TABLE IF NOT EXISTS discovered (
    url TEXT PRIMARY KEY,
    title TEXT,
    feed TEXT,
    first_seen TEXT NOT NULL
);
"""

# Statuses that count as "we entered this period" (don't enter again).
ENTERED = ("entered", "submitted_unconfirmed")
# Statuses that mean "don't keep retrying automatically" for one-time giveaways.
FINAL = ENTERED + ("needs_manual", "skipped")

PERIODS = {"daily": timedelta(hours=23), "weekly": timedelta(days=6, hours=23)}


class Tracker:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(str(path))
        self.db.executescript(SCHEMA)

    def record(self, url, status, detail="", name="", source="config"):
        self.db.execute(
            "INSERT INTO attempts(url,name,status,detail,source,ts) VALUES (?,?,?,?,?,?)",
            (url, name, status, detail, source, datetime.now().isoformat(timespec="seconds")),
        )
        self.db.commit()

    def last(self, url, statuses):
        q = "SELECT ts FROM attempts WHERE url=? AND status IN (%s) ORDER BY ts DESC LIMIT 1" % (
            ",".join("?" * len(statuses))
        )
        row = self.db.execute(q, (url, *statuses)).fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def is_due(self, url: str, frequency: str, now: datetime | None = None) -> bool:
        now = now or datetime.now()
        if frequency == "once":
            return self.last(url, FINAL) is None
        last = self.last(url, ENTERED)
        if last is None:
            # Recurring giveaway flagged as manual/skipped today: wait for next period.
            last = self.last(url, ("needs_manual", "skipped"))
        return last is None or now - last >= PERIODS[frequency]

    def add_discovered(self, url, title, feed) -> bool:
        cur = self.db.execute(
            "INSERT OR IGNORE INTO discovered(url,title,feed,first_seen) VALUES (?,?,?,?)",
            (url, title, feed, datetime.now().isoformat(timespec="seconds")),
        )
        self.db.commit()
        return cur.rowcount > 0

    def pending_discovered(self, limit: int):
        return self.db.execute(
            "SELECT d.url, d.title FROM discovered d WHERE NOT EXISTS "
            "(SELECT 1 FROM attempts a WHERE a.url = d.url) ORDER BY first_seen LIMIT ?",
            (limit,),
        ).fetchall()

    def history(self, limit: int = 50):
        return self.db.execute(
            "SELECT ts, status, name, url, detail FROM attempts ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()

    def needs_manual(self):
        return self.db.execute(
            "SELECT url, name, detail, MAX(ts) FROM attempts WHERE status='needs_manual' "
            "AND url NOT IN (SELECT url FROM attempts WHERE status IN ('entered','submitted_unconfirmed')) "
            "GROUP BY url ORDER BY MAX(ts) DESC"
        ).fetchall()
