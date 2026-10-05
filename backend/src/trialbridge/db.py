"""SQLite storage for trials, parsed criteria and patients.

Phase 1 uses SQLite so the whole system runs with zero setup. The schema is
plain SQL and ports directly to PostgreSQL in Phase 2.
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from trialbridge import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS trials (
    trial_id        TEXT PRIMARY KEY,      -- NCT id (or CTRI id in Phase 2)
    source          TEXT NOT NULL,         -- 'ctgov' | 'ctri'
    title           TEXT,
    official_title  TEXT,
    status          TEXT,
    phase           TEXT,
    conditions      TEXT,                  -- JSON list
    keywords        TEXT,                  -- JSON list
    interventions   TEXT,                  -- JSON list
    summary         TEXT,
    eligibility     TEXT,                  -- raw eligibility criteria text
    min_age_years   REAL,
    max_age_years   REAL,
    sex             TEXT,                  -- ALL | MALE | FEMALE
    healthy_volunteers INTEGER,
    countries       TEXT,                  -- JSON list
    last_updated    TEXT,
    ingested_at     TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS criteria (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    trial_id    TEXT NOT NULL REFERENCES trials(trial_id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    kind        TEXT NOT NULL,             -- inclusion | exclusion
    text        TEXT NOT NULL,
    predicates  TEXT NOT NULL              -- JSON list of predicate dicts
);
CREATE INDEX IF NOT EXISTS idx_criteria_trial ON criteria(trial_id);
CREATE TABLE IF NOT EXISTS patients (
    patient_id  TEXT PRIMARY KEY,
    source      TEXT NOT NULL,             -- 'synthea' | 'manual' | 'trec'
    name        TEXT,
    profile     TEXT NOT NULL              -- JSON PatientProfile
);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def session(path: Path | None = None):
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


JSON_FIELDS = ("conditions", "keywords", "interventions", "countries", "predicates", "profile")


def row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k in JSON_FIELDS:
        if k in d and isinstance(d[k], str):
            d[k] = json.loads(d[k])
    return d


def upsert_trial(conn: sqlite3.Connection, t: dict) -> None:
    cols = [
        "trial_id", "source", "title", "official_title", "status", "phase", "conditions",
        "keywords", "interventions", "summary", "eligibility", "min_age_years",
        "max_age_years", "sex", "healthy_volunteers", "countries", "last_updated",
    ]
    vals = [json.dumps(t.get(c)) if c in JSON_FIELDS else t.get(c) for c in cols]
    conn.execute(
        f"INSERT OR REPLACE INTO trials ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
        vals,
    )


def replace_criteria(conn: sqlite3.Connection, trial_id: str, criteria: list[dict]) -> None:
    conn.execute("DELETE FROM criteria WHERE trial_id = ?", (trial_id,))
    conn.executemany(
        "INSERT INTO criteria (trial_id, position, kind, text, predicates) VALUES (?, ?, ?, ?, ?)",
        [(trial_id, i, c["kind"], c["text"], json.dumps(c["predicates"])) for i, c in enumerate(criteria)],
    )


def upsert_patient(conn: sqlite3.Connection, patient_id: str, source: str, name: str, profile: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO patients (patient_id, source, name, profile) VALUES (?, ?, ?, ?)",
        (patient_id, source, name, json.dumps(profile)),
    )
