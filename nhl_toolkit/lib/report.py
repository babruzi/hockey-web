"""
Builds the daily picks report from `daily_scores`: for each game,
whichever team scored higher is "the pick," ranked across the day's
full slate by the score gap between the two teams -- every scored game
is included, not just a top-N cut. Writes the result to a local CSV
digest, an HTML page under docs/reports/ (for GitHub Pages), and logs
each pick to `picks_log` for later grading/backtesting.

Run this after score.py has scored the target date.

Usage:
    python lib/report.py --date 2026-10-05
    python lib/report.py                      # defaults to today
"""

import argparse
import csv
import sqlite3
from datetime import date as date_cls
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from db import get_connection, init_db
from grade import STAKE
from market_metrics import american_to_probability

EASTERN = ZoneInfo("America/New_York")

REPORTS_DIR = Path(__file__).parent.parent / "reports"

# docs/ lives at the repo root (two levels up from lib/), since
# GitHub Pages serves a repo from either the root or a /docs folder.
DOCS_DIR = Path(__file__).parent.parent.parent / "docs"
DOCS_REPORTS_DIR = DOCS_DIR / "reports" / "picks"
DOCS_POLICIES_DIR = DOCS_DIR / "reports" / "policies"


PRIMARY_BOOK = "draftkings"


def _dk_or_consensus(
    conn: sqlite3.Connection, game_id: int, team_id: str, home_col: str, away_col: str
) -> Optional[float]:
    """One team's DraftKings quote, falling back to a cross-book average.

    DraftKings (`PRIMARY_BOOK`) is the book these picks are actually meant to
    be bet on, so its own line is used whenever it has one -- not a blend.
    The cross-book average (each bookmaker's latest quote, averaged) only
    kicks in on the rare game DraftKings hasn't posted a line for yet. That
    average can look like a line no real book would ever offer when
    bookmakers disagree about which side is favored (e.g. a near-50/50 game
    where some books have the home team at -1.5 and others at +1.5 averages
    out to something like -0.17) -- a real limitation worth knowing about,
    but it only ever applies to that rare DraftKings-less fallback case.

    :param conn: Open connection to the schedule database.
    :param game_id: The game to look up odds for.
    :param team_id: The team whose line to return (its home or away side).
    :param home_col: `odds` column to read for the home team (e.g. "home_spread").
    :param away_col: `odds` column to read for the away team (e.g. "away_spread").
    :returns: The value, or None if no odds have been fetched for this game at all.
    """
    dk_row = conn.execute(
        f"""
        SELECT o.{home_col}, o.{away_col}, g.home_team
        FROM odds o
        JOIN games g ON g.game_id = o.game_id
        WHERE o.game_id = ? AND o.source = ?
        ORDER BY o.fetched_at DESC
        LIMIT 1
        """,
        (game_id, PRIMARY_BOOK),
    ).fetchone()
    if dk_row:
        home_value, away_value, home_team = dk_row
        value = home_value if team_id == home_team else away_value
        if value is not None:
            return value

    rows = conn.execute(
        f"""
        SELECT o.{home_col}, o.{away_col}, g.home_team
        FROM odds o
        JOIN games g ON g.game_id = o.game_id
        WHERE o.game_id = ?
          AND o.fetched_at = (
              SELECT MAX(o2.fetched_at) FROM odds o2
              WHERE o2.game_id = o.game_id AND o2.source = o.source
          )
        """,
        (game_id,),
    ).fetchall()
    if not rows:
        return None

    values = [
        home_value if team_id == home_team else away_value
        for home_value, away_value, home_team in rows
        if (home_value if team_id == home_team else away_value) is not None
    ]
    return sum(values) / len(values) if values else None


def latest_consensus_spread(
    conn: sqlite3.Connection, game_id: int, team_id: str
) -> Optional[float]:
    """One team's puck-line spread: DraftKings' own quote, or a cross-book
    average if DraftKings hasn't posted a line for this game (see
    :func:`_dk_or_consensus`).

    :param conn: Open connection to the schedule database.
    :param game_id: The game to look up odds for.
    :param team_id: The team whose spread to return (its home or away line).
    :returns: The spread, or None if no odds have been fetched for this game.
    """
    return _dk_or_consensus(conn, game_id, team_id, "home_spread", "away_spread")


def latest_consensus_moneyline(
    conn: sqlite3.Connection, game_id: int, team_id: str
) -> Optional[int]:
    """One team's moneyline: DraftKings' own quote, or a cross-book average
    if DraftKings hasn't posted a line for this game (see
    :func:`_dk_or_consensus`).

    :param conn: Open connection to the schedule database.
    :param game_id: The game to look up odds for.
    :param team_id: The team whose moneyline to return (its home or away line).
    :returns: The moneyline, or None if no odds have been fetched for this game.
    """
    value = _dk_or_consensus(conn, game_id, team_id, "home_ml", "away_ml")
    return round(value) if value is not None else None


