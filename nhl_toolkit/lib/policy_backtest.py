"""
Replays every completed game's scoring under every policy_version that
has ever been synced into `policy_weights` -- not just whichever one
was actually live on a given day -- so different weight configurations
can be compared head-to-head against the exact same full slate of
history, instead of each only ever being judged on the (different,
non-overlapping) stretch of the season it happened to be live for.

Read-only and side-effect-free: never writes to `daily_scores` or
`picks_log`, which represent what was actually live and bet on at the
time -- this is a separate "what if every game this season had been
scored under policy X" simulation. Reuses `score.py`'s own
`compute_scores()` for the actual scoring math, so a policy's simulated
picks here are computed exactly the same way real picks are, not by a
parallel reimplementation that could silently drift from it.

Scalable to new policies with zero code changes: every policy_version
ever synced into `policy_weights` (which happens automatically any time
score.py runs with a changed policy.yaml) is picked up here the next
time this runs -- there's nothing to register or configure per policy.
Only scores the Money Line pick under each policy; Puck Line/Over-Under
aren't policy.yaml-driven (same recommendation regardless of policy), so
backtest.py's bet_type_totals() already covers those on their own.

Usage:
    python lib/policy_backtest.py
"""

from typing import Optional

from db import COMPLETED_STATES, get_connection, init_db
from grade import STAKE, odds_profit
from report import (
    latest_consensus_moneyline,
    latest_consensus_spread,
    latest_consensus_spread_price,
)
from score import compute_scores, load_policy

# Minimum predicted edge for the live-policy section of record.html.
# Derived differently from report.py's DEFAULT_MIN_EDGE (0.9, from sweeping
# thresholds against the full season-backfilled history, most of which has
# no odds): this one came from sweeping thresholds against just this
# season's odds-covered games under the live policy specifically, where
# 1.0 gave the best combination of win rate (76.2%) and sample size (21
# games) -- 1.2 had a slightly worse rate on fewer games, lower thresholds
# had worse rates on more games.
LIVE_POLICY_MIN_EDGE = 1.0


def all_policy_versions(conn) -> list[str]:
    """Every policy_version that's ever been synced into policy_weights.

    :param conn: Open connection to the schedule database.
    :returns: policy_version strings, lexicographically sorted (oldest first).
    """
    return [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT policy_version FROM policy_weights ORDER BY policy_version"
        ).fetchall()
    ]


def completed_games_by_date(conn) -> dict[str, list[tuple]]:
    """Every completed game, grouped by date.

    :param conn: Open connection to the schedule database.
    :returns: {game_date: [(game_id, home_team, away_team, home_score, away_score), ...]}
    """
    state_placeholders = ",".join("?" * len(COMPLETED_STATES))
    rows = conn.execute(
        f"""
        SELECT game_date, game_id, home_team, away_team, home_score, away_score
        FROM games
        WHERE game_state IN ({state_placeholders})
          AND home_score IS NOT NULL AND away_score IS NOT NULL
        ORDER BY game_date
        """,
        COMPLETED_STATES,
    ).fetchall()
    games_by_date: dict[str, list[tuple]] = {}
    for game_date, game_id, home_team, away_team, home_score, away_score in rows:
        games_by_date.setdefault(game_date, []).append(
            (game_id, home_team, away_team, home_score, away_score)
        )
    return games_by_date


def games_with_odds(conn, games_by_date: dict[str, list[tuple]]) -> dict[str, list[tuple]]:
    """Restrict a games_by_date dict to games with at least one odds quote on record.

    In practice this restricts to the current season, since The Odds API's
    free tier never serves historical lines for a backfilled prior season
    -- but it's written as a generic "has odds" filter, not a date check,
    so it stays correct if that ever changes.

    :param conn: Open connection to the schedule database.
    :param games_by_date: Result of :func:`completed_games_by_date`.
    :returns: The same shape, with games that have no odds quote dropped.
    """
    odds_game_ids = {row[0] for row in conn.execute("SELECT DISTINCT game_id FROM odds")}
    filtered = {
        game_date: [game for game in games if game[0] in odds_game_ids]
        for game_date, games in games_by_date.items()
    }
    return {game_date: games for game_date, games in filtered.items() if games}


