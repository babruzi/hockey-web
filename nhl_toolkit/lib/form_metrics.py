"""
Derives two performance metrics that nothing else in the pipeline
captures: recent form (win percentage over a team's last N completed
games) and goal differential (average goal margin over that same
window). Unlike travel_metrics.py, there's no separate context table --
these are simple trailing stats computed straight from `games` and
written directly into metric_values, using the same
seed-then-populate pattern as metrics.py.

Only completed games (game_state 'OFF', per the NHL Web API) update the
rolling window, but a metric_values row is written for every game on
record (including future ones), so an upcoming game gets scored using
form built from games already played -- there's no lookahead into the
game being scored.

Run this after fetch_schedule.py has updated scores. Like the other
metric builders, it fully deletes and rebuilds the metric_values rows
it owns each run (idempotent).

Usage:
    python lib/form_metrics.py
"""

import sqlite3
from collections import deque
from typing import Optional

from db import get_connection, init_db
from metrics import seed_metrics
from travel_metrics import all_team_abbrevs

FORM_WINDOW = 10

# The NHL Web API uses "OFF" for a completed/official game, not "FINAL"
# (despite what db.py's schema comment suggests) -- "FINAL" is kept here
# too as a defensive fallback in case that ever changes upstream.
COMPLETED_STATES = ("OFF", "FINAL")

FORM_METRICS = [
    ("recent_form", f"Win percentage over the last {FORM_WINDOW} completed games", "win_pct"),
    (
        "goal_differential",
        f"Average goal margin over the last {FORM_WINDOW} completed games",
        "goals",
    ),
]


def compute_for_team(conn: sqlite3.Connection, team_abbrev: str) -> list[tuple]:
    """Compute recent_form and goal_differential for every game a team has on record.

    :param conn: Open connection to the schedule database.
    :param team_abbrev: The team's 3-letter NHL API abbreviation.
    :returns: (game_id, team_id, recent_form, goal_differential) rows, chronological.
    """
    rows = conn.execute(
        """
        SELECT game_id, home_team, away_team, game_state, home_score, away_score
        FROM games
        WHERE (home_team = ? OR away_team = ?) AND game_date IS NOT NULL
        ORDER BY game_date ASC, game_id ASC
        """,
        (team_abbrev, team_abbrev),
    ).fetchall()

    results: deque = deque(maxlen=FORM_WINDOW)
    goal_diffs: deque = deque(maxlen=FORM_WINDOW)
    output = []

    for game_id, home_team, _away_team, game_state, home_score, away_score in rows:
        is_home = home_team == team_abbrev

        recent_form: Optional[float] = sum(results) / len(results) if results else None
        goal_differential: Optional[float] = (
            sum(goal_diffs) / len(goal_diffs) if goal_diffs else None
        )
        output.append((game_id, team_abbrev, recent_form, goal_differential))

        if game_state in COMPLETED_STATES and home_score is not None and away_score is not None:
            team_score = home_score if is_home else away_score
            opp_score = away_score if is_home else home_score
            results.append(1.0 if team_score > opp_score else 0.0)
            goal_diffs.append(team_score - opp_score)

    return output


def rebuild_form_metrics() -> None:
    """Seed the recent_form/goal_differential metrics and repopulate their values."""
    init_db()
    conn = get_connection()
    with conn:
        metric_ids = seed_metrics(conn, FORM_METRICS)
        form_metric_ids = (metric_ids["recent_form"], metric_ids["goal_differential"])
        conn.execute(
            "DELETE FROM metric_values WHERE metric_id IN (?, ?)",
            form_metric_ids,
        )

        total = 0
        for team in all_team_abbrevs(conn):
            rows = compute_for_team(conn, team)
            values_rows = [
                (game_id, team_id, metric_ids["recent_form"], recent_form)
                for game_id, team_id, recent_form, _goal_differential in rows
            ] + [
                (game_id, team_id, metric_ids["goal_differential"], goal_differential)
                for game_id, team_id, _recent_form, goal_differential in rows
            ]
            conn.executemany(
                """
                INSERT INTO metric_values (game_id, team_id, metric_id, value)
                VALUES (?, ?, ?, ?)
                """,
                values_rows,
            )
            total += len(values_rows)
    conn.close()
    print(f"Wrote {total} metric_values rows for recent_form/goal_differential.")


if __name__ == "__main__":
    rebuild_form_metrics()
