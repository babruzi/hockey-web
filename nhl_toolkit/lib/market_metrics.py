"""
Derives one metric -- market_edge -- from the `odds` table: each team's
devigged, market-implied win probability, from DraftKings' moneyline
(PRIMARY_BOOK) when it has posted a line, falling back to a cross-book
average otherwise -- see compute_market_edge.

This was originally built from the puck-line spread (the negative of a
team's own spread), but that turned out to carry almost no signal: NHL
puck lines are set at a fixed 1.5 goals in practice -- every quote this
pipeline has ever recorded is exactly -1.5 or +1.5, never anything in
between. All of the market's actual opinion about *how much* it favors
a team (not just *which* team) lives in the moneyline instead -- e.g.
a -218/+180 moneyline says something very different from a -115/-105
one, even though both games would show the identical +-1.5 spread.
Converting the moneyline to a probability and removing the
bookmaker's overround (vig) gives a continuous 0-1 value instead of
a near-constant one.

Like every other metric, its weight in policy.yaml determines how much
it actually sways total_score -- this is one signal among several
feeding the sum, not an override of the others, and not the same thing
as grading a pick against the spread after the fact (see grade.py).

A (game, team) pair with no moneyline quote on record (no
ODDS_API_KEY set that day, or a game nobody's posted a line for yet)
simply gets no value here -- same as every other metric, it just
doesn't contribute to that team's total_score rather than erroring.

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

# Kept in sync with report.py's PRIMARY_BOOK by hand rather than imported --
# report.py imports american_to_probability from this module, so importing
# the other way round would be circular.
PRIMARY_BOOK = "draftkings"

MARKET_METRICS = [
    (
        "market_edge",
        "Betting market's devigged implied win probability for this team (from moneyline)",
        "win_pct",
    ),
]


def american_to_probability(odds: int) -> float:
    """Convert American odds to a raw (not yet devigged) implied win probability.

    :param odds: American odds, e.g. -142 or +180.
    :returns: Implied probability in (0, 1); sums to > 1 across both sides
        of a market before devigging, since it still includes the vig.
    """
    if odds < 0:
        return -odds / (-odds + 100)
    return 100 / (odds + 100)


def _devig(home_ml: int, away_ml: int) -> tuple:
    """Devig one bookmaker's pair of moneylines into (home_prob, away_prob).

    :param home_ml: Home team's American moneyline.
    :param away_ml: Away team's American moneyline.
    :returns: (home_prob, away_prob), summing to exactly 1.0.
    """
    home_raw = american_to_probability(home_ml)
    away_raw = american_to_probability(away_ml)
    overround = home_raw + away_raw
    return home_raw / overround, away_raw / overround


def compute_market_edge(conn: sqlite3.Connection) -> list:
    """DraftKings' own moneyline per team, devigged -- these are the lines
    actually meant to be bet, so PRIMARY_BOOK's quote is used directly
    rather than blended with others. Falls back to a cross-book average
    (each bookmaker's latest quote devigged individually, then averaged)
    only for a game DraftKings hasn't posted a line for yet. A bookmaker's
    quote only counts if it has both sides' moneylines -- devigging needs
    both to remove the overround.

    :param conn: Open connection to the schedule database.
    :returns: (game_id, team_id, market_edge) tuples, one per team with a quote.
    """
    rows = conn.execute(
        """
        SELECT o.game_id, o.source, g.home_team, g.away_team, o.home_ml, o.away_ml
        FROM odds o
        JOIN games g ON g.game_id = o.game_id
        WHERE o.fetched_at = (
            SELECT MAX(o2.fetched_at) FROM odds o2
            WHERE o2.game_id = o.game_id AND o2.source = o.source
        )
        """
    ).fetchall()

    quotes_by_game: dict = defaultdict(dict)
    for game_id, source, home_team, away_team, home_ml, away_ml in rows:
        if home_ml is not None and away_ml is not None:
            quotes_by_game[game_id][source] = (home_team, away_team, home_ml, away_ml)

    values = []
    for game_id, quotes in quotes_by_game.items():
        sources = [PRIMARY_BOOK] if PRIMARY_BOOK in quotes else list(quotes)

        home_probs, away_probs = [], []
        home_team = away_team = None
        for source in sources:
            home_team, away_team, home_ml, away_ml = quotes[source]
            home_prob, away_prob = _devig(home_ml, away_ml)
            home_probs.append(home_prob)
            away_probs.append(away_prob)

        values.append((game_id, home_team, sum(home_probs) / len(home_probs)))
        values.append((game_id, away_team, sum(away_probs) / len(away_probs)))
    return values


def rebuild_market_metrics() -> None:
    """Seed the market_edge metric and repopulate its values from `odds`."""
    init_db()
    conn = get_connection()
    with conn:
        metric_ids = seed_metrics(conn, MARKET_METRICS)
        metric_id = metric_ids["market_edge"]
        # seed_metrics only inserts a metric the first time it's seen (INSERT
        # OR IGNORE) -- this keeps the catalog's description/unit current for
        # anyone who already had the old spread-based version seeded.
        conn.execute(
            "UPDATE metrics SET description = ?, unit = ? WHERE metric_id = ?",
            (MARKET_METRICS[0][1], MARKET_METRICS[0][2], metric_id),
        )
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
