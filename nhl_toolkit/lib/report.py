"""
Builds the daily Top-10 picks report from `daily_scores`: for each game,
whichever team scored higher is "the pick," ranked across the day's
slate by the score gap between the two teams. Writes the result to a
local CSV digest, an HTML page under docs/reports/ (for GitHub Pages),
and logs each pick to `picks_log` for later grading/backtesting.

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

from db import get_connection, init_db

REPORTS_DIR = Path(__file__).parent.parent / "reports"

# docs/ lives at the repo root (two levels up from lib/), since
# GitHub Pages serves a repo from either the root or a /docs folder.
DOCS_DIR = Path(__file__).parent.parent.parent / "docs"
DOCS_REPORTS_DIR = DOCS_DIR / "reports" / "picks"
DOCS_POLICIES_DIR = DOCS_DIR / "reports" / "policies"


def latest_consensus_spread(
    conn: sqlite3.Connection, game_id: int, team_id: str
) -> Optional[float]:
    """Average the most recent spread quote per bookmaker for one team in one game.

    :param conn: Open connection to the schedule database.
    :param game_id: The game to look up odds for.
    :param team_id: The team whose spread to return (its home or away line).
    :returns: The consensus spread, or None if no odds have been fetched for this game.
    """
    rows = conn.execute(
        """
        SELECT o.home_spread, o.away_spread, g.home_team
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

    spreads = [
        home_spread if team_id == home_team else away_spread
        for home_spread, away_spread, home_team in rows
        if (home_spread if team_id == home_team else away_spread) is not None
    ]
    return sum(spreads) / len(spreads) if spreads else None


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
        picks.append(
            {
                "game_id": game_id,
                "home_team": game["home_team"],
                "away_team": game["away_team"],
                "pick": pick_team,
                "pick_is_home": pick_team == game["home_team"],
                "predicted_edge": predicted_edge,
                "spread_at_pick": latest_consensus_spread(conn, game_id, pick_team),
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
    """Write the Top-10 picks to a CSV digest file.

    :param target_date: Date the report covers, as YYYY-MM-DD.
    :param picks: Picks as returned by :func:`build_picks`, already limited to the top 10.
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
    max-width: 760px;
    margin: 2rem auto;
    padding: 0 1rem;
}
h1 { font-size: 1.4rem; margin-bottom: 0.25rem; }
.subtitle { color: var(--muted); margin-top: 0; margin-bottom: 1.5rem; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border); }
tr:nth-child(even) td { background: var(--row-alt); }
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
"""


def generation_timestamp() -> str:
    """The current time, formatted for a page's "last updated" footer.

    :returns: e.g. "October 01, 2026 at 03:42 PM UTC".
    """
    return datetime.now(timezone.utc).strftime("%B %d, %Y at %I:%M %p UTC")


def render_html_report(target_date: str, picks: list[dict]) -> Path:
    """Render the day's Top-N picks as a static HTML page under docs/reports/.

    :param target_date: Date the report covers, as YYYY-MM-DD.
    :param picks: Picks as returned by :func:`build_picks`, already limited to the top N.
    :returns: Path to the written HTML file.
    """
    DOCS_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    pretty_date = datetime.strptime(target_date, "%Y-%m-%d").strftime("%B %d, %Y")

    def format_spread(pick: dict) -> str:
        return f"{pick['spread_at_pick']:+.1f}" if pick["spread_at_pick"] is not None else "n/a"

    def format_team(team: str, is_pick: bool) -> str:
        return f'<strong class="pick">{team}</strong>' if is_pick else team

    def format_notes(pick: dict) -> str:
        return "; ".join(pick["notes"]) if pick["notes"] else "&mdash;"

    def format_final_score(pick: dict) -> str:
        if pick["final_home_score"] is None or pick["final_away_score"] is None:
            return '<span class="notes">&mdash;</span>'
        return f"{pick['final_away_score']}&ndash;{pick['final_home_score']}"

    def format_outcome_plain(value: Optional[str]) -> str:
        if value in ("win", "loss", "push"):
            return value.capitalize()
        return '<span class="notes">&mdash;</span>'

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

    rows = "\n".join(
        f"""
        <tr>
            <td class="rank">{i}</td>
            <td>{format_team(pick["away_team"], not pick["pick_is_home"])}</td>
            <td class="notes">@</td>
            <td>{format_team(pick["home_team"], pick["pick_is_home"])}</td>
            <td class="edge">{pick["predicted_edge"]:.3f}</td>
            <td>{format_spread(pick)}</td>
            <td class="edge">{format_final_score(pick)}</td>
            <td>{format_outcome_plain(pick["straight_up_result"])}</td>
            <td>{format_ats(pick)}</td>
            <td class="edge">{format_team_ats_record(pick)}</td>
            <td class="notes">{format_notes(pick)}</td>
        </tr>"""
        for i, pick in enumerate(picks, start=1)
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
<h1>Top {len(picks)} Picks</h1>
<p class="subtitle">
{pretty_date} &middot; generated by the NHL paper-betting toolkit &middot;
the <strong class="pick">green, bolded</strong> team is the pick (Score column is also
Away&ndash;Home) &middot; Straight Up/Vs. Spread show once the game is final, color is only
used for Vs. Spread &middot; Team ATS Record is the picked team's all-time record against
the spread across every graded pick so far
</p>
<table>
<thead>
<tr>
    <th>#</th><th>Away</th><th></th><th>Home</th><th>Edge</th><th>Spread</th><th>Score</th>
    <th>Straight Up</th><th>Vs. Spread</th><th>Team ATS Record</th><th>Notes</th>
</tr>
</thead>
<tbody>{rows}
</tbody>
</table>
<p class="disclaimer">
Paper-trading analysis only, not betting advice. Scores are a config-driven
weighted heuristic (see policy.yaml), not a prediction guarantee.
</p>
<p class="updated">Last updated {generation_timestamp()}</p>
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
<p class="subtitle">Daily Top-10 reports from the policy-driven scoring engine.</p>
{todays_picks_link}
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
    pick/edge/spread columns and leaves grading columns untouched. Ungraded
    rows for games no longer in `picks` (e.g. a dropped-out top-N game) are
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
        INSERT INTO picks_log (date, game_id, pick, predicted_edge, spread_at_pick)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(date, game_id) DO UPDATE SET
            pick = excluded.pick,
            predicted_edge = excluded.predicted_edge,
            spread_at_pick = excluded.spread_at_pick
        """,
        [
            (
                target_date,
                pick["game_id"],
                pick["pick"],
                pick["predicted_edge"],
                pick["spread_at_pick"],
            )
            for pick in picks
        ],
    )


def print_report(target_date: str, picks: list[dict]) -> None:
    """Print the Top-10 picks as a plain-text table.

    :param target_date: Date the report covers, as YYYY-MM-DD.
    :param picks: Picks to display, already limited to the top 10.
    """
    print(f"\nTop {len(picks)} picks for {target_date}\n" + "-" * 70)
    for i, pick in enumerate(picks, start=1):
        spread = f"{pick['spread_at_pick']:+.1f}" if pick["spread_at_pick"] is not None else "n/a"
        site = "home" if pick["pick_is_home"] else "away"
        matchup = f"{pick['away_team']} @ {pick['home_team']}"
        notes = f" [{'; '.join(pick['notes'])}]" if pick["notes"] else ""
        print(
            f"{i:>2}. PICK {pick['pick']} ({site}) -- {matchup:<9} "
            f"edge={pick['predicted_edge']:.3f} spread={spread}{notes}"
        )


def build_report(target_date: str, top_n: int = 10) -> None:
    """Score, rank, print, and log the day's Top-N picks.

    :param target_date: Date to report on, as YYYY-MM-DD.
    :param top_n: How many top-edge picks to keep.
    """
    init_db()
    conn = get_connection()
    with conn:
        picks = build_picks(conn, target_date)[:top_n]
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
    parser = argparse.ArgumentParser(description="Build the daily Top-10 picks report")
    parser.add_argument("--date", default=date_cls.today().isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--top", type=int, default=10, help="Number of picks to include")
    args = parser.parse_args()
    build_report(args.date, args.top)
