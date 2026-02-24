# schema.py
import sqlite3
from typing import List

DB_DEFAULT = "mypet.db"


def connect(db_path: str = DB_DEFAULT) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    rows = conn.execute(f"PRAGMA table_info({table});").fetchall()
    return [r["name"] for r in rows]


def migrate(conn: sqlite3.Connection) -> None:
    """
    Safe migration:
    - Create tables if missing (does not overwrite existing)
    - Add new columns only if missing
    - Create indices if missing
    Never deletes or drops data.
    """
    conn.execute("PRAGMA foreign_keys = ON;")

    # Base tables (existing)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS mypet (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            breed TEXT,
            birth_date TEXT,    -- YYYY-MM-DD
            gender TEXT CHECK (gender IN ('male','female','unknown')) DEFAULT 'unknown',
            castrated INTEGER NOT NULL DEFAULT 0 CHECK (castrated IN (0,1)),
            allergies TEXT,     -- free text (zh/en)
            chronic_conditions TEXT,  -- free text (zh/en)
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            pet_id INTEGER NOT NULL,

            date TEXT NOT NULL,  -- YYYY-MM-DD
            type TEXT NOT NULL CHECK (type IN ('healthCheck','vaccine','diagnosis','symptoms','surgery','treatment')),
            vet TEXT,

            title TEXT NOT NULL,
            note TEXT,

            -- for diagnosis/symptoms standardization (optional, can be NULL)
            standard_name_zh TEXT,  -- e.g. "退行性二尖瓣病"
            standard_name_en TEXT,  -- e.g. "Myxomatous Mitral Valve Disease (MMVD)"

            attachment_path TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (pet_id) REFERENCES mypet(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pet_id INTEGER NOT NULL,

            date TEXT NOT NULL, -- YYYY-MM-DD
            type TEXT NOT NULL CHECK (type IN ('weight','neck','chest','waist')),
            value REAL NOT NULL,
            unit TEXT NOT NULL CHECK (unit IN ('kg','cm','inch')),
            note TEXT,

            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (pet_id) REFERENCES mypet(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS medications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pet_id INTEGER NOT NULL,

            drug_name TEXT NOT NULL,
            dose REAL,                -- if not numeric (e.g. "half tablet"), put in note
            unit TEXT,                -- mg/ml/tablet/drops etc (free text)
            frequency TEXT,           -- free text: "once daily", "every 8 hours", etc

            start_date TEXT,          -- YYYY-MM-DD
            end_date TEXT,            -- YYYY-MM-DD
            reason TEXT,
            note TEXT,

            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (pet_id) REFERENCES mypet(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pet_id INTEGER NOT NULL,

            due_date TEXT NOT NULL,  -- YYYY-MM-DD
            title TEXT NOT NULL,
            note TEXT,

            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','done')),
            repeat_rule TEXT, -- keep empty for now

            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (pet_id) REFERENCES mypet(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_events_pet_date ON events(pet_id, date);
        CREATE INDEX IF NOT EXISTS idx_measurements_pet_date ON measurements(pet_id, date);
        CREATE INDEX IF NOT EXISTS idx_reminders_pet_due ON reminders(pet_id, due_date);
        """
    )

    # NEW: episodes table
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS episodes (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          pet_id INTEGER NOT NULL,
          condition_name_zh TEXT NOT NULL,
          condition_name_en TEXT,
          category TEXT, -- cardiac/respiratory/ortho/neuro/skin/other
          status TEXT NOT NULL DEFAULT 'active', -- active/resolved/monitoring
          start_date TEXT,
          end_date TEXT,
          note TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          FOREIGN KEY (pet_id) REFERENCES mypet(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_episodes_pet_status ON episodes(pet_id, status);
        """
    )

    # NEW: events.episode_id column (only if missing)
    cols = _table_columns(conn, "events")
    if "episode_id" not in cols:
        conn.execute("ALTER TABLE events ADD COLUMN episode_id INTEGER;")

    # index for episode timeline
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_episode_date ON events(episode_id, date);")

    conn.commit()