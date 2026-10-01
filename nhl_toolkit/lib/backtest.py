"""
Diagnostic backtest over graded history: for every metric currently in
the `metrics` table, correlates that metric's home-minus-away
differential against the actual goal margin across every completed
game, to see which metrics the data actually supports and which are
dead weight in policy.yaml. Also reports picks_log's real record
(straight-up and against the spread) per policy_version that's
actually been scored.

This never hardcodes a metric name -- it reads whatever rows exist in
`metrics`, so a brand-new metric (injuries, head-to-head, goalie
quality, ...) shows up here automatically the first time this runs
after something starts writing metric_values for it. No code changes
needed here when a metric gets added.

This is a read-only analysis tool, not an auto-tuner: it never writes
to policy.yaml. Treat a metric's correlation as a hint for hand-tuning
its weight, not a verdict -- a metric correlating with goal margin and
being correctly weighted *relative to every other metric* are different
questions, and early-season sample sizes are small (see --min-n).

Usage:
    python lib/backtest.py
    python lib/backtest.py --min-n 20   # hide metrics below this sample size
"""

import argparse
import sqlite3
from typing import Optional

from db import get_connection, init_db
from score import load_policy

DEFAULT_MIN_N = 10


def pearson_r(xs: list, ys: list) -> Optional[float]:
    """Pearson correlation coefficient, computed by hand (stdlib-only, no numpy).

    :param xs: First variable's values.
    :param ys: Second variable's values, same length and order as xs.
    :returns: r in [-1, 1], or None with fewer than 2 points or a constant variable.
    """
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0 or var_y == 0:
        return None
    return cov / (var_x * var_y) ** 0.5


def metric_margin_pairs(conn: sqlite3.Connection, metric_id: int) -> tuple:
    """A metric's (home - away) differential and the actual goal margin, per completed game.

    :param conn: Open connection to the schedule database.
    :param metric_id: Metric to pull values for.
    :returns: (diffs, margins), paired and same length -- one entry per game
        where both teams have a value for this metric.
    """
    rows = conn.execute(
        """
        SELECT mv.game_id, mv.team_id, mv.value, g.home_team, g.away_team,
               g.home_score, g.away_score
        FROM metric_values mv
        JOIN games g ON g.game_id = mv.game_id
        WHERE mv.metric_id = ?
          AND g.game_state = 'OFF'
          AND g.home_score IS NOT NULL
          AND g.away_score IS NOT NULL
          AND mv.value IS NOT NULL
        """,
        (metric_id,),
    ).fetchall()

    by_game: dict = {}
    for game_id, team_id, value, home_team, away_team, home_score, away_score in rows:
        game = by_game.setdefault(
            game_id,
            {
                "home_team": home_team,
                "away_team": away_team,
                "margin": home_score - away_score,
                "values": {},
            },
        )
        game["values"][team_id] = value

    diffs, margins = [], []
    for game in by_game.values():
        home_value = game["values"].get(game["home_team"])
        away_value = game["values"].get(game["away_team"])
        if home_value is None or away_value is None:
            continue
        diffs.append(home_value - away_value)
        margins.append(game["margin"])
    return diffs, margins


def metric_report(conn: sqlite3.Connection) -> list:
    """Correlate every metric in `metrics` against actual goal margin.

    :param conn: Open connection to the schedule database.
    :returns: One dict per metric: name, n, correlation, and its current
        policy.yaml weight/normalize (None if the metric isn't in policy.yaml).
    """
    policy_settings = load_policy()["metrics"]
    metrics = conn.execute("SELECT metric_id, name FROM metrics ORDER BY metric_id").fetchall()

    report = []
    for metric_id, name in metrics:
        diffs, margins = metric_margin_pairs(conn, metric_id)
        settings = policy_settings.get(name)
        report.append(
            {
                "name": name,
                "n": len(diffs),
                "correlation": pearson_r(diffs, margins),
                "weight": settings["weight"] if settings else None,
                "normalize": settings["normalize"] if settings else None,
                "in_policy": settings is not None,
            }
        )
    return report