def _policy_weight_rows(conn, policy_version: str) -> list[tuple]:
    """The (name, metric_id, weight, normalize) rows compute_scores() needs for one policy.

    :param conn: Open connection to the schedule database.
    :param policy_version: Which policy_weights version to look up.
    :returns: Rows as compute_scores() expects them.
    """
    return conn.execute(
        """
        SELECT m.name, m.metric_id, pw.weight, pw.normalize
        FROM policy_weights pw JOIN metrics m ON m.metric_id = pw.metric_id
        WHERE pw.policy_version = ?
        """,
        (policy_version,),
    ).fetchall()


def _grade_simulated_game(conn, scores: dict, game: tuple, min_edge: float) -> Optional[dict]:
    """Score and grade one game under one date's already-computed scores.

    Shared by :func:`simulate_policy` (aggregates across all history) and
    :func:`simulate_policy_daily` (keeps each date's result separate, for a
    cumulative time series) so the two can never silently drift apart on
    what counts as a win, a cover, or a graded bet.

    :param conn: Open connection to the schedule database.
    :param scores: This date's {(game_id, team_id): score}, from compute_scores().
    :param game: (game_id, home_team, away_team, home_score, away_score).
    :param min_edge: Skip (return None) if the score gap is below this.
    :returns: None if skipped (missing scores or below min_edge), else a dict
        with keys: won (bool), ats_result (Optional[str]), ml_profit
        (Optional[float]), pl_profit (Optional[float]).
    """
    game_id, home_team, away_team, home_score, away_score = game
    home_score_val = scores.get((game_id, home_team))
    away_score_val = scores.get((game_id, away_team))
    if home_score_val is None or away_score_val is None:
        return None
    if abs(home_score_val - away_score_val) < min_edge:
        return None

    if home_score_val >= away_score_val:
        pick, pick_score, opp_score = home_team, home_score, away_score
    else:
        pick, pick_score, opp_score = away_team, away_score, home_score
    margin = pick_score - opp_score
    won = margin > 0

    spread = latest_consensus_spread(conn, game_id, pick)
    ats_result = None
    if spread is not None:
        covered = margin + spread
        if covered > 0:
            ats_result = "win"
        elif covered < 0:
            ats_result = "loss"
        else:
            ats_result = "push"

    moneyline = latest_consensus_moneyline(conn, game_id, pick)
    ml_profit = odds_profit(moneyline, "win" if won else "loss")

    # Puck Line here is about the same team as the Money Line pick, graded
    # against the spread -- not the same thing as report.py's independent
    # puck_line_pick recommendation (a different team entirely, based on
    # goal_differential, not this policy's weights).
    spread_price = latest_consensus_spread_price(conn, game_id, pick)
    pl_profit = odds_profit(spread_price, ats_result)

    return {"won": won, "ats_result": ats_result, "ml_profit": ml_profit, "pl_profit": pl_profit}


