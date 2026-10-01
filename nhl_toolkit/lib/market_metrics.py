"""
Derives one metric -- market_edge -- from the `odds` table: how many
points the betting market favors a team by (the negative of its own
spread, so higher = more favored, consistent with every other metric's
"higher is better" convention -- a team favored by 1.5 gets +1.5, the
underdog gets -1.5).

This exists because none of the schedule/travel/form metrics reflect
real-world information the betting market prices in (injuries, goalie
starts, line movement, public money). Like every other metric, its
weight in policy.yaml determines how much it actually sways
total_score -- this is one signal among several feeding the sum, not
an override of the others, and not the same thing as grading a pick
against the spread after the fact (see grade.py).

A (game, team) pair with no odds quote on record (no ODDS_API_KEY set
that day, or a game nobody's posted a line for yet) simply gets no
value here -- same as every other metric, it just doesn't contribute
to that team's total_score rather than erroring.

Run this after fetch_odds.py has updated `odds`. Like the other metric
builders, it fully deletes and rebuilds the metric_values rows it owns
each run (idempotent).

Usage:
    python lib/market_metrics.py
"""

import sqlite3
from collections import defaultdict

from db import get_connection, init_db
from metrics import seed_metrics

MARKET_METRICS = [
    (
        "market_edge",
        "Betting market's implied edge for this team (negative of its own spread)",
        "points",
    ),
]


def compute_market_edge(conn: sqlite3.Connection) -> list:
    """Average each bookmaker's latest spread quote per team, sign-flipped.

    Mirrors report.py's latest_consensus_spread (same "latest quote per
    bookmaker, then average" logic), computed in bulk for both teams across
    every game at once instead of one (game, team) pair at a time.

    :param conn: Open connection to the schedule database.
    :returns: (game_id, team_id, market_edge) tuples, one per team with a quote.
    """
    rows = conn.execute(
        """
        SELECT o.game_id, g.home_team, g.away_team, o.home_spread, o.away_spread
        FROM odds o
        JOIN games g ON g.game_id = o.game_id
        WHERE o.fetched_at = (
            SELECT MAX(o2.fetched_at) FROM odds o2
            WHERE o2.game_id = o.game_id AND o2.source = o.source
        )
        """
    ).fetchall()

    home_quotes: dict = defaultdict(list)
    away_quotes: dict = defaultdict(list)
    teams_by_game: dict = {}
    for game_id, home_team, away_team, home_spread, away_spread in rows:
        teams_by_game[game_id] = (home_team, away_team)
        if home_spread is not None:
            home_quotes[game_id].append(home_spread)
        if away_spread is not None:
            away_quotes[game_id].append(away_spread)

    values = []
    for game_id, (home_team, away_team) in teams_by_game.items():
        if home_quotes[game_id]:
            consensus = sum(home_quotes[game_id]) / len(home_quotes[game_id])
            values.append((game_id, home_team, -consensus))
        if away_quotes[game_id]:
            consensus = sum(away_quotes[game_id]) / len(away_quotes[game_id])
            values.append((game_id, away_team, -consensus))
    return values


def rebuild_market_metrics() -> None:
    """Seed the market_edge metric and repopulate its values from `odds`."""
    init_db()
    conn = get_connection()
    with conn:
        metric_ids = seed_metrics(conn, MARKET_METRICS)
        metric_id = metric_ids["market_edge"]
        conn.execute("DELETE FROM metric_values WHERE metric_id = ?", (metric_id,))

        values = compute_market_edge(conn)
        conn.executemany(
            """
            INSERT INTO metric_values (game_id, team_id, metric_id, value)
            VALUES (?, ?, ?, ?)
            """,
            [(game_id, team_id, metric_id, value) for game_id, team_id, value in values],
        )
    conn.close()
    print(f"Wrote {len(values)} metric_values rows for market_edge.")


if __name__ == "__main__":
    rebuild_market_metrics()