def latest_total(conn: sqlite3.Connection, game_id: int) -> tuple:
    """The game's over/under total and both sides' prices.

    DraftKings' own quote if it has one, else a cross-book average of each
    bookmaker's latest quote -- same preference as :func:`_dk_or_consensus`,
    but the total isn't per-team (over/under applies to the game as a
    whole), so it's handled separately rather than reusing that helper.

    :param conn: Open connection to the schedule database.
    :param game_id: The game to look up odds for.
    :returns: (total, over_odds, under_odds), each None if unavailable.
    """
    dk_row = conn.execute(
        """
        SELECT total, over_odds, under_odds
        FROM odds
        WHERE game_id = ? AND source = ? AND total IS NOT NULL
        ORDER BY fetched_at DESC
        LIMIT 1
        """,
        (game_id, PRIMARY_BOOK),
    ).fetchone()
    if dk_row:
        return dk_row

    rows = conn.execute(
        """
        SELECT total, over_odds, under_odds
        FROM odds o
        WHERE game_id = ?
          AND total IS NOT NULL
          AND fetched_at = (
              SELECT MAX(o2.fetched_at) FROM odds o2
              WHERE o2.game_id = o.game_id AND o2.source = o.source
          )
        """,
        (game_id,),
    ).fetchall()
    if not rows:
        return None, None, None

    totals = [r[0] for r in rows]
    overs = [r[1] for r in rows if r[1] is not None]
    unders = [r[2] for r in rows if r[2] is not None]
    return (
        sum(totals) / len(totals),
        round(sum(overs) / len(overs)) if overs else None,
        round(sum(unders) / len(unders)) if unders else None,
    )


def devig_pair(odds_a: Optional[int], odds_b: Optional[int]) -> tuple:
    """Devig a two-sided market's American odds into percentages that sum to 100.

    Same devig approach as market_metrics.py's market_edge (convert each
    side's American odds to a raw implied probability, then divide by their
    sum to remove the bookmaker's overround) -- shown here purely for
    display (moneyline win%, puck-line cover%, or over/under%), not stored
    anywhere. Works for any two-sided market, not just moneylines.

    :param odds_a: First side's American odds, or None if no quote.
    :param odds_b: Second side's American odds, or None if no quote.
    :returns: (pct_a, pct_b) in [0, 100], or (None, None) if either side's quote is missing.
    """
    if odds_a is None or odds_b is None:
        return None, None
    raw_a = american_to_probability(odds_a)
    raw_b = american_to_probability(odds_b)
    overround = raw_a + raw_b
    return 100 * raw_a / overround, 100 * raw_b / overround


def potential_payout(price: Optional[int], stake: float) -> Optional[float]:
    """Profit on a $stake bet at American odds `price`, if it wins.

    Not the same thing as grade.py's moneyline_profit(), which needs to know
    whether the bet actually won -- this is the forward-looking "if this
    pick hits, how much do I win" question for an *ungraded* pick, so there's
    no loss case here.

    :param price: American odds, e.g. -142 or +180, or None if no quote.
    :param stake: Dollar amount wagered.
    :returns: Profit in dollars if the bet wins, or None if there's no price.
    """
    if price is None:
        return None
    if price > 0:
        return stake * price / 100
    return stake * 100 / abs(price)


def home_opener_note(conn: sqlite3.Connection, home_team: str, game_date: str) -> Optional[str]:
    """Flag whether this is the home team's first home game in the data we've fetched.

    Only as reliable as the fetched schedule window -- if `games` doesn't go
    back to the actual season start, this reports the first home game *we
    know about*, not necessarily the true season opener.

    :param conn: Open connection to the schedule database.
    :param home_team: The home team's abbreviation.
    :param game_date: This game's date, as YYYY-MM-DD.
    :returns: "Home opener" if no earlier home game is on record, else None.
    """
    earlier_home_games = conn.execute(
        """
        SELECT COUNT(*) FROM schedule_context sc
        JOIN games g ON g.game_id = sc.game_id
        WHERE sc.team_id = ? AND sc.is_home = 1 AND g.game_date < ?
        """,
        (home_team, game_date),
    ).fetchone()[0]
    return "Home opener" if earlier_home_games == 0 else None


def back_to_back_notes(conn: sqlite3.Connection, game_id: int) -> list[str]:
    """List which team(s), if any, are playing this game on zero days of rest.

    :param conn: Open connection to the schedule database.
    :param game_id: The game to check.
    :returns: One note per team on a back-to-back, e.g. ["PHI on a back-to-back"].
    """
    rows = conn.execute(
        "SELECT team_id FROM schedule_context WHERE game_id = ? AND back_to_back = 1",
        (game_id,),
    ).fetchall()
    return [f"{team_id} on a back-to-back" for (team_id,) in rows]


def build_game_notes(
    conn: sqlite3.Connection, game_id: int, home_team: str, game_date: str
) -> list[str]:
    """Collect special-context notes for a game (home opener, back-to-back, ...).

    :param conn: Open connection to the schedule database.
    :param game_id: The game to annotate.
    :param home_team: The home team's abbreviation.
    :param game_date: This game's date, as YYYY-MM-DD.
    :returns: Short note strings, e.g. ["Home opener", "PHI on a back-to-back"].
    """
    notes = []
    opener_note = home_opener_note(conn, home_team, game_date)
    if opener_note:
        notes.append(opener_note)
    notes.extend(back_to_back_notes(conn, game_id))
    return notes


