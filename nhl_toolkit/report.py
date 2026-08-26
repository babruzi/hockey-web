"""
Builds the daily Top-10 picks report from `daily_scores`: for each game,
whichever team scored higher is "the pick," ranked across the day's
slate by the score gap between the two teams. Writes the result to a
local CSV digest, an HTML page under docs/reports/ (for GitHub Pages),
and logs each pick to `picks_log` for later grading/backtesting.

Run this after score.py has scored the target date.

Usage:
    python report.py --date 2026-10-05
    python report.py                      # defaults to today
"""

import argparse
import csv
import sqlite3
from datetime import date as date_cls
from datetime import datetime
from pathlib import Path
from typing import Optional

from db import get_connection, init_db

REPORTS_DIR = Path(__file__).parent / "reports"

# docs/ lives at the repo root (one level up from nhl_toolkit/), since
# GitHub Pages serves a repo from either the root or a /docs folder.
DOCS_DIR = Path(__file__).parent.parent / "docs"
DOCS_REPORTS_DIR = DOCS_DIR / "reports"


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


def build_picks(conn: sqlite3.Connection, target_date: str) -> list[dict]:
    """Rank each game by score gap and pick the higher-scoring side.

    :param conn: Open connection to the schedule database.
    :param target_date: Date to report on, as YYYY-MM-DD.
    :returns: Pick dicts sorted by predicted_edge descending.
    """
    rows = conn.execute(
        """
        SELECT ds.game_id, ds.team_id, ds.total_score, g.home_team, g.away_team
        FROM daily_scores ds
        JOIN games g ON g.game_id = ds.game_id
        WHERE ds.date = ?
        """,
        (target_date,),
    ).fetchall()

    scores_by_game: dict[int, dict] = {}
    for game_id, team_id, total_score, home_team, away_team in rows:
        game = scores_by_game.setdefault(
            game_id, {"home_team": home_team, "away_team": away_team, "scores": {}}
        )
        game["scores"][team_id] = total_score

    picks = []
    for game_id, game in scores_by_game.items():
        home_score = game["scores"].get(game["home_team"])
        away_score = game["scores"].get(game["away_team"])
        if home_score is None or away_score is None:
            continue

        pick_team = game["home_team"] if home_score >= away_score else game["away_team"]
        predicted_edge = abs(home_score - away_score)
        picks.append(
            {
                "game_id": game_id,
                "pick": pick_team,
                "opponent": game["away_team"]
                if pick_team == game["home_team"]
                else game["home_team"],
                "predicted_edge": predicted_edge,
                "spread_at_pick": latest_consensus_spread(conn, game_id, pick_team),
            }
        )

    picks.sort(key=lambda pick: pick["predicted_edge"], reverse=True)
    return picks


def write_csv(target_date: str, picks: list[dict]) -> Path:
    """Write the Top-10 picks to a CSV digest file.

    :param target_date: Date the report covers, as YYYY-MM-DD.
    :param picks: Picks as returned by :func:`build_picks`, already limited to the top 10.
    :returns: Path to the written CSV file.
    """
    REPORTS_DIR.mkdir(exist_ok=True)
    path = REPORTS_DIR / f"picks_{target_date}.csv"
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["game_id", "pick", "opponent", "predicted_edge", "spread_at_pick"]
        )
        writer.writeheader()
        writer.writerows(picks)
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
}
@media (prefers-color-scheme: dark) {
    :root {
        --bg: #16181d;
        --fg: #e6e6e6;
        --muted: #9ca3af;
        --border: #2c2f36;
        --row-alt: #1c1f26;
        --accent: #60a5fa;
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
a { color: var(--accent); }
.disclaimer { color: var(--muted); font-size: 0.85rem; margin-top: 2rem; }
"""


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

    rows = "\n".join(
        f"""
        <tr>
            <td class="rank">{i}</td>
            <td>{pick["pick"]}</td>
            <td>{pick["opponent"]}</td>
            <td class="edge">{pick["predicted_edge"]:.3f}</td>
            <td>{format_spread(pick)}</td>
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
<p><a href="../index.html">&larr; All reports</a></p>
<h1>Top {len(picks)} Picks</h1>
<p class="subtitle">{pretty_date} &middot; generated by the NHL paper-betting toolkit</p>
<table>
<thead>
<tr><th>#</th><th>Pick</th><th>Opponent</th><th>Edge</th><th>Spread</th></tr>
</thead>
<tbody>{rows}
</tbody>
</table>
<p class="disclaimer">
Paper-trading analysis only, not betting advice. Scores are a config-driven
weighted heuristic (see policy.yaml), not a prediction guarantee.
</p>
</body>
</html>
"""
    path = DOCS_REPORTS_DIR / f"picks_{target_date}.html"
    with open(path, "w") as f:
        f.write(page)
    return path


def update_index() -> Path:
    """Regenerate docs/index.html linking to every report in docs/reports/, newest first.

    :returns: Path to the written index file.
    """
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    report_files = sorted(DOCS_REPORTS_DIR.glob("picks_*.html"), reverse=True)

    links = "\n".join(
        f'<li><a href="reports/{path.name}">'
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
<ul>
{links}
</ul>
</body>
</html>
"""
    path = DOCS_DIR / "index.html"
    with open(path, "w") as f:
        f.write(page)
    return path


def log_picks(conn: sqlite3.Connection, target_date: str, picks: list[dict]) -> None:
    """Record the day's picks in picks_log for later grading, replacing any ungraded entries.

    :param conn: Open connection to the schedule database.
    :param target_date: Date the picks were made, as YYYY-MM-DD.
    :param picks: Picks as returned by :func:`build_picks`.
    """
    conn.execute("DELETE FROM picks_log WHERE date = ? AND result IS NULL", (target_date,))
    conn.executemany(
        """
        INSERT INTO picks_log (date, game_id, pick, predicted_edge, spread_at_pick)
        VALUES (?, ?, ?, ?, ?)
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
    print(f"\nTop {len(picks)} picks for {target_date}\n" + "-" * 60)
    for i, pick in enumerate(picks, start=1):
        spread = f"{pick['spread_at_pick']:+.1f}" if pick["spread_at_pick"] is not None else "n/a"
        print(
            f"{i:>2}. {pick['pick']} vs {pick['opponent']:<4} "
            f"edge={pick['predicted_edge']:.3f} spread={spread}"
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
        if not picks:
            print(f"No scored games found for {target_date}. Run score.py first.")
            conn.close()
            return
        log_picks(conn, target_date, picks)
    print_report(target_date, picks)
    csv_path = write_csv(target_date, picks)
    html_path = render_html_report(target_date, picks)
    index_path = update_index()
    print(f"\nWrote {csv_path}\nWrote {html_path}\nWrote {index_path}")
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the daily Top-10 picks report")
    parser.add_argument("--date", default=date_cls.today().isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--top", type=int, default=10, help="Number of picks to include")
    args = parser.parse_args()
    build_report(args.date, args.top)
