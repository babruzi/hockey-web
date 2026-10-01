"""
Grades completed picks_log rows against final scores: `result` ('win' /
'loss' / 'push') against the puck-line spread recorded at pick time in
`spread_at_pick`, and `straight_up_result` ('win' / 'loss') for whether the
picked team won the game outright, regardless of the spread.

Tracking both separately matters because `spread_at_pick` is often NULL
(no odds fetched for that game, or ODDS_API_KEY unset that day) -- those
rows can still get a straight_up_result, which is also the cleaner signal
for judging the scoring engine's own picks independent of the betting
market's line.

Only grades rows for games the NHL Web API marks 'OFF' (final; see
form_metrics.py for why not 'FINAL') with both scores present, and only
rows still missing a result -- safe to re-run as often as you like.

Usage (from nhl_toolkit/):
    python picks/grade.py
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from db import get_connection, init_db  # noqa: E402


def grade_pending_picks(conn) -> int:
    """Fill in result/straight_up_result for any gradeable picks_log rows.

    :param conn: Open connection to the schedule database.
    :returns: Number of picks_log rows graded.
    """
    rows = conn.execute(
        """
        SELECT p.pick_id, p.pick, p.spread_at_pick, g.home_team, g.away_team,
               g.home_score, g.away_score
        FROM picks_log p
        JOIN games g ON g.game_id = p.game_id
        WHERE g.game_state = 'OFF'
          AND g.home_score IS NOT NULL
          AND g.away_score IS NOT NULL
          AND (p.result IS NULL OR p.straight_up_result IS NULL)
        """
    ).fetchall()

    graded_at = datetime.now(timezone.utc).isoformat()
    for pick_id, pick, spread, home_team, _away_team, home_score, away_score in rows:
        pick_score = home_score if pick == home_team else away_score
        opp_score = away_score if pick == home_team else home_score
        margin = pick_score - opp_score

        straight_up_result = "win" if margin > 0 else "loss"

        if spread is None:
            result = None
        else:
            covered = margin + spread
            result = "win" if covered > 0 else ("loss" if covered < 0 else "push")

        conn.execute(
            """
            UPDATE picks_log
            SET result = ?, straight_up_result = ?, graded_at = ?
            WHERE pick_id = ?
            """,
            (result, straight_up_result, graded_at, pick_id),
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