def team_ats_records(conn: sqlite3.Connection) -> dict[str, tuple[int, int]]:
    """Each team's all-time (wins, losses) against the spread, across every graded pick.

    Pushes don't count toward either side. This is a running total as of
    whenever it's queried -- a team's record here changes as soon as another
    of its picks gets graded, which is why every published report needs to be
    re-rendered whenever grading runs, not just the date that was graded.

    :param conn: Open connection to the schedule database.
    :returns: {team_abbrev: (wins, losses)} for every team with at least one graded pick.
    """
    rows = conn.execute(
        """
        SELECT pick,
               SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END),
               SUM(CASE WHEN result = 'loss' THEN 1 ELSE 0 END)
        FROM picks_log
        WHERE result IN ('win', 'loss')
        GROUP BY pick
        """
    ).fetchall()
    return {team: (wins, losses) for team, wins, losses in rows}


def team_metric_values(
    conn: sqlite3.Connection, game_id: int, team_id: str, metric_names: list[str]
) -> dict[str, float]:
    """Look up a team's metric_values for a game, keyed by metric name.

    :param conn: Open connection to the schedule database.
    :param game_id: The game to look up.
    :param team_id: The team's 3-letter abbreviation.
    :param metric_names: Metric names to fetch (from the metrics catalog).
    :returns: {metric_name: value}, missing a key if that metric has no value on record.
    """
    placeholders = ",".join("?" * len(metric_names))
    rows = conn.execute(
        f"""
        SELECT m.name, mv.value
        FROM metric_values mv JOIN metrics m ON m.metric_id = mv.metric_id
        WHERE mv.game_id = ? AND mv.team_id = ? AND m.name IN ({placeholders})
        """,
        [game_id, team_id, *metric_names],
    ).fetchall()
    return dict(rows)


FORM_METRIC_NAMES = ["goal_differential", "goals_for_avg", "goals_against_avg"]

# Puck line is fixed at 1.5 goals in every quote this pipeline has ever
# recorded (see market_metrics.py) -- so "covers" is simply "wins by more
# than this many goals."
PUCK_LINE = 1.5


def puck_line_recommendation(
    home_team: str,
    away_team: str,
    home_spread: Optional[float],
    away_spread: Optional[float],
    home_goal_diff: Optional[float],
    away_goal_diff: Optional[float],
) -> Optional[str]:
    """Which team's puck line price projects as the better side to lay/take.

    Unlike the Money Line pick (driven by policy.yaml's weighted total_score),
    this only asks "who covers the fixed 1.5-goal line" -- a question about
    margin of victory, not overall team strength. It projects this game's
    margin as each team's own recent average goal differential (goal_differential,
    from form_metrics.py) minus the other's, a simple straight-up comparison with
    no further weighting, and checks whether that projected margin clears 1.5
    in the favorite's direction.

    :param home_team: Home team abbreviation.
    :param away_team: Away team abbreviation.
    :param home_spread: Home team's puck line (negative if favored).
    :param away_spread: Away team's puck line (negative if favored).
    :param home_goal_diff: Home team's recent average goal differential.
    :param away_goal_diff: Away team's recent average goal differential.
    :returns: The recommended team abbreviation, or None if there isn't enough data.
    """
    if home_goal_diff is None or away_goal_diff is None:
        return None
    projected_margin = home_goal_diff - away_goal_diff  # positive favors home
    if home_spread is not None and home_spread < 0:
        return home_team if projected_margin > PUCK_LINE else away_team
    if away_spread is not None and away_spread < 0:
        return away_team if -projected_margin > PUCK_LINE else home_team
    return None


def total_recommendation(
    total: Optional[float],
    home_goals_for: Optional[float],
    home_goals_against: Optional[float],
    away_goals_for: Optional[float],
    away_goals_against: Optional[float],
) -> Optional[str]:
    """Project this game's total goals and compare it to the market's total line.

    Each team's expected goals is the average of its own scoring rate and the
    opponent's rate of allowing goals (goals_for_avg/goals_against_avg, from
    form_metrics.py) -- a simple offense-vs-opponent-defense projection, not a
    policy.yaml-weighted metric, since this compares against a fixed market
    line rather than scoring one team against another.

    :param total: The market's over/under line for this game.
    :param home_goals_for: Home team's recent average goals scored.
    :param home_goals_against: Home team's recent average goals allowed.
    :param away_goals_for: Away team's recent average goals scored.
    :param away_goals_against: Away team's recent average goals allowed.
    :returns: "Over", "Under", or None if there isn't enough data (or it's a wash).
    """
    values = (total, home_goals_for, home_goals_against, away_goals_for, away_goals_against)
    if any(v is None for v in values):
        return None
    projected_home_goals = (home_goals_for + away_goals_against) / 2
    projected_away_goals = (away_goals_for + home_goals_against) / 2
    projected_total = projected_home_goals + projected_away_goals
    if projected_total > total:
        return "Over"
    if projected_total < total:
        return "Under"
    return None


