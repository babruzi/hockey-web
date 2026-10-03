"""
Grades completed picks_log rows against final scores -- three independent
bets per game, matching the three independent recommendations report.py
produces (Money Line, Puck Line, Over/Under):

- Money Line: `straight_up_result` ('win'/'loss', the picked team's own
  game outcome) and `profit_10` ($ P&L on a flat $STAKE bet at
  `moneyline_at_pick`). `result` ('win'/'loss'/'push') additionally grades
  that same Money Line pick against the spread recorded in `spread_at_pick`
  -- this predates the Puck Line recommendation below and is kept for the
  "Team ATS Record" column, which is about the scoring engine's own pick,
  not the independent puck-line read.
- Puck Line: `puck_line_result`/`puck_line_profit_10`, graded the same way
  but against whichever team `puck_line_pick` named (which can differ from
  the Money Line pick) and its own `puck_line_spread_at_pick`/
  `puck_line_price_at_pick`.
- Over/Under: `total_result`/`total_profit_10`, graded against
  `total_at_pick`/`total_price_at_pick` and whatever `total_pick`
  ('Over'/'Under') was recommended.

Tracking win/loss and $ P&L separately for each matters for the same
reason: `profit_10` is odds-weighted while straight win/loss isn't, so a
string of favorites can go win-heavy and still lose money (and
underdogs can do the reverse) -- `backtest.py`/`record_page.py` sum the
profit columns for actual ROI figures, one per bet type.

Only grades rows for games the NHL Web API marks 'OFF' (final; see
form_metrics.py for why not 'FINAL') with both scores present, and only
rows still missing a gradeable result -- safe to re-run as often as you
like. A game with no Puck Line/Over-Under recommendation on record (e.g.
no odds, or not enough trailing-game data yet) simply never gets those
columns graded, same as a missing spread/moneyline already does for the
Money Line bet.

Usage:
    python lib/grade.py
"""

from datetime import datetime, timezone
from typing import Optional

from db import get_connection, init_db

STAKE = 10.0


def odds_profit(price: Optional[int], result: Optional[str]) -> Optional[float]:
    """Dollar profit/loss on a flat $STAKE bet at the given American odds.

    :param price: American odds for the side that was bet, or None if no
        odds were on record.
    :param result: 'win', 'loss', or 'push' (a push returns the stake, for a
        net $0), or None if there's no outcome to grade yet.
    :returns: Profit (positive), loss (negative), 0.0 for a push, or None if
        there was no price or result to grade against.
    """
    if price is None or result is None:
        return None
    if result == "push":
        return 0.0
    if result == "loss":
        return -STAKE
    return STAKE * price / 100.0 if price > 0 else STAKE * 100.0 / abs(price)


def grade_pending_picks(conn) -> int:
    """Fill in the Money Line/Puck Line/Over-Under grading columns for gradeable rows.

    :param conn: Open connection to the schedule database.
    :returns: Number of picks_log rows graded.
    """
    rows = conn.execute(
        """
        SELECT p.pick_id, p.pick, p.spread_at_pick, p.moneyline_at_pick,
               p.puck_line_pick, p.puck_line_spread_at_pick, p.puck_line_price_at_pick,
               p.total_pick, p.total_at_pick, p.total_price_at_pick,
               g.home_team, g.away_team, g.home_score, g.away_score
        FROM picks_log p
        JOIN games g ON g.game_id = p.game_id
        WHERE g.game_state = 'OFF'
          AND g.home_score IS NOT NULL
          AND g.away_score IS NOT NULL
          AND (
              p.result IS NULL OR p.straight_up_result IS NULL OR p.profit_10 IS NULL
              OR (p.puck_line_pick IS NOT NULL AND p.puck_line_result IS NULL)
              OR (p.total_pick IS NOT NULL AND p.total_result IS NULL)
          )
        """
    ).fetchall()

    graded_at = datetime.now(timezone.utc).isoformat()
    for (
        pick_id,
        pick,
        spread,
        moneyline,
        puck_line_pick,
        puck_line_spread,
        puck_line_price,
        total_pick,
        total_at_pick,
        total_price,
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
        profit_10 = odds_profit(moneyline, straight_up_result)

        if puck_line_pick is None or puck_line_spread is None:
            puck_line_result = None
        else:
            pl_score = home_score if puck_line_pick == home_team else away_score
            pl_opp_score = away_score if puck_line_pick == home_team else home_score
            pl_covered = (pl_score - pl_opp_score) + puck_line_spread
            puck_line_result = "win" if pl_covered > 0 else ("loss" if pl_covered < 0 else "push")
        puck_line_profit_10 = odds_profit(puck_line_price, puck_line_result)

        if total_pick is None or total_at_pick is None:
            total_result = None
        else:
            actual_total = home_score + away_score
            if actual_total == total_at_pick:
                total_result = "push"
            elif (actual_total > total_at_pick) == (total_pick == "Over"):
                total_result = "win"
            else:
                total_result = "loss"
        total_profit_10 = odds_profit(total_price, total_result)

        conn.execute(
            """
            UPDATE picks_log
            SET result = ?, straight_up_result = ?, profit_10 = ?,
                puck_line_result = ?, puck_line_profit_10 = ?,
                total_result = ?, total_profit_10 = ?,
                graded_at = ?
            WHERE pick_id = ?
            """,
            (
                result,
                straight_up_result,
                profit_10,
                puck_line_result,
                puck_line_profit_10,
                total_result,
                total_profit_10,
                graded_at,
                pick_id,
            ),
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
