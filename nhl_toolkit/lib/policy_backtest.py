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

from db import get_connection, init_db
from grade import STAKE, odds_profit
from report import latest_consensus_moneyline, latest_consensus_spread
from score import compute_scores


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
    rows = conn.execute(
        """
        SELECT game_date, game_id, home_team, away_team, home_score, away_score
        FROM games
        WHERE game_state = 'OFF' AND home_score IS NOT NULL AND away_score IS NOT NULL
        ORDER BY game_date
        """
    ).fetchall()
    games_by_date: dict[str, list[tuple]] = {}
    for game_date, game_id, home_team, away_team, home_score, away_score in rows:
        games_by_date.setdefault(game_date, []).append(
            (game_id, home_team, away_team, home_score, away_score)
        )
    return games_by_date


def simulate_policy(conn, policy_version: str, games_by_date: dict[str, list[tuple]]) -> dict:
    """Replay every completed date's slate under one policy_version and grade the picks.

    :param conn: Open connection to the schedule database.
    :param policy_version: Which policy_weights version to score with.
    :param games_by_date: Result of :func:`completed_games_by_date`.
    :returns: Aggregate record/ROI dict for this policy_version across all history.
    """
    weight_rows = conn.execute(
        """
        SELECT m.name, m.metric_id, pw.weight, pw.normalize
        FROM policy_weights pw JOIN metrics m ON m.metric_id = pw.metric_id
        WHERE pw.policy_version = ?
        """,
        (policy_version,),
    ).fetchall()

    totals = {
        "games_evaluated": 0,
        "su_wins": 0,
        "su_losses": 0,
        "ats_wins": 0,
        "ats_losses": 0,
        "ats_pushes": 0,
        "total_profit": 0.0,
        "graded_bet_count": 0,
    }

    for game_date, games in games_by_date.items():
        scores = compute_scores(conn, game_date, weight_rows)
        for game_id, home_team, away_team, home_score, away_score in games:
            home_score_val = scores.get((game_id, home_team))
            away_score_val = scores.get((game_id, away_team))
            if home_score_val is None or away_score_val is None:
                continue

            if home_score_val >= away_score_val:
                pick, pick_score, opp_score = home_team, home_score, away_score
            else:
                pick, pick_score, opp_score = away_team, away_score, home_score
            margin = pick_score - opp_score

            totals["games_evaluated"] += 1
            won = margin > 0
            if won:
                totals["su_wins"] += 1
            else:
                totals["su_losses"] += 1

            spread = latest_consensus_spread(conn, game_id, pick)
            if spread is not None:
                covered = margin + spread
                if covered > 0:
                    totals["ats_wins"] += 1
                elif covered < 0:
                    totals["ats_losses"] += 1
                else:
                    totals["ats_pushes"] += 1

            moneyline = latest_consensus_moneyline(conn, game_id, pick)
            profit = odds_profit(moneyline, "win" if won else "loss")
            if profit is not None:
                totals["total_profit"] += profit
                totals["graded_bet_count"] += 1

    return totals


def _pct(wins: int, losses: int) -> str:
    total = wins + losses
    return f"{wins}-{losses} ({100 * wins / total:.1f}%)" if total else "0-0 (n/a)"


def print_policy_backtest(results: list[tuple[str, dict]]) -> None:
    """Print every policy_version's simulated record, ranked by moneyline ROI%.

    :param results: (policy_version, totals) pairs, as returned by :func:`simulate_policy`.
    """
    print("\nPolicy backtest -- every policy replayed across the same full history")
    print("-" * 92)
    if not results:
        print("No completed games yet.")
        return

    def roi_pct(totals: dict) -> Optional[float]:
        bet_count = totals["graded_bet_count"]
        if not bet_count:
            return None
        return 100 * totals["total_profit"] / (STAKE * bet_count)

    ranked = sorted(results, key=lambda item: (roi_pct(item[1]) is None, -(roi_pct(item[1]) or 0)))

    for policy_version, totals in ranked:
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


if __name__ == "__main__":
    print_policy_backtest(build_policy_backtest())