def build_picks(conn: sqlite3.Connection, target_date: str) -> list[dict]:
    """Rank each game by score gap and pick the higher-scoring side.

    :param conn: Open connection to the schedule database.
    :param target_date: Date to report on, as YYYY-MM-DD.
    :returns: Pick dicts sorted by predicted_edge descending.
    """
    rows = conn.execute(
        """
        SELECT ds.game_id, ds.team_id, ds.total_score, g.home_team, g.away_team,
               g.game_date, g.home_score, g.away_score
        FROM daily_scores ds
        JOIN games g ON g.game_id = ds.game_id
        WHERE ds.date = ?
        """,
        (target_date,),
    ).fetchall()

    scores_by_game: dict[int, dict] = {}
    for (
        game_id,
        team_id,
        total_score,
        home_team,
        away_team,
        game_date,
        final_home_score,
        final_away_score,
    ) in rows:
        game = scores_by_game.setdefault(
            game_id,
            {
                "home_team": home_team,
                "away_team": away_team,
                "game_date": game_date,
                "final_home_score": final_home_score,
                "final_away_score": final_away_score,
                "scores": {},
            },
        )
        game["scores"][team_id] = total_score

    grading_by_game = {
        game_id: (result, straight_up_result)
        for game_id, result, straight_up_result in conn.execute(
            "SELECT game_id, result, straight_up_result FROM picks_log WHERE date = ?",
            (target_date,),
        ).fetchall()
    }
    ats_records = team_ats_records(conn)

    picks = []
    for game_id, game in scores_by_game.items():
        home_score = game["scores"].get(game["home_team"])
        away_score = game["scores"].get(game["away_team"])
        if home_score is None or away_score is None:
            continue

        pick_team = game["home_team"] if home_score >= away_score else game["away_team"]
        predicted_edge = abs(home_score - away_score)
        result, straight_up_result = grading_by_game.get(game_id, (None, None))

        home_moneyline = latest_consensus_moneyline(conn, game_id, game["home_team"])
        away_moneyline = latest_consensus_moneyline(conn, game_id, game["away_team"])
        home_win_pct, away_win_pct = devig_pair(home_moneyline, away_moneyline)

        home_spread = latest_consensus_spread(conn, game_id, game["home_team"])
        away_spread = latest_consensus_spread(conn, game_id, game["away_team"])
        home_spread_price = _dk_or_consensus(
            conn, game_id, game["home_team"], "home_spread_price", "away_spread_price"
        )
        away_spread_price = _dk_or_consensus(
            conn, game_id, game["away_team"], "home_spread_price", "away_spread_price"
        )
        home_cover_pct, away_cover_pct = devig_pair(home_spread_price, away_spread_price)
        pick_spread_price = (
            home_spread_price if pick_team == game["home_team"] else away_spread_price
        )

        total, over_odds, under_odds = latest_total(conn, game_id)
        over_pct, under_pct = devig_pair(over_odds, under_odds)

        home_form = team_metric_values(conn, game_id, game["home_team"], FORM_METRIC_NAMES)
        away_form = team_metric_values(conn, game_id, game["away_team"], FORM_METRIC_NAMES)
        puck_line_pick = puck_line_recommendation(
            game["home_team"],
            game["away_team"],
            home_spread,
            away_spread,
            home_form.get("goal_differential"),
            away_form.get("goal_differential"),
        )
        total_pick = total_recommendation(
            total,
            home_form.get("goals_for_avg"),
            home_form.get("goals_against_avg"),
            away_form.get("goals_for_avg"),
            away_form.get("goals_against_avg"),
        )

        picks.append(
            {
                "game_id": game_id,
                "home_team": game["home_team"],
                "away_team": game["away_team"],
                "pick": pick_team,
                "pick_is_home": pick_team == game["home_team"],
                "predicted_edge": predicted_edge,
                "spread_at_pick": latest_consensus_spread(conn, game_id, pick_team),
                "moneyline_at_pick": latest_consensus_moneyline(conn, game_id, pick_team),
                "pick_spread_price": pick_spread_price,
                "home_moneyline": home_moneyline,
                "away_moneyline": away_moneyline,
                "home_win_pct": home_win_pct,
                "away_win_pct": away_win_pct,
                "home_spread": home_spread,
                "away_spread": away_spread,
                "home_spread_price": home_spread_price,
                "away_spread_price": away_spread_price,
                "home_cover_pct": home_cover_pct,
                "away_cover_pct": away_cover_pct,
                "total": total,
                "over_odds": over_odds,
                "under_odds": under_odds,
                "over_pct": over_pct,
                "under_pct": under_pct,
                "puck_line_pick": puck_line_pick,
                "total_pick": total_pick,
                "notes": build_game_notes(conn, game_id, game["home_team"], game["game_date"]),
                "final_home_score": game["final_home_score"],
                "final_away_score": game["final_away_score"],
                "result": result,
                "straight_up_result": straight_up_result,
                "pick_ats_record": ats_records.get(pick_team),
            }
        )

    picks.sort(key=lambda pick: pick["predicted_edge"], reverse=True)
    return picks


CSV_FIELDNAMES = [
    "game_id",
    "away_team",
    "home_team",
    "pick",
    "predicted_edge",
    "spread_at_pick",
    "notes",
]


def write_csv(target_date: str, picks: list[dict]) -> Path:
    """Write every pick to a CSV digest file.

    :param target_date: Date the report covers, as YYYY-MM-DD.
    :param picks: Picks as returned by :func:`build_picks`.
    :returns: Path to the written CSV file.
    """
    REPORTS_DIR.mkdir(exist_ok=True)
    path = REPORTS_DIR / f"picks_{target_date}.csv"
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for pick in picks:
            row = {key: pick[key] for key in CSV_FIELDNAMES if key != "notes"}
            row["notes"] = "; ".join(pick["notes"])
            writer.writerow(row)
    return path


