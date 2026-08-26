"""
Database setup. Starts on SQLite (zero-config, single file) so you can
run everything locally today; the schema is plain-enough SQL that
moving to Postgres later is a straight `pg_dump`-style port, not a
rewrite.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "nhl.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    game_id         INTEGER PRIMARY KEY,   -- NHL's own gamePk/id
    game_date       TEXT NOT NULL,         -- YYYY-MM-DD, local game date
    start_time_utc  TEXT,
    home_team       TEXT NOT NULL,         -- abbrev, e.g. 'BOS'
    away_team       TEXT NOT NULL,
    home_score      INTEGER,
    away_score      INTEGER,
    game_state      TEXT,                  -- 'FUT', 'LIVE', 'OFF' (completed), etc.
    venue           TEXT
);

CREATE TABLE IF NOT EXISTS schedule_context (
    game_id             INTEGER NOT NULL,
    team_id             TEXT NOT NULL,      -- abbrev
    is_home             INTEGER NOT NULL,   -- 1/0
    rest_days           REAL,
    games_last_7        INTEGER,
    games_last_14        INTEGER,
    games_last_30        INTEGER,
    distance_traveled_km REAL,
    timezones_crossed    REAL,
    back_to_back         INTEGER,           -- 1/0
    PRIMARY KEY (game_id, team_id),
    FOREIGN KEY (game_id) REFERENCES games (game_id)
);

CREATE TABLE IF NOT EXISTS odds (
    odds_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id      INTEGER NOT NULL,
    source       TEXT NOT NULL,        -- bookmaker key, e.g. 'draftkings'
    fetched_at   TEXT NOT NULL,        -- ISO timestamp of this snapshot
    home_spread  REAL,
    away_spread  REAL,
    home_ml      INTEGER,
    away_ml      INTEGER,
    total        REAL,
    over_odds    INTEGER,
    under_odds   INTEGER,
    FOREIGN KEY (game_id) REFERENCES games (game_id)
);

CREATE TABLE IF NOT EXISTS metrics (
    metric_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    description  TEXT,
    unit         TEXT,
    active       INTEGER NOT NULL DEFAULT 1   -- 1/0
);

CREATE TABLE IF NOT EXISTS metric_values (
    game_id    INTEGER NOT NULL,
    team_id    TEXT NOT NULL,          -- abbrev
    metric_id  INTEGER NOT NULL,
    value      REAL,
    PRIMARY KEY (game_id, team_id, metric_id),
    FOREIGN KEY (game_id) REFERENCES games (game_id),
    FOREIGN KEY (metric_id) REFERENCES metrics (metric_id)
);

CREATE TABLE IF NOT EXISTS policy_weights (
    policy_version  TEXT NOT NULL,
    metric_id       INTEGER NOT NULL,
    weight          REAL NOT NULL,
    normalize       TEXT NOT NULL DEFAULT 'none',  -- 'minmax' | 'zscore' | 'none'
    PRIMARY KEY (policy_version, metric_id),
    FOREIGN KEY (metric_id) REFERENCES metrics (metric_id)
);

CREATE TABLE IF NOT EXISTS daily_scores (
    date            TEXT NOT NULL,     -- YYYY-MM-DD
    game_id         INTEGER NOT NULL,
    team_id         TEXT NOT NULL,     -- abbrev
    total_score     REAL NOT NULL,
    rank            INTEGER,
    policy_version  TEXT NOT NULL,
    PRIMARY KEY (date, game_id, team_id, policy_version),
    FOREIGN KEY (game_id) REFERENCES games (game_id)
);

CREATE TABLE IF NOT EXISTS picks_log (
    pick_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date            TEXT NOT NULL,     -- YYYY-MM-DD, date the pick was made
    game_id         INTEGER NOT NULL,
    pick            TEXT NOT NULL,     -- team abbrev picked
    predicted_edge  REAL,              -- score gap between the two teams
    spread_at_pick  REAL,              -- picked team's spread when logged
    result          TEXT,              -- 'win' | 'loss' | 'push', NULL until graded
    graded_at       TEXT,
    FOREIGN KEY (game_id) REFERENCES games (game_id)
);

CREATE INDEX IF NOT EXISTS idx_games_date ON games (game_date);
CREATE INDEX IF NOT EXISTS idx_ctx_team ON schedule_context (team_id);
CREATE INDEX IF NOT EXISTS idx_odds_game ON odds (game_id);
CREATE INDEX IF NOT EXISTS idx_metric_values_metric ON metric_values (metric_id);
CREATE INDEX IF NOT EXISTS idx_daily_scores_date ON daily_scores (date);
CREATE INDEX IF NOT EXISTS idx_picks_log_date ON picks_log (date);
"""


def get_connection() -> sqlite3.Connection:
    """Open a connection to the local SQLite database with foreign keys enabled.

    :returns: An open connection ready for queries.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db() -> None:
    """Create the database file and apply the schema if not already present."""
    conn = get_connection()
    with conn:
        conn.executescript(SCHEMA)
    conn.close()
    print(f"Database ready at {DB_PATH}")


if __name__ == "__main__":
    init_db()