def policy_performance(conn: sqlite3.Connection) -> list:
    """picks_log's real record, straight-up and against the spread, per policy_version.

    Joined through daily_scores (picks_log itself doesn't store policy_version)
    so that comparing performance before/after a policy.yaml weight change is
    possible once more than one policy_version has actually been scored.

    :param conn: Open connection to the schedule database.
    :returns: One dict per policy_version with win/loss/push counts.
    """
    rows = conn.execute(
        """
        SELECT ds.policy_version,
               SUM(CASE WHEN p.straight_up_result = 'win' THEN 1 ELSE 0 END),
               SUM(CASE WHEN p.straight_up_result = 'loss' THEN 1 ELSE 0 END),
               SUM(CASE WHEN p.result = 'win' THEN 1 ELSE 0 END),
               SUM(CASE WHEN p.result = 'loss' THEN 1 ELSE 0 END),
               SUM(CASE WHEN p.result = 'push' THEN 1 ELSE 0 END),
               SUM(p.profit_100),
               SUM(CASE WHEN p.profit_100 IS NOT NULL THEN 1 ELSE 0 END)
        FROM picks_log p
        JOIN daily_scores ds
          ON ds.date = p.date AND ds.game_id = p.game_id AND ds.team_id = p.pick
        GROUP BY ds.policy_version
        ORDER BY ds.policy_version
        """
    ).fetchall()
    return [
        {
            "policy_version": policy_version,
            "su_wins": su_wins,
            "su_losses": su_losses,
            "ats_wins": ats_wins,
            "ats_losses": ats_losses,
            "ats_pushes": ats_pushes,
            "total_profit_100": total_profit_100,
            "graded_bet_count": graded_bet_count,
        }
        for (
            policy_version,
            su_wins,
            su_losses,
            ats_wins,
            ats_losses,
            ats_pushes,
            total_profit_100,
            graded_bet_count,
        ) in rows
    ]


def _pct(wins: int, losses: int) -> str:
    total = wins + losses
    return f"{wins}-{losses} ({100 * wins / total:.1f}%)" if total else "0-0 (n/a)"


def print_backtest_report(report: list, performance: list, min_n: int) -> None:
    """Print the metric-correlation table and the policy performance summary.

    :param report: Rows from :func:`metric_report`.
    :param performance: Rows from :func:`policy_performance`.
    :param min_n: Metrics with fewer completed-game samples than this are
        flagged as too thin to draw a conclusion from, not hidden outright.
    """
    print("\nMetric vs. actual goal-margin correlation")
    print("-" * 88)
    print(f"{'metric':<22}{'n':>5}{'corr':>8}{'weight':>9}{'normalize':>11}  note")

    def sort_key(row):
        r = row["correlation"]
        return (r is None, -abs(r) if r is not None else 0)

    for row in sorted(report, key=sort_key):
        corr_str = f"{row['correlation']:+.3f}" if row["correlation"] is not None else "n/a"
        weight_str = f"{row['weight']:+.2f}" if row["weight"] is not None else "n/a"
        normalize_str = row["normalize"] or "n/a"

        notes = []
        if row["n"] < min_n:
            notes.append(f"only {row['n']} games -- too little data to trust yet")
        if not row["in_policy"]:
            notes.append("not in policy.yaml -- candidate to add")
        elif (
            row["correlation"] is not None
            and row["n"] >= min_n
            and row["weight"] != 0
            and (row["correlation"] > 0) != (row["weight"] > 0)
        ):
            notes.append("weight sign disagrees with correlation!")

        print(
            f"{row['name']:<22}{row['n']:>5}{corr_str:>8}{weight_str:>9}"
            f"{normalize_str:>11}  {'; '.join(notes)}"
        )

    print("\nPicks_log record by policy_version")
    print("-" * 88)
    if not performance:
        print("No graded picks yet.")
        return
    for row in performance:
        su = _pct(row["su_wins"], row["su_losses"])
        ats = _pct(row["ats_wins"], row["ats_losses"])
        push_note = f", {row['ats_pushes']} push" if row["ats_pushes"] else ""
        bet_count = row["graded_bet_count"]
        if bet_count:
            profit = row["total_profit_100"]
            roi_pct = 100 * profit / (100 * bet_count)
            roi_note = f" | moneyline ROI {profit:+.2f} on {bet_count} bets ({roi_pct:+.1f}%)"
        else:
            roi_note = " | moneyline ROI n/a (no odds on any graded pick)"
        print(f"{row['policy_version']}: straight-up {su} | vs. spread {ats}{push_note}{roi_note}")


def build_backtest_report(min_n: int = DEFAULT_MIN_N) -> None:
    """Run the full backtest and print it.

    :param min_n: Sample-size threshold below which a metric's correlation gets flagged.
    """
    init_db()
    conn = get_connection()
    with conn:
        report = metric_report(conn)
        performance = policy_performance(conn)
    conn.close()
    print_backtest_report(report, performance, min_n)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backtest policy.yaml metrics against actual game outcomes"
    )
    parser.add_argument(
        "--min-n",
        type=int,
        default=DEFAULT_MIN_N,
        help="Sample-size threshold below which a metric's correlation is flagged as thin",
    )
    args = parser.parse_args()
    build_backtest_report(args.min_n)