HTML_STYLE = """
:root {
    color-scheme: light dark;
    --bg: #ffffff;
    --fg: #1a1a1a;
    --muted: #6b7280;
    --border: #e5e7eb;
    --row-alt: #f9fafb;
    --accent: #1d4ed8;
    --pick: #15803d;
    --negative: #b91c1c;
}
@media (prefers-color-scheme: dark) {
    :root {
        --bg: #16181d;
        --fg: #e6e6e6;
        --muted: #9ca3af;
        --border: #2c2f36;
        --row-alt: #1c1f26;
        --accent: #60a5fa;
        --pick: #4ade80;
        --negative: #f87171;
    }
}
body {
    background: var(--bg);
    color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    max-width: 1400px;
    margin: 2rem auto;
    padding: 0 1rem;
}
h1 { font-size: 1.4rem; margin-bottom: 0.25rem; }
.subtitle { color: var(--muted); margin-top: 0; margin-bottom: 1.5rem; }
.legend { color: var(--muted); font-size: 0.85rem; margin-top: 1.5rem; }
/* The picks table (12 columns with full borders/padding) only needs
   horizontal scrolling on a viewport narrower than this page's own
   max-width -- on anything wider, it fits and should just lay out
   normally. This also matters for the sticky header below: setting
   overflow-x: auto on an element makes browsers implicitly treat its
   overflow-y as auto too (per the CSS Overflow spec's "visible paired
   with non-visible" rule), which turns it into its own scroll
   container -- and `position: sticky` sticks to the nearest scroll
   container, not necessarily the page. Inside an always-auto wrapper,
   the header would silently stop sticking (it'd stick to the wrapper's
   own never-scrolled top instead of the viewport). Scoping overflow-x
   to narrow viewports only, where it's actually needed, keeps the
   sticky header working everywhere else. */
.table-scroll { overflow-x: auto; }
@media (min-width: 1400px) {
    .table-scroll { overflow-x: visible; }
}
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 0.65rem 0.9rem; border: 1px solid var(--border); }
thead th { position: sticky; top: 0; background: var(--bg); z-index: 2; }
td[rowspan] { vertical-align: middle; }
tr:nth-child(even) td { background: var(--row-alt); }
/* Picks report only: both rows of a game share one background, alternating
   per game rather than per physical row (each game is two rows -- away team
   on top, home team below -- so plain nth-child striping would just color
   every home row, not every other game). "tr.game-even"/"tr.game-odd" match
   the nth-child rule's specificity (tr + class + td = tr + pseudo-class +
   td) exactly, so source order decides and these, placed after, win --
   a bare ".game-even td" is actually *less* specific than the nth-child
   rule above and would silently lose to it. */
tr.game-even td { background: var(--row-alt); }
tr.game-odd td { background: var(--bg); }
th { color: var(--muted); font-weight: 600; font-size: 0.85rem; text-transform: uppercase; }
.rank { color: var(--muted); width: 2rem; }
.edge { font-variant-numeric: tabular-nums; }
.notes { color: var(--muted); font-size: 0.85rem; }
.pick { color: var(--pick); }
.positive { color: var(--pick); font-variant-numeric: tabular-nums; }
.negative { color: var(--negative); font-variant-numeric: tabular-nums; }
a { color: var(--accent); }
.disclaimer { color: var(--muted); font-size: 0.85rem; margin-top: 2rem; }
.updated { color: var(--muted); font-size: 0.75rem; margin-top: 0.5rem; }
.controls {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
    margin-bottom: 1rem;
    padding: 0.6rem 0.9rem;
    border: 1px solid var(--border);
    border-radius: 0.4rem;
}
.controls select {
    background: var(--bg);
    color: var(--fg);
    border: 1px solid var(--border);
    border-radius: 0.3rem;
    padding: 0.25rem 0.5rem;
}
"""


def generation_timestamp() -> str:
    """The current time in US Eastern, formatted for a page's "last updated" footer.

    Uses America/New_York via zoneinfo rather than a hardcoded "EDT" label,
    so it reads correctly as EDT or EST depending on whether daylight saving
    is in effect on the day this actually runs.

    :returns: e.g. "October 01, 2026 at 11:42 AM EDT".
    """
    eastern_now = datetime.now(timezone.utc).astimezone(EASTERN)
    return eastern_now.strftime("%B %d, %Y at %I:%M %p %Z")


