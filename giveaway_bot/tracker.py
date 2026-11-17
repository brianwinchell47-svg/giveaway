"""SQLite log of checked giveaways, so each one is sent to you once per period."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    name TEXT,
    status TEXT NOT NULL,   -- ready | skipped | failed
    detail TEXT,
    source TEXT,            -- config | feed
    ts TEXT NOT NULL,
    link TEXT               -- page to open to enter (entry page behind a blog post)
);
CREATE INDEX IF NOT EXISTS attempts_url ON attempts(url, ts);
CREATE TABLE IF NOT EXISTS discovered (
    url TEXT PRIMARY KEY,
    title TEXT,
    feed TEXT,
    first_seen TEXT NOT NULL
);
"""

# Statuses that mean "handled for this period" (a failed check is retried next run).
DONE = ("ready", "skipped")

PERIODS = {"daily": timedelta(hours=23), "weekly": timedelta(days=6, hours=23)}


class Tracker:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(str(path))
        self.db.executescript(SCHEMA)
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(attempts)")}
        if "link" not in cols:  # database from an older version
            self.db.execute("ALTER TABLE attempts ADD COLUMN link TEXT")

    def record(self, url, status, detail="", name="", source="config", link=None):
        self.db.execute(
            "INSERT INTO attempts(url,name,status,detail,source,ts,link) VALUES (?,?,?,?,?,?,?)",
            (url, name, status, detail, source, datetime.now().isoformat(timespec="seconds"),
             link or url),
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
        last = self.last(url, DONE)
        if frequency == "once":
            return last is None
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

    def todo(self, hours: float = 24):
        """Giveaways sent to you as ready to enter in the last `hours`."""
        since = (datetime.now() - timedelta(hours=hours)).isoformat(timespec="seconds")
        return self.db.execute(
            "SELECT COALESCE(link, url), name, MAX(ts) FROM attempts "
            "WHERE status='ready' AND ts >= ? GROUP BY url ORDER BY MAX(ts) DESC",
            (since,),
        ).fetchall()
