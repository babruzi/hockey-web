"""
Grades completed picks_log rows against final scores: `result` ('win' /
'loss' / 'push') against the puck-line spread recorded at pick time in
`spread_at_pick`, `straight_up_result` ('win' / 'loss') for whether the
picked team won the game outright regardless of the spread, and
`profit_10` -- the $ profit or loss a flat $STAKE moneyline bet on the
pick would have made, using the moneyline recorded at pick time in
`moneyline_at_pick`.

Tracking result/straight_up_result/profit_10 separately matters
because `spread_at_pick`/`moneyline_at_pick` are often NULL (no odds
fetched for that game, or ODDS_API_KEY unset that day) -- those rows
can still get a straight_up_result, which is also the cleaner signal
for judging the scoring engine's own picks independent of the betting
market's line. A win/loss record alone doesn't tell you whether these
picks would have been profitable -- a string of favorites can go
win-heavy and still lose money, and vice versa for underdogs -- so
profit_10 is what backtest.py sums for an actual ROI figure.

Only grades rows for games the NHL Web API marks 'OFF' (final; see
form_metrics.py for why not 'FINAL') with both scores present, and only
rows still missing a result -- safe to re-run as often as you like.

Usage:
    python lib/grade.py
"""

from datetime import datetime, timezone
from typing import Optional

from db import get_connection, init_db

STAKE = 10.0


def moneyline_profit(moneyline: Optional[int], won: bool) -> Optional[float]:
    """Dollar profit/loss on a flat $STAKE moneyline bet on the pick.

    :param moneyline: The picked team's American moneyline at pick time, or
        None if no odds were on record.
    :param won: Whether the pick won straight up.
    :returns: Profit (positive) or loss (negative) on a $STAKE bet, or None
        if there was no moneyline to grade against.
    """
    if moneyline is None:
        return None
    if not won:
        return -STAKE
    if moneyline > 0:
        return STAKE * moneyline / 100.0
    return STAKE * 100.0 / abs(moneyline)


def grade_pending_picks(conn) -> int:
    """Fill in result/straight_up_result/profit_10 for any gradeable picks_log rows.

    :param conn: Open connection to the schedule database.
    :returns: Number of picks_log rows graded.
    """
    rows = conn.execute(
        """
        SELECT p.pick_id, p.pick, p.spread_at_pick, p.moneyline_at_pick,
               g.home_team, g.away_team, g.home_score, g.away_score
        FROM picks_log p
        JOIN games g ON g.game_id = p.game_id
        WHERE g.game_state = 'OFF'
          AND g.home_score IS NOT NULL
          AND g.away_score IS NOT NULL
          AND (p.result IS NULL OR p.straight_up_result IS NULL OR p.profit_10 IS NULL)
        """
    ).fetchall()

    graded_at = datetime.now(timezone.utc).isoformat()
    for (
        pick_id,
        pick,
        spread,
        moneyline,
        home_team,
        _away_team,
        home_score,
        away_score,
    ) in rows:
        pick_score = home_score if pick == home_team else away_score
        opp_score = away_score if pick == home_team else home_score
        margin = pick_score - opp_score

        won = margin > 0
        straight_up_result = "win" if won else "loss"

        if spread is None:
            result = None
        else:
            covered = margin + spread
            result = "win" if covered > 0 else ("loss" if covered < 0 else "push")

        profit_10 = moneyline_profit(moneyline, won)

        conn.execute(
            """
            UPDATE picks_log
            SET result = ?, straight_up_result = ?, profit_10 = ?, graded_at = ?
            WHERE pick_id = ?
            """,
            (result, straight_up_result, profit_10, graded_at, pick_id),
        )

    return len(rows)


def grade_all() -> None:
    """Grade every pending pick currently in picks_log and print a summary."""
    init_db()
    conn = get_connection()
    with conn:
        graded = grade_pending_picks(conn)
    conn.close()
    print(f"Graded {graded} pick(s).")


if __name__ == "__main__":
    grade_all()