def render_html_report(target_date: str, picks: list[dict]) -> Path:
    """Render the day's Top-N picks as a static HTML page under docs/reports/.

    :param target_date: Date the report covers, as YYYY-MM-DD.
    :param picks: Picks as returned by :func:`build_picks`.
    :returns: Path to the written HTML file.
    """
    DOCS_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    pretty_date = datetime.strptime(target_date, "%Y-%m-%d").strftime("%B %d, %Y")

    def format_price(price: Optional[int]) -> str:
        return f"{price:+d}" if price is not None else ""

    def format_team_name(team: str, is_pick: bool) -> str:
        return f'<strong class="pick">{team}</strong>' if is_pick else team

    def wrap_if_pick(line: str, is_pick: bool) -> str:
        return f'<strong class="pick">{line}</strong>' if is_pick else line

    def format_puck_line_cell(
        spread: Optional[float], price: Optional[int], pct: Optional[float], is_pick: bool
    ) -> str:
        if spread is None:
            return '<span class="notes">n/a</span>'
        parts = [f"{spread:+.1f}", format_price(price)]
        line = " ".join(p for p in parts if p)
        line = f"{line} ({pct:.1f}%)" if pct is not None else line
        return wrap_if_pick(line, is_pick)

    def format_total_cell(
        side_label: str,
        total: Optional[float],
        price: Optional[int],
        pct: Optional[float],
        is_pick: bool,
    ) -> str:
        if total is None:
            return '<span class="notes">n/a</span>'
        total_str = f"{total:g}"
        parts = [f"{side_label} {total_str}", format_price(price)]
        line = " ".join(p for p in parts if p)
        line = f"{line} ({pct:.1f}%)" if pct is not None else line
        return wrap_if_pick(line, is_pick)

    def format_ml_cell(moneyline: Optional[int], pct: Optional[float], is_pick: bool) -> str:
        if moneyline is None:
            return '<span class="notes">n/a</span>'
        price = format_price(moneyline)
        line = f"{price} ({pct:.1f}%)" if pct is not None else price
        return wrap_if_pick(line, is_pick)

    def format_notes(pick: dict) -> str:
        return "; ".join(pick["notes"]) if pick["notes"] else "&mdash;"

    def format_final_score(pick: dict) -> str:
        if pick["final_home_score"] is None or pick["final_away_score"] is None:
            return '<span class="notes">&mdash;</span>'
        score = f"{pick['final_away_score']}&ndash;{pick['final_home_score']}"
        if pick["total"] is None:
            return score
        actual_total = pick["final_home_score"] + pick["final_away_score"]
        if actual_total > pick["total"]:
            ou_note = "Over"
        elif actual_total < pick["total"]:
            ou_note = "Under"
        else:
            ou_note = "Push"
        return f'{score} <span class="notes">({ou_note})</span>'

    def format_outcome_colored(value: Optional[str]) -> str:
        if value == "win":
            return '<span class="positive">Win</span>'
        if value == "loss":
            return '<span class="negative">Loss</span>'
        if value == "push":
            return '<span class="notes">Push</span>'
        return '<span class="notes">&mdash;</span>'

    def format_ats(pick: dict) -> str:
        if pick["result"] is not None:
            return format_outcome_colored(pick["result"])
        # Game is final but there was never a spread to grade against --
        # distinct from "not played yet", which falls through to the dash.
        if pick["final_home_score"] is not None and pick["spread_at_pick"] is None:
            return '<span class="notes">n/a</span>'
        return format_outcome_colored(None)

    def format_team_ats_record(pick: dict) -> str:
        record = pick["pick_ats_record"]
        if record is None:
            return '<span class="notes">&mdash;</span>'
        wins, losses = record
        pct = 100 * wins / (wins + losses)
        return f"{wins}-{losses} ({pct:.1f}%)"

    is_today = target_date == date_cls.today().isoformat()

    def format_winnings_cell(pick: dict) -> str:
        if not is_today:
            return ""
        ml_price = pick["moneyline_at_pick"]
        pl_price = pick["pick_spread_price"]
        default_payout = potential_payout(ml_price, STAKE)
        default_str = f"${default_payout:.2f}" if default_payout is not None else "&mdash;"
        ml_attr = "" if ml_price is None else str(ml_price)
        pl_attr = "" if pl_price is None else str(pl_price)
        return (
            f'<td class="edge winnings-cell" rowspan="2" data-ml="{ml_attr}" '
            f'data-pl="{pl_attr}">{default_str}</td>'
        )

    def render_game_rows(i: int, pick: dict) -> str:
        game_class = "game-even" if i % 2 == 0 else "game-odd"
        away_puck = format_puck_line_cell(
            pick["away_spread"],
            pick["away_spread_price"],
            pick["away_cover_pct"],
            pick["puck_line_pick"] == pick["away_team"],
        )
        home_puck = format_puck_line_cell(
            pick["home_spread"],
            pick["home_spread_price"],
            pick["home_cover_pct"],
            pick["puck_line_pick"] == pick["home_team"],
        )
        over_cell = format_total_cell(
            "O", pick["total"], pick["over_odds"], pick["over_pct"], pick["total_pick"] == "Over"
        )
        under_cell = format_total_cell(
            "U",
            pick["total"],
            pick["under_odds"],
            pick["under_pct"],
            pick["total_pick"] == "Under",
        )
        away_ml = format_ml_cell(
            pick["away_moneyline"], pick["away_win_pct"], not pick["pick_is_home"]
        )
        home_ml = format_ml_cell(pick["home_moneyline"], pick["home_win_pct"], pick["pick_is_home"])

        return f"""
        <tr class="{game_class}">
            <td class="rank" rowspan="2">{i}</td>
            <td>{format_team_name(pick["away_team"], not pick["pick_is_home"])}</td>
            <td>{away_puck}</td>
            <td>{over_cell}</td>
            <td>{away_ml}</td>
            {format_winnings_cell(pick)}
            <td class="edge" rowspan="2">{pick["predicted_edge"]:.3f}</td>
            <td class="edge" rowspan="2">{format_final_score(pick)}</td>
            <td rowspan="2">{format_outcome_colored(pick["straight_up_result"])}</td>
            <td rowspan="2">{format_ats(pick)}</td>
            <td class="edge" rowspan="2">{format_team_ats_record(pick)}</td>
            <td class="notes" rowspan="2">{format_notes(pick)}</td>
        </tr>
        <tr class="{game_class}">
            <td>{format_team_name(pick["home_team"], pick["pick_is_home"])}</td>
            <td>{home_puck}</td>
            <td>{under_cell}</td>
            <td>{home_ml}</td>
        </tr>"""

    rows = "\n".join(render_game_rows(i, pick) for i, pick in enumerate(picks, start=1))

    winnings_header = "<th>Est. Winnings</th>" if is_today else ""
    controls_html = (
        f"""
<div class="controls">
<label for="odds-type">Show "Est. Winnings" using:</label>
<select id="odds-type" onchange="updateWinnings()">
<option value="ml" selected>Money Line</option>
<option value="pl">Puck Line</option>
</select>
<span class="notes">(payout on a ${STAKE:.0f} bet on the pick, if it wins)</span>
</div>"""
        if is_today
        else ""
    )
    winnings_script = (
        """
<script>
function updateWinnings() {
    var marketType = document.getElementById("odds-type").value;
    var cells = document.querySelectorAll(".winnings-cell");
    cells.forEach(function (cell) {
        var attr = marketType === "ml" ? "data-ml" : "data-pl";
        var raw = cell.getAttribute(attr);
        if (!raw) {
            cell.textContent = "\\u2014";
            return;
        }
        var price = parseInt(raw, 10);
        var stake = """
        + f"{STAKE}"
        + """;
        var payout = price > 0 ? (stake * price) / 100 : (stake * 100) / Math.abs(price);
        cell.textContent = "$" + payout.toFixed(2);
    });
}
</script>"""
        if is_today
        else ""
    )

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>NHL Picks &mdash; {pretty_date}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{HTML_STYLE}</style>
</head>
<body>
<p><a href="../../index.html">&larr; All reports</a></p>
<h1>{len(picks)} Picks</h1>
<p class="subtitle">{pretty_date}</p>
{controls_html}
<div class="table-scroll">
<table>
<thead>
<tr>
    <th>#</th><th>Team</th><th>Puck Line</th><th>Over/Under</th><th>Money Line</th>
    {winnings_header}
    <th>Edge</th><th>Score</th><th>ML Result</th><th>Vs. Puck Line</th>
    <th>Team ATS Record</th><th>Notes</th>
