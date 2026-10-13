"""
Derives a single `injury_edge` metric from the `injuries` table: a
team-level health score for a game, higher being healthier (fewer/less
severe injuries), using the same seed-then-populate pattern as
metrics.py/form_metrics.py.

Unlike recent_form/goal_differential, this metric has no lookahead
problem to solve by construction -- it isn't derived from `games` at
all, just from whatever `injuries` snapshots are on record. For a given
game, the snapshot used is the most recent one fetched at or before that
game's date, so a future game gets today's injury picture and a past
game gets whatever was captured on or before it (sparse until this
table accumulates history, since fetch_injuries.py only started running
once this module was built -- there's no way to backfill a team's injury
list from a date before this existed).

Severity weighting is a simple, admittedly crude proxy (no roster
salary/ice-time data exists in this schema to weigh who specifically is
hurt): each injury contributes a status-based weight, doubled if the
player is a goalie (position 'G') on the theory that losing a starting
goalie matters more than losing a bottom-six forward, which this schema
otherwise has no way to tell apart. This has not been backtested yet
(see policy.yaml's injury_edge comment) -- treat the weights below as a
starting guess, not a validated one.

Run this after fetch_injuries.py. Like the other metric builders, it
fully deletes and rebuilds the metric_values rows it owns each run
(idempotent).

Usage:
    python lib/injury_metrics.py
"""

import sqlite3
from typing import Optional

from db import get_connection, init_db
from metrics import seed_metrics
from travel_metrics import all_team_abbrevs

INJURY_METRICS = [
    ("injury_edge", "Health score from current injuries (higher = healthier)", "severity"),
]

STATUS_WEIGHT = {
    "Out": 3.0,
    "Day-To-Day": 1.0,
    "Injured Reserve": 2.0,
    "Suspension": 2.0,
}
GOALIE_MULTIPLIER = 2.0


def latest_injury_fetch_at_or_before(conn: sqlite3.Connection, as_of_date: str) -> Optional[str]:
    """The timestamp of the most recent league-wide injury fetch at or before a date.

    ESPN's response omits any team with zero current injuries entirely, so a
    healthy team already covered by a fetch and a team that's never been
    fetched both have zero rows *for that team* -- the only way to tell them
    apart is to check whether *any* fetch happened by this date (one fetch
    call always covers the whole league in a single pass), not whether this
    specific team has rows.

    :param conn: Open connection to the schedule database.
    :param as_of_date: Date to look back from, as YYYY-MM-DD.
    :returns: The fetch's `fetched_at` timestamp, or None if no fetch has
        ever happened at or before this date.
    """
    return conn.execute(
        "SELECT MAX(fetched_at) FROM injuries WHERE fetched_at <= ?",
        (f"{as_of_date}T23:59:59",),
    ).fetchone()[0]


def latest_snapshot_at_or_before(
    conn: sqlite3.Connection, team: str, as_of_date: str
) -> Optional[list[tuple]]:
    """The most recent injury snapshot for a team at or before a given date.

    :param conn: Open connection to the schedule database.
    :param team: Team abbreviation.
    :param as_of_date: Date to look back from, as YYYY-MM-DD.
    :returns: (status, position) rows from that snapshot (empty list means a
        snapshot exists and the team had zero injuries on it), or None if no
        snapshot has ever been fetched at or before this date -- that's a
        "no data" case, not "healthy," and must not be scored as 0.
    """
    latest_fetch = latest_injury_fetch_at_or_before(conn, as_of_date)
    if latest_fetch is None:
        return None
    return conn.execute(
        "SELECT status, position FROM injuries WHERE team = ? AND fetched_at = ?",
        (team, latest_fetch),
    ).fetchall()


def severity_score(injury_rows: list[tuple]) -> float:
    """Sum a status/position-weighted severity across a team's current injuries.

    :param injury_rows: (status, position) rows from one snapshot.
    :returns: Total severity (0 if healthy; higher means more/worse injuries).
    """
    total = 0.0
    for status, position in injury_rows:
        weight = STATUS_WEIGHT.get(status, 1.0)
        if position == "G":
            weight *= GOALIE_MULTIPLIER
        total += weight
    return total


def rebuild_injury_metrics() -> None:
    """Seed injury_edge and repopulate its metric_values for every game on record."""
    init_db()
    conn = get_connection()
    with conn:
        metric_ids = seed_metrics(conn, INJURY_METRICS)
        injury_edge_id = metric_ids["injury_edge"]
        conn.execute("DELETE FROM metric_values WHERE metric_id = ?", (injury_edge_id,))

        has_any_snapshot = conn.execute("SELECT 1 FROM injuries LIMIT 1").fetchone() is not None
        if not has_any_snapshot:
            conn.close()
            print("No injury snapshots on record yet; wrote 0 metric_values rows.")
            return

        total = 0
        for team in all_team_abbrevs(conn):
            games = conn.execute(
                "SELECT game_id, game_date FROM games WHERE home_team = ? OR away_team = ?",
                (team, team),
            ).fetchall()
            values_rows = []
            for game_id, game_date in games:
                injury_rows = latest_snapshot_at_or_before(conn, team, game_date)
                value = -severity_score(injury_rows) if injury_rows is not None else None
                values_rows.append((game_id, team, injury_edge_id, value))
            conn.executemany(
                """
                INSERT INTO metric_values (game_id, team_id, metric_id, value)
                VALUES (?, ?, ?, ?)
                """,
                values_rows,
            )
            total += len(values_rows)
    conn.close()
    print(f"Wrote {total} injury_edge metric_values rows.")


if __name__ == "__main__":
    rebuild_injury_metrics()