def simulate_policy(
    conn,
    policy_version: str,
    games_by_date: dict[str, list[tuple]],
    min_edge: float = 0.0,
) -> dict:
    """Replay every completed date's slate under one policy_version and grade the picks.

    :param conn: Open connection to the schedule database.
    :param policy_version: Which policy_weights version to score with.
    :param games_by_date: Result of :func:`completed_games_by_date`.
    :param min_edge: Skip any game whose score gap under this policy is below
        this -- a pure display filter, same idea as report.py's picks-page
        edge dropdown, not a change to how a game would actually be picked.
    :returns: Aggregate record/ROI dict for this policy_version across all history.
    """
    weight_rows = _policy_weight_rows(conn, policy_version)

    totals = {
        "games_evaluated": 0,
        "su_wins": 0,
        "su_losses": 0,
        "ats_wins": 0,
        "ats_losses": 0,
        "ats_pushes": 0,
        "total_profit": 0.0,
        "graded_bet_count": 0,
        "puck_line_profit": 0.0,
        "puck_line_bet_count": 0,
    }

    for game_date, games in games_by_date.items():
        scores = compute_scores(conn, game_date, weight_rows)
        for game in games:
            result = _grade_simulated_game(conn, scores, game, min_edge)
            if result is None:
                continue

            totals["games_evaluated"] += 1
            if result["won"]:
                totals["su_wins"] += 1
            else:
                totals["su_losses"] += 1

            if result["ats_result"] == "win":
                totals["ats_wins"] += 1
            elif result["ats_result"] == "loss":
                totals["ats_losses"] += 1
            elif result["ats_result"] == "push":
                totals["ats_pushes"] += 1

            if result["ml_profit"] is not None:
                totals["total_profit"] += result["ml_profit"]
                totals["graded_bet_count"] += 1

            if result["pl_profit"] is not None:
                totals["puck_line_profit"] += result["pl_profit"]
                totals["puck_line_bet_count"] += 1

    return totals


def simulate_policy_daily(
    conn,
    policy_version: str,
    games_by_date: dict[str, list[tuple]],
    min_edge: float = 0.0,
) -> list[dict]:
    """Per-date (not aggregate) Money Line/Puck Line profit under one policy.

    Reuses :func:`_grade_simulated_game`, the exact same per-game grading
    :func:`simulate_policy` uses, so summing this series' ml_profit/pl_profit
    across every date reproduces that function's total_profit/
    puck_line_profit exactly -- this is for record_page.py's Bankroll Over
    Time chart, which needs a day-by-day breakdown rather than one aggregate.

    :param conn: Open connection to the schedule database.
    :param policy_version: Which policy_weights version to score with.
    :param games_by_date: Result of :func:`completed_games_by_date`.
    :param min_edge: Same meaning as in :func:`simulate_policy`.
    :returns: One dict per date with at least one evaluated game:
        {"date", "ml_profit", "pl_profit"} -- that date's own totals, not a
        running cumulative sum (record_page.py accumulates these itself).
        Dates with no evaluated game are omitted, not zero-filled.
    """
    weight_rows = _policy_weight_rows(conn, policy_version)

    series = []
    for game_date in sorted(games_by_date):
        scores = compute_scores(conn, game_date, weight_rows)
        ml_profit = 0.0
        pl_profit = 0.0
        evaluated = False
        for game in games_by_date[game_date]:
            result = _grade_simulated_game(conn, scores, game, min_edge)
            if result is None:
                continue
            evaluated = True
            if result["ml_profit"] is not None:
                ml_profit += result["ml_profit"]
            if result["pl_profit"] is not None:
                pl_profit += result["pl_profit"]
        if evaluated:
            series.append({"date": game_date, "ml_profit": ml_profit, "pl_profit": pl_profit})

    return series


def _pct(wins: int, losses: int) -> str:
    total = wins + losses
    return f"{wins}-{losses} ({100 * wins / total:.1f}%)" if total else "0-0 (n/a)"


def roi_pct(totals: dict) -> Optional[float]:
    """Moneyline ROI%, on a flat $STAKE stake per bet.

    :param totals: One policy_version's aggregate dict, from :func:`simulate_policy`.
    :returns: ROI as a percentage, or None if no evaluated game had a moneyline to bet.
    """
    bet_count = totals["graded_bet_count"]
    if not bet_count:
        return None
    return 100 * totals["total_profit"] / (STAKE * bet_count)