</tr>
</thead>
<tbody>{rows}
</tbody>
</table>
</div>
<p class="legend">
Every game on the slate, ranked by edge &middot; generated by the NHL paper-betting
toolkit &middot; away team's row on top, home team's row below, same layout as a
sportsbook board (Score column is also Away&ndash;Home, with whether the total went
Over/Under in parens) &middot; the
<strong class="pick">green, bolded</strong> side in each column is that column's own
recommendation &middot; Money Line is the overall pick (policy.yaml's weighted
total_score) &middot; Puck Line and Over/Under are each a separate, simpler projection
(recent average goal margin, and recent average goals for/against vs. the market's
total) and so can recommend a different side than Money Line does &middot; each price
is followed in parens by the market's devigged implied probability for that side
&middot; ML Result/Vs. Puck Line columns grade the pick once the
game is final &middot; Team ATS Record is the picked team's all-time record against the
puck line across every graded pick so far
</p>
<p class="disclaimer">
Paper-trading analysis only, not betting advice. Scores are a config-driven
weighted heuristic (see policy.yaml), not a prediction guarantee.
</p>
<p class="updated">Last updated {generation_timestamp()}</p>
{winnings_script}
</body>
</html>
"""
    path = DOCS_REPORTS_DIR / f"picks_{target_date}.html"
    with open(path, "w") as f:
        f.write(page)

    # A real symlink would be more "correct," but GitHub Pages builds in
    # Jekyll's safe mode, which ignores symlinked files -- it would 404 once
    # published. A duplicate file at a stable name is the static-hosting-safe
    # equivalent of "current -> today's picks". Only written when target_date
    # is actually today, so re-rendering a past date (e.g. the lookback
    # refresh in run_daily.py) never clobbers it with stale content.
    if target_date == date_cls.today().isoformat():
        with open(DOCS_REPORTS_DIR / "current.html", "w") as f:
            f.write(page)

    return path


def update_index() -> Path:
    """Regenerate docs/index.html linking to every report in docs/reports/, newest first.

    :returns: Path to the written index file.
    """
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    report_files = sorted(DOCS_REPORTS_DIR.glob("picks_*.html"), reverse=True)

    todays_picks_link = (
        '<p><a href="reports/picks/current.html"><strong>Today\'s Picks &rarr;</strong></a></p>'
        if (DOCS_REPORTS_DIR / "current.html").exists()
        else ""
    )
    record_link = (
        '<p><a href="reports/record.html">Performance record &amp; ROI &rarr;</a></p>'
        if (DOCS_DIR / "reports" / "record.html").exists()
        else ""
    )

    links = "\n".join(
        f'<li><a href="reports/picks/{path.name}">'
        f"{datetime.strptime(path.stem.removeprefix('picks_'), '%Y-%m-%d').strftime('%B %d, %Y')}"
        f"</a></li>"
        for path in report_files
    )

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>NHL Paper Betting Picks</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{HTML_STYLE}</style>
</head>
<body>
<h1>NHL Paper Betting Picks</h1>
<p class="subtitle">Every game, every day, ranked by edge from the policy-driven scoring engine.</p>
{todays_picks_link}
{record_link}
<p><a href="reports/policies/policy.html">Current scoring policy &amp; weights &rarr;</a></p>
<ul>
{links}
</ul>
<p class="updated">Last updated {generation_timestamp()}</p>
</body>
</html>
"""
    path = DOCS_DIR / "index.html"
    with open(path, "w") as f:
        f.write(page)
    return path


