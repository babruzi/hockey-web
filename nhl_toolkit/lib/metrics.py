"""
Bridges the fixed-column `schedule_context` table into the generic
metrics/metric_values schema, so the policy engine only ever has to
know about "named metrics with values" -- never about specific
schedule_context columns. Adding a future metric (injuries, recent
form, odds movement) means adding rows here or elsewhere, not changing
this module or the policy engine.

Run this after travel_metrics.py has rebuilt `schedule_context`. Like
that script, it fully deletes and rebuilds the metric_values rows it
owns each run (idempotent).

Usage:
    python lib/metrics.py
"""

import sqlite3

from db import get_connection, init_db

# (name, description, unit) -- the metrics this module derives from
# schedule_context. Each name must match a column below in
# SCHEDULE_CONTEXT_COLUMNS.
SCHEDULE_METRICS = [
    ("rest_days", "Days of rest since the team's previous game", "days"),
    ("games_last_7", "Games played in the trailing 7 days", "count"),
    ("games_last_14", "Games played in the trailing 14 days", "count"),
    ("games_last_30", "Games played in the trailing 30 days", "count"),
    ("distance_traveled_km", "Distance traveled since the previous game", "km"),
    ("timezones_crossed", "Timezone shift since the previous game", "hours"),
    ("back_to_back", "Playing on zero days of rest", "bool"),
    ("home_ice", "Playing at home", "bool"),
]

# Maps metric name -> schedule_context column it's sourced from.
SCHEDULE_CONTEXT_COLUMNS = {
    "rest_days": "rest_days",
    "games_last_7": "games_last_7",
    "games_last_14": "games_last_14",
    "games_last_30": "games_last_30",
    "distance_traveled_km": "distance_traveled_km",
    "timezones_crossed": "timezones_crossed",
    "back_to_back": "back_to_back",
    "home_ice": "is_home",
}


def seed_metrics(conn: sqlite3.Connection, catalog: list[tuple]) -> dict[str, int]:
    """Insert any missing metrics from the catalog and return name -> metric_id.

    :param conn: Open connection to the schedule database.
    :param catalog: (name, description, unit) tuples to ensure exist.
    :returns: Mapping of metric name to its metric_id.
    """
    conn.executemany(
        "INSERT OR IGNORE INTO metrics (name, description, unit) VALUES (?, ?, ?)",
        catalog,
    )
    rows = conn.execute("SELECT name, metric_id FROM metrics").fetchall()
    return {name: metric_id for name, metric_id in rows}


def compute_schedule_metric_values(conn: sqlite3.Connection, metric_ids: dict[str, int]) -> int:
    """Rebuild metric_values rows sourced from schedule_context.

    :param conn: Open connection to the schedule database.
    :param metric_ids: Mapping of metric name to metric_id, from :func:`seed_metrics`.
    :returns: Number of metric_values rows written.
    """
    schedule_metric_ids = [metric_ids[name] for name in SCHEDULE_CONTEXT_COLUMNS]
    placeholders = ",".join("?" * len(schedule_metric_ids))
    conn.execute(
        f"DELETE FROM metric_values WHERE metric_id IN ({placeholders})",
        schedule_metric_ids,
    )

    columns = ", ".join(SCHEDULE_CONTEXT_COLUMNS.values())
    rows = conn.execute(f"SELECT game_id, team_id, {columns} FROM schedule_context").fetchall()

    values_rows = []
    for row in rows:
        game_id, team_id = row[0], row[1]
        for metric_name, value in zip(SCHEDULE_CONTEXT_COLUMNS, row[2:]):
            values_rows.append((game_id, team_id, metric_ids[metric_name], value))

    conn.executemany(
        """
        INSERT INTO metric_values (game_id, team_id, metric_id, value)
        VALUES (?, ?, ?, ?)
        """,
        values_rows,
    )
    return len(values_rows)


def rebuild_schedule_metrics() -> None:
    """Seed the schedule-derived metrics catalog and repopulate their values."""
    init_db()
    conn = get_connection()
    with conn:
        metric_ids = seed_metrics(conn, SCHEDULE_METRICS)
        written = compute_schedule_metric_values(conn, metric_ids)
    conn.close()
    print(f"Seeded {len(SCHEDULE_METRICS)} metrics; wrote {written} metric_values rows.")


if __name__ == "__main__":
    rebuild_schedule_metrics()