def rank_by_roi(results: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    """Every policy_version's results, best ROI% first (policies with no odds last).

    Shared by the console printout and record_page.py's published table, so
    both ever only show one ranking of "which policy's doing best."

    :param results: (policy_version, totals) pairs, as returned by :func:`simulate_policy`.
    :returns: The same pairs, re-ordered.
    """
    return sorted(results, key=lambda item: (roi_pct(item[1]) is None, -(roi_pct(item[1]) or 0)))


def print_policy_backtest(results: list[tuple[str, dict]]) -> None:
    """Print every policy_version's simulated record, ranked by moneyline ROI%.

    :param results: (policy_version, totals) pairs, as returned by :func:`simulate_policy`.
    """
    print("\nPolicy backtest -- every policy replayed across the same full history")
    print("-" * 92)
    if not results:
        print("No completed games yet.")
        return

    for policy_version, totals in rank_by_roi(results):
        su = _pct(totals["su_wins"], totals["su_losses"])
        ats = _pct(totals["ats_wins"], totals["ats_losses"])
        push_note = f", {totals['ats_pushes']} push" if totals["ats_pushes"] else ""
        bet_count = totals["graded_bet_count"]
        pct = roi_pct(totals)
        roi_note = (
            f"ROI {totals['total_profit']:+.2f} on {bet_count} bets ({pct:+.1f}%)"
            if pct is not None
            else "ROI n/a (no odds on any evaluated game)"
        )
        print(
            f"{policy_version}: {totals['games_evaluated']} games evaluated | "
            f"moneyline {su} | vs. puck line {ats}{push_note} | {roi_note}"
        )


def build_policy_backtest() -> list[tuple[str, dict]]:
    """Simulate every known policy_version across all completed history.

    :returns: (policy_version, totals) pairs, in policy_version order.
    """
    init_db()
    conn = get_connection()
    with conn:
        policy_versions = all_policy_versions(conn)
        games_by_date = completed_games_by_date(conn)
        results = [
            (policy_version, simulate_policy(conn, policy_version, games_by_date))
            for policy_version in policy_versions
        ]
    conn.close()
    return results


def build_live_policy_edge_backtest() -> tuple[str, dict]:
    """Simulate just the currently-live policy, restricted to this season's
    odds-covered games with at least LIVE_POLICY_MIN_EDGE of predicted edge.

    Narrower than :func:`build_policy_backtest` on purpose: that one answers
    "which policy_version does best overall," this one answers "how has the
    policy actually live right now done on the specific games/threshold
    combination report.py's picks-page edge filter is built around" -- a
    direct, odds-backed read on the live policy rather than a cross-version
    comparison.

    :returns: (live policy_version, totals dict from :func:`simulate_policy`).
    """
    init_db()
    conn = get_connection()
    with conn:
        live_version = load_policy()["policy_version"]
        odds_games = games_with_odds(conn, completed_games_by_date(conn))
        totals = simulate_policy(conn, live_version, odds_games, min_edge=LIVE_POLICY_MIN_EDGE)
    conn.close()
    return live_version, totals


def build_live_policy_edge_series() -> list[dict]:
    """Day-by-day version of :func:`build_live_policy_edge_backtest`.

    Same restriction (this season's odds-covered games, edge >=
    LIVE_POLICY_MIN_EDGE) and the same policy, but kept per-date rather than
    summed into one aggregate -- feeds record_page.py's Bankroll Over Time
    chart, so that chart's live-policy line and the static Live Policy at
    High Edge section above it are always describing the exact same
    simulation (summing this series' ml_profit/pl_profit reproduces that
    section's totals exactly).

    :returns: Result of :func:`simulate_policy_daily` for the live policy.
    """
    init_db()
    conn = get_connection()
    with conn:
        live_version = load_policy()["policy_version"]
        odds_games = games_with_odds(conn, completed_games_by_date(conn))
        series = simulate_policy_daily(
            conn, live_version, odds_games, min_edge=LIVE_POLICY_MIN_EDGE
        )
    conn.close()
    return series


if __name__ == "__main__":
    print_policy_backtest(build_policy_backtest())