def log_picks(conn: sqlite3.Connection, target_date: str, picks: list[dict]) -> None:
    """Record the day's picks in picks_log, upserting by (date, game_id).

    An upsert (rather than delete-then-insert) is required here because
    build_report() gets re-run for already-graded past dates too, to refresh
    their published HTML with final scores -- a plain delete-then-insert would
    either wipe out recorded `result`/`straight_up_result`/`graded_at` values,
    or (since the old delete only matched ungraded rows) insert a duplicate
    row for an already-graded game. The upsert updates only the
    pick/edge/spread/moneyline columns and leaves grading columns untouched. Ungraded
    rows for games no longer in `picks` (e.g. a postponed game) are
    still pruned, same as before.

    :param conn: Open connection to the schedule database.
    :param target_date: Date the picks were made, as YYYY-MM-DD.
    :param picks: Picks as returned by :func:`build_picks`.
    """
    game_ids = [pick["game_id"] for pick in picks]
    placeholders = ",".join("?" * len(game_ids))
    conn.execute(
        f"""
        DELETE FROM picks_log
        WHERE date = ? AND result IS NULL AND game_id NOT IN ({placeholders})
        """,
        [target_date, *game_ids],
    )
    conn.executemany(
        """
        INSERT INTO picks_log
            (date, game_id, pick, predicted_edge, spread_at_pick, moneyline_at_pick)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(date, game_id) DO UPDATE SET
            pick = excluded.pick,
            predicted_edge = excluded.predicted_edge,
            spread_at_pick = excluded.spread_at_pick,
            moneyline_at_pick = excluded.moneyline_at_pick
        """,
        [
            (
                target_date,
                pick["game_id"],
                pick["pick"],
                pick["predicted_edge"],
                pick["spread_at_pick"],
                pick["moneyline_at_pick"],
            )
            for pick in picks
        ],
    )


def print_report(target_date: str, picks: list[dict]) -> None:
    """Print every pick as a plain-text table.

    :param target_date: Date the report covers, as YYYY-MM-DD.
    :param picks: Picks to display.
    """
    print(f"\n{len(picks)} picks for {target_date}\n" + "-" * 70)
    for i, pick in enumerate(picks, start=1):
        spread = f"{pick['spread_at_pick']:+.1f}" if pick["spread_at_pick"] is not None else "n/a"
        site = "home" if pick["pick_is_home"] else "away"
        matchup = f"{pick['away_team']} @ {pick['home_team']}"
        notes = f" [{'; '.join(pick['notes'])}]" if pick["notes"] else ""
        print(
            f"{i:>2}. PICK {pick['pick']} ({site}) -- {matchup:<9} "
            f"edge={pick['predicted_edge']:.3f} puck_line={spread}{notes}"
        )


def build_report(target_date: str) -> None:
    """Score, rank, print, and log every one of the day's picks.

    :param target_date: Date to report on, as YYYY-MM-DD.
    """
    init_db()
    conn = get_connection()
    with conn:
        picks = build_picks(conn, target_date)
        if picks:
            log_picks(conn, target_date, picks)

    if not picks:
        print(f"No scored games found for {target_date}. Run score.py first.")
        conn.close()
        return

    print_report(target_date, picks)
    csv_path = write_csv(target_date, picks)
    html_path = render_html_report(target_date, picks)
    index_path = update_index()
    print(f"\nWrote {csv_path}\nWrote {html_path}\nWrote {index_path}")
    conn.close()


def all_report_dates() -> list[str]:
    """Every date that currently has a published report, oldest first.

    Used to re-render every past report after grading, since stats like a
    team's all-time ATS record (see :func:`team_ats_records`) change for
    *every* report that ever featured that team, not just the date that was
    just graded.

    :returns: Dates with at least one picks_log row, as YYYY-MM-DD, sorted ascending.
    """
    init_db()
    conn = get_connection()
    with conn:
        rows = conn.execute("SELECT DISTINCT date FROM picks_log ORDER BY date").fetchall()
    conn.close()
    return [row[0] for row in rows]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the daily picks report")
    parser.add_argument("--date", default=date_cls.today().isoformat(), help="YYYY-MM-DD")
    args = parser.parse_args()
    build_report(args.date)
