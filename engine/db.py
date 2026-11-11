# -*- coding: utf-8 -*-
import os
import sqlite3

from engine.config import DATA_DIR, DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS destinations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    host TEXT NOT NULL,
    port INTEGER NOT NULL DEFAULT 21,
    username TEXT NOT NULL,
    password TEXT NOT NULL,
    path TEXT NOT NULL DEFAULT '/',
    passive INTEGER NOT NULL DEFAULT 1,
    tls INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    destination_id INTEGER NOT NULL,
    all_accounts INTEGER NOT NULL DEFAULT 1,
    accounts TEXT NOT NULL DEFAULT '[]',
    schedule TEXT NOT NULL DEFAULT 'manual',
    hour INTEGER NOT NULL DEFAULT 2,
    minute INTEGER NOT NULL DEFAULT 30,
    weekday INTEGER,
    retention INTEGER NOT NULL DEFAULT 7,
    include_homedir INTEGER NOT NULL DEFAULT 1,
    include_db INTEGER NOT NULL DEFAULT 1,
    include_dns INTEGER NOT NULL DEFAULT 1,
    include_mailconfig INTEGER NOT NULL DEFAULT 1,
    skip_logs INTEGER NOT NULL DEFAULT 1,
    skip_suspended INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_run TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    destination_id INTEGER,
    account TEXT,
    kind TEXT NOT NULL DEFAULT 'backup',
    status TEXT NOT NULL,
    remote_path TEXT,
    size_bytes INTEGER,
    started_at TEXT,
    finished_at TEXT,
    error TEXT,
    log TEXT NOT NULL DEFAULT '',
    force INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at);

CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    destination_id INTEGER,
    title TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'backup',
    created_at TEXT NOT NULL
);
"""


def connect():
    if not os.path.isdir(DATA_DIR):
        os.makedirs(DATA_DIR, 0o700)
    previous = os.umask(0o077)
    try:
        conn = sqlite3.connect(DB_PATH, timeout=60)
    finally:
        os.umask(previous)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    conn.executescript(_SCHEMA)
    _migrate(conn)
    os.chmod(DATA_DIR, 0o700)
    os.chmod(DB_PATH, 0o600)
    for suffix in ("-wal", "-shm"):
        side = DB_PATH + suffix
        if os.path.exists(side):
            os.chmod(side, 0o600)
    return conn


def _migrate(conn):
    columns = [row[1] for row in conn.execute("PRAGMA table_info(runs)")]
    if "batch_id" not in columns:
        conn.execute("ALTER TABLE runs ADD COLUMN batch_id INTEGER")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_batch ON runs(batch_id)")
    job_columns = [row[1] for row in conn.execute("PRAGMA table_info(jobs)")]
    if "max_account_bytes" not in job_columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN max_account_bytes INTEGER NOT NULL DEFAULT 0")
    run_columns = [row[1] for row in conn.execute("PRAGMA table_info(runs)")]
    if "local_path" not in run_columns:
        conn.execute("ALTER TABLE runs ADD COLUMN local_path TEXT")
    if "stage" not in run_columns:
        conn.execute("ALTER TABLE runs ADD COLUMN stage TEXT")
    if "manual" not in run_columns:
        conn.execute("ALTER TABLE runs ADD COLUMN manual INTEGER NOT NULL DEFAULT 0")
    if "expires_at" not in run_columns:
        conn.execute("ALTER TABLE runs ADD COLUMN expires_at TEXT")
    batch_columns = [row[1] for row in conn.execute("PRAGMA table_info(batches)")]
    added_summary = "summary_sent" not in batch_columns
    if "stop_requested" not in batch_columns:
        conn.execute("ALTER TABLE batches ADD COLUMN stop_requested INTEGER NOT NULL DEFAULT 0")
    if added_summary:
        conn.execute("ALTER TABLE batches ADD COLUMN summary_sent INTEGER NOT NULL DEFAULT 0")
    if "contains" not in job_columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN contains INTEGER")
    if "exclude_databases" not in job_columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN exclude_databases TEXT NOT NULL DEFAULT '[]'")
    if "email_contents" not in job_columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN email_contents INTEGER NOT NULL DEFAULT 1")
    if "exclude_junk" not in job_columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN exclude_junk INTEGER NOT NULL DEFAULT 0")
    if "locked" not in run_columns:
        conn.execute("ALTER TABLE runs ADD COLUMN locked INTEGER NOT NULL DEFAULT 0")
    if "scope_json" not in run_columns:
        conn.execute("ALTER TABLE runs ADD COLUMN scope_json TEXT")
    if "selection" not in run_columns:
        conn.execute("ALTER TABLE runs ADD COLUMN selection TEXT")
    dest_columns = [row[1] for row in conn.execute("PRAGMA table_info(destinations)")]
    if "kind" not in dest_columns:
        conn.execute("ALTER TABLE destinations ADD COLUMN kind TEXT NOT NULL DEFAULT 'ftp'")
    if "extra" not in dest_columns:
        conn.execute("ALTER TABLE destinations ADD COLUMN extra TEXT NOT NULL DEFAULT '{}'")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS backup_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            path TEXT NOT NULL,
            size_bytes INTEGER NOT NULL DEFAULT 0
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_entries_run ON backup_entries(run_id)")
    conn.commit()
    if added_summary:
        conn.execute(
            """UPDATE batches SET summary_sent=1
               WHERE NOT EXISTS (
                   SELECT 1 FROM runs
                   WHERE runs.batch_id=batches.id
                     AND runs.status IN ('queued','running','packaging','packaged','uploading')
               )"""
        )
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        pending = conn.execute("SELECT 1 FROM runs WHERE batch_id IS NULL LIMIT 1").fetchone()
        if pending is not None:
            _backfill_batches(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _backfill_batches(conn):
    groups = conn.execute(
        """SELECT job_id, destination_id, kind, created_at
           FROM runs WHERE batch_id IS NULL
           GROUP BY job_id, destination_id, kind, created_at
           ORDER BY created_at"""
    ).fetchall()
    for group in groups:
        job_name = None
        if group["job_id"] is not None:
            job = conn.execute("SELECT name FROM jobs WHERE id=?", (group["job_id"],)).fetchone()
            if job is not None:
                job_name = job["name"]
        if group["kind"] == "restore":
            account = conn.execute(
                """SELECT account FROM runs
                   WHERE batch_id IS NULL AND kind='restore' AND created_at=?
                     AND ((job_id IS NULL AND ? IS NULL) OR job_id=?)
                     AND ((destination_id IS NULL AND ? IS NULL) OR destination_id=?)
                   LIMIT 1""",
                (
                    group["created_at"],
                    group["job_id"],
                    group["job_id"],
                    group["destination_id"],
                    group["destination_id"],
                ),
            ).fetchone()
            title = "Geri yükleme · %s" % (account["account"] if account else "hesap")
        else:
            title = job_name or "Yedekleme"
        cur = conn.execute(
            """INSERT INTO batches (job_id, destination_id, title, kind, created_at)
               VALUES (?,?,?,?,?)""",
            (group["job_id"], group["destination_id"], title, group["kind"], group["created_at"]),
        )
        conn.execute(
            """UPDATE runs SET batch_id=?
               WHERE batch_id IS NULL AND kind=? AND created_at=?
                 AND ((job_id IS NULL AND ? IS NULL) OR job_id=?)
                 AND ((destination_id IS NULL AND ? IS NULL) OR destination_id=?)""",
            (
                cur.lastrowid,
                group["kind"],
                group["created_at"],
                group["job_id"],
                group["job_id"],
                group["destination_id"],
                group["destination_id"],
            ),
        )


def get_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if row is None:
        return default
    return row["value"]


def set_setting(conn, key, value):
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
