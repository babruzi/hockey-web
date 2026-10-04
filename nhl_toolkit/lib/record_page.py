"""
Renders docs/reports/record.html: picks_log's overall record and ROI for
all three independent bet types -- Money Line, Puck Line, and Over/Under
(see report.py's puck_line_recommendation()/total_recommendation()) --
plus a per-policy_version Money Line breakdown for comparing before/after
a weight change (Puck Line/Over-Under aren't policy.yaml-driven, so a
per-policy_version breakdown wouldn't mean anything for those two), and a
third section replaying every policy_version against the exact same full
slate of completed games (policy_backtest.py) -- unlike the "By Policy
Version" section above it, which only shows how each version did during
the different, non-overlapping stretch it happened to be live for, this
one is a fair head-to-head comparison. This is the published,
no-terminal-needed view of the same numbers backtest.py/policy_backtest.py
already print to the console -- it reuses their
policy_performance()/bet_type_totals()/build_policy_backtest() rather
than re-deriving them.

Regenerated automatically by run_daily.py (right after grading, so this
is always current as of the last graded games), or run standalone:

Usage:
    python lib/record_page.py
"""

from pathlib import Path
from typing import Optional

from backtest import bet_type_totals, policy_performance
from db import get_connection
from grade import STAKE
from policy_backtest import build_policy_backtest, rank_by_roi
from report import DOCS_DIR, HTML_STYLE, generation_timestamp, strategy_markets

RECORD_PATH = DOCS_DIR / "reports" / "record.html"

CHART_TRACKS = [
    ("ml", "Money Line", "--chart-ml"),
    ("pl", "Puck Line", "--chart-pl"),
    ("ou", "Over/Under", "--chart-ou"),
    ("strategy", "Strategy", "--chart-strategy"),
]


def combine_performance(performance: list) -> dict:
    """Sum every policy_version's record into one overall total.

    :param performance: Rows from :func:`backtest.policy_performance`.
    :returns: A single dict with the same keys as one policy_performance row.
    """
    totals = {
        "su_wins": 0,
        "su_losses": 0,
        "ats_wins": 0,
        "ats_losses": 0,
        "ats_pushes": 0,
        "total_profit": 0.0,
        "graded_bet_count": 0,
    }
    for row in performance:
        for key in totals:
            value = row[key]
            if value is not None:
                totals[key] += value
    return totals


def bankroll_series(conn) -> list[dict]:
    """Day-by-day cumulative P&L for Money Line, Puck Line, Over/Under, and Strategy.

    The Strategy track is computed the same way report.py's day-total does
    (see strategy_markets()): Puck Line's own profit whenever it has a
    recommendation, plus Money Line's profit too on days it agrees with the
    Puck Line pick. A date with nothing graded at all is skipped rather than
    plotted flat, so an ungraded "today" doesn't visually flatten the chart.

    :param conn: Open connection to the schedule database.
    :returns: One dict per graded date: {"date", "ml", "pl", "ou", "strategy"},
        each value the *cumulative* total through that date, in date order.
    """
    rows = conn.execute(
        """
        SELECT date, pick, puck_line_pick, profit_10, puck_line_profit_10, total_profit_10
        FROM picks_log
        ORDER BY date, game_id
        """
    ).fetchall()

    daily: dict[str, dict] = {}
    for date, pick, puck_line_pick, ml_profit, pl_profit, ou_profit in rows:
        day = daily.setdefault(
            date, {"ml": 0.0, "pl": 0.0, "ou": 0.0, "strategy": 0.0, "has_any": False}
        )
        if ml_profit is not None:
            day["ml"] += ml_profit
            day["has_any"] = True
        if pl_profit is not None:
            day["pl"] += pl_profit
            day["has_any"] = True
        if ou_profit is not None:
            day["ou"] += ou_profit
            day["has_any"] = True
        markets = strategy_markets(pick, puck_line_pick)
        if "pl" in markets and pl_profit is not None:
            day["strategy"] += pl_profit
            day["has_any"] = True
        if "ml" in markets and ml_profit is not None:
            day["strategy"] += ml_profit
            day["has_any"] = True

    running = {"ml": 0.0, "pl": 0.0, "ou": 0.0, "strategy": 0.0}
    series = []
    for date in sorted(daily):
        day = daily[date]
        if not day["has_any"]:
            continue
        for key in running:
            running[key] += day[key]
        series.append({"date": date, **running})
    return series


def current_streak(conn) -> Optional[tuple[str, int]]:
    """The most recent run of consecutive straight-up Money Line wins or losses.

    :param conn: Open connection to the schedule database.
    :returns: ("win"/"loss", length), or None if nothing's graded yet.
    """
    rows = conn.execute(
        """
        SELECT straight_up_result FROM picks_log
        WHERE straight_up_result IS NOT NULL
        ORDER BY date, game_id
        """
    ).fetchall()
    if not rows:
        return None
    results = [row[0] for row in rows]
    last = results[-1]
    length = 0
    for result in reversed(results):
        if result != last:
            break
        length += 1
    return last, length


def best_worst_pick(conn) -> tuple[Optional[tuple], Optional[tuple]]:
    """The single best and worst graded Money Line picks by dollar profit.

    :param conn: Open connection to the schedule database.
    :returns: (best, worst), each (date, pick, profit_10), or None if nothing's graded.
    """
    best = conn.execute(
        """
        SELECT date, pick, profit_10 FROM picks_log
        WHERE profit_10 IS NOT NULL ORDER BY profit_10 DESC LIMIT 1
        """
    ).fetchone()
    worst = conn.execute(
        """
        SELECT date, pick, profit_10 FROM picks_log
        WHERE profit_10 IS NOT NULL ORDER BY profit_10 ASC LIMIT 1
        """
    ).fetchone()
    return best, worst


def render_bankroll_chart(series: list[dict]) -> str:
    """Render a cumulative P&L line chart as inline SVG -- no JS, no external assets.

    :param series: Result of :func:`bankroll_series`.
    :returns: An <svg>...</svg> element, or a "not enough data" message.
    """
    if len(series) < 2:
        return '<p class="notes">Not enough graded days yet for a chart.</p>'

    width, height = 760, 260
    pad_left, pad_right, pad_top, pad_bottom = 46, 40, 16, 24
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    all_values = [point[key] for point in series for key, _, _ in CHART_TRACKS]
    lo, hi = min(all_values + [0.0]), max(all_values + [0.0])
    span = hi - lo or 1.0

    def x_at(i: int) -> float:
        return pad_left + (i / (len(series) - 1)) * plot_w

    def y_at(value: float) -> float:
        return pad_top + plot_h - ((value - lo) / span) * plot_h

    zero_y = y_at(0.0)
    lines = []
    end_labels = []
    for key, _label, color_var in CHART_TRACKS:
        points = " ".join(f"{x_at(i):.1f},{y_at(point[key]):.1f}" for i, point in enumerate(series))
        lines.append(
            f'<polyline points="{points}" fill="none" stroke="var({color_var})" stroke-width="2" />'
        )
        end_value = series[-1][key]
        end_labels.append(
            f'<text x="{x_at(len(series) - 1) + 6:.1f}" y="{y_at(end_value):.1f}" '
            f'fill="var({color_var})" font-size="11" dominant-baseline="middle">'
            f"{end_value:+.0f}</text>"
        )

    return f"""<svg viewBox="0 0 {width} {height}" class="bankroll-chart" role="img"
     aria-label="Cumulative profit and loss over the season, per bet type">
<line x1="{pad_left}" y1="{zero_y:.1f}" x2="{width - pad_right}" y2="{zero_y:.1f}"
      stroke="var(--border)" stroke-width="1" stroke-dasharray="4 3" />
<text x="{pad_left - 6}" y="{zero_y:.1f}" fill="var(--muted)" font-size="10"
      text-anchor="end" dominant-baseline="middle">$0</text>
<text x="{pad_left - 6}" y="{pad_top:.1f}" fill="var(--muted)" font-size="10"
      text-anchor="end" dominant-baseline="middle">{hi:+.0f}</text>
<text x="{pad_left - 6}" y="{pad_top + plot_h:.1f}" fill="var(--muted)" font-size="10"
      text-anchor="end" dominant-baseline="middle">{lo:+.0f}</text>
<text x="{pad_left}" y="{height - 6}" fill="var(--muted)" font-size="10">{series[0]["date"]}</text>
<text x="{width - pad_right}" y="{height - 6}" fill="var(--muted)" font-size="10"
      text-anchor="end">{series[-1]["date"]}</text>
{"".join(lines)}
{"".join(end_labels)}
</svg>"""


def format_record_pct(wins: int, losses: int) -> str:
    """ "W-L (win %)", or "0-0 (n/a)" if there's nothing graded yet.

    :param wins: Win count.
    :param losses: Loss count.
    :returns: Formatted record string.
    """
    total = wins + losses
    if not total:
        return "0-0 (n/a)"
    return f"{wins}-{losses} ({100 * wins / total:.1f}%)"


def format_record_with_pushes(wins: int, losses: int, pushes: int) -> str:
    """ "W-L-P (win %, decided bets only)", or "...(n/a)" with nothing decided yet.

    :param wins: Win count.
    :param losses: Loss count.
    :param pushes: Push count (doesn't count toward the percentage).
    :returns: Formatted record string.
    """
    decided = wins + losses
    if not decided:
        return f"{wins}-{losses}-{pushes} (n/a)"
    return f"{wins}-{losses}-{pushes} ({100 * wins / decided:.1f}%)"


def format_roi(total_profit: float, bet_count: int) -> tuple:
    """Dollar P&L and ROI% on a flat $STAKE-per-pick moneyline stake.

    :param total_profit: Summed profit_10 across graded picks with odds.
    :param bet_count: How many graded picks had a moneyline to bet against.
    :returns: (display string, css class) -- class is "positive"/"negative"/"notes".
    """
    if not bet_count:
        return "n/a (no odds on any graded pick)", "notes"
    roi_pct = 100 * total_profit / (STAKE * bet_count)
    css_class = "positive" if total_profit >= 0 else "negative"
    return f"{total_profit:+.2f} on {bet_count} bets ({roi_pct:+.1f}%)", css_class


def format_single_pick(row: Optional[tuple]) -> tuple:
    """ "+12.40 on SJS (2026-10-01)", or a dash if nothing's graded yet.

    :param row: (date, pick, profit_10), as returned by :func:`best_worst_pick`.
    :returns: (display string, css class) -- class is "positive"/"negative"/"notes".
    """
    if row is None:
        return "&mdash;", "notes"
    date, pick, profit = row
    css_class = "positive" if profit >= 0 else "negative"
    return f"{profit:+.2f} on {pick} ({date})", css_class


def render_record_html(
    performance: list,
    bet_types: dict,
    policy_backtest_results: list[tuple[str, dict]],
    bankroll: list[dict],
    streak: Optional[tuple[str, int]],
    best_pick: Optional[tuple],
    worst_pick: Optional[tuple],
) -> Path:
    """Render the overall + per-policy_version record as a static HTML page.

    :param performance: Rows from :func:`backtest.policy_performance`.
    :param bet_types: Result of :func:`backtest.bet_type_totals`.
    :param policy_backtest_results: Result of :func:`policy_backtest.build_policy_backtest`.
    :param bankroll: Result of :func:`bankroll_series`.
    :param streak: Result of :func:`current_streak`.
    :param best_pick: Result of :func:`best_worst_pick` (first element).
    :param worst_pick: Result of :func:`best_worst_pick` (second element).
    :returns: Path to the written HTML file.
    """
    RECORD_PATH.parent.mkdir(parents=True, exist_ok=True)
    overall = combine_performance(performance)

    overall_su = format_record_pct(overall["su_wins"], overall["su_losses"])
    overall_ats_total = overall["ats_wins"] + overall["ats_losses"] + overall["ats_pushes"]
    overall_ats_pct = format_record_with_pushes(
        overall["ats_wins"], overall["ats_losses"], overall["ats_pushes"]
    )
    overall_roi_str, overall_roi_class = format_roi(
        overall["total_profit"], overall["graded_bet_count"]
    )
    overall_ats_total_note = f" ({overall_ats_total} graded)" if overall_ats_total else ""

    pl, ou = bet_types["puck_line"], bet_types["total"]
    pl_record = format_record_with_pushes(pl["wins"], pl["losses"], pl["pushes"])
    pl_roi_str, pl_roi_class = format_roi(pl["total_profit"], pl["graded_bet_count"])
    ou_record = format_record_with_pushes(ou["wins"], ou["losses"], ou["pushes"])
    ou_roi_str, ou_roi_class = format_roi(ou["total_profit"], ou["graded_bet_count"])

    version_rows = "\n".join(
        f"""
        <tr>
            <td>{row["policy_version"]}</td>
            <td>{format_record_pct(row["su_wins"], row["su_losses"])}</td>
            <td>{
            format_record_with_pushes(row["ats_wins"], row["ats_losses"], row["ats_pushes"])
        }</td>
            <td class="{format_roi(row["total_profit"] or 0.0, row["graded_bet_count"])[1]}">
                {format_roi(row["total_profit"] or 0.0, row["graded_bet_count"])[0]}
            </td>
        </tr>"""
        for row in performance
    )
    if not version_rows:
        version_rows = '<tr><td colspan="4" class="notes">No graded picks yet.</td></tr>'

    backtest_rows = "\n".join(
        f"""
        <tr>
            <td>{policy_version}</td>
            <td class="edge">{totals["games_evaluated"]}</td>
            <td>{format_record_pct(totals["su_wins"], totals["su_losses"])}</td>
            <td>{
            format_record_with_pushes(
                totals["ats_wins"], totals["ats_losses"], totals["ats_pushes"]
            )
        }</td>
            <td class="{format_roi(totals["total_profit"], totals["graded_bet_count"])[1]}">
                {format_roi(totals["total_profit"], totals["graded_bet_count"])[0]}
            </td>
        </tr>"""
        for policy_version, totals in rank_by_roi(policy_backtest_results)
    )
    if not backtest_rows:
        backtest_rows = '<tr><td colspan="5" class="notes">No completed games yet.</td></tr>'

    chart_svg = render_bankroll_chart(bankroll)
    if streak:
        result, length = streak
        noun = ("win" if result == "win" else "loss") + ("s" if length != 1 else "")
        streak_text = f"{length} {noun}"
    else:
        streak_text = "&mdash;"

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>NHL Picks Performance</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{HTML_STYLE}</style>
</head>
<body>
<p><a href="../index.html">&larr; All reports</a></p>
<h1>Performance Record</h1>
<p class="subtitle">
picks_log's real record so far across all three independent bet types --
Money Line, Puck Line, and Over/Under -- plus simulated ROI on a flat
${STAKE:.0f} stake per pick, had every one of that type's recommendations
been bet.
</p>

<h2>Bankroll Over Time</h2>
<p class="subtitle">
Cumulative P&amp;L on a flat ${STAKE:.0f} stake per pick, day by day, for each
bet type -- a day with nothing graded yet is skipped rather than plotted
flat.
</p>
<div class="chart-wrap">{chart_svg}</div>
<p class="chart-legend">
<span class="swatch" style="color:var(--chart-ml)">&#9632;</span> Money Line &nbsp;
<span class="swatch" style="color:var(--chart-pl)">&#9632;</span> Puck Line &nbsp;
<span class="swatch" style="color:var(--chart-ou)">&#9632;</span> Over/Under &nbsp;
<span class="swatch" style="color:var(--chart-strategy)">&#9632;</span> Strategy
</p>

<table>
<thead><tr><th></th><th></th></tr></thead>
<tbody>
<tr><td>Current Streak (Money Line)</td><td>{streak_text}</td></tr>
<tr><td>Best Single Pick (Money Line)</td>
    <td class="{format_single_pick(best_pick)[1]}">{format_single_pick(best_pick)[0]}</td></tr>
<tr><td>Worst Single Pick (Money Line)</td>
    <td class="{format_single_pick(worst_pick)[1]}">{format_single_pick(worst_pick)[0]}</td></tr>
</tbody>
</table>

<table>
<thead><tr><th></th><th>Record</th></tr></thead>
<tbody>
<tr><td>Moneyline</td><td>{overall_su}</td></tr>
<tr><td>Vs. Puck Line</td><td>{overall_ats_pct}{overall_ats_total_note}</td></tr>
<tr><td>Moneyline ROI</td><td class="{overall_roi_class}">{overall_roi_str}</td></tr>
<tr><td>Puck Line Record</td><td>{pl_record}</td></tr>
<tr><td>Puck Line ROI</td><td class="{pl_roi_class}">{pl_roi_str}</td></tr>
<tr><td>Over/Under Record</td><td>{ou_record}</td></tr>
<tr><td>Over/Under ROI</td><td class="{ou_roi_class}">{ou_roi_str}</td></tr>
</tbody>
</table>

<h2>By Policy Version</h2>
<table>
<thead>
<tr><th>Version</th><th>Moneyline</th><th>Vs. Puck Line</th><th>Moneyline ROI</th></tr>
</thead>
<tbody>{version_rows}
</tbody>
</table>

<h2>Policy Backtest</h2>
<p class="subtitle">
Every policy_version replayed against the exact same full slate of completed
games, instead of only the different (non-overlapping) stretch each one
actually happened to be live for -- a fair head-to-head comparison, ranked
by moneyline ROI%. See policy_backtest.py.
</p>
<table>
<thead>
<tr>
    <th>Version</th><th>Games</th><th>Moneyline</th><th>Vs. Puck Line</th><th>Moneyline ROI</th>
</tr>
</thead>
<tbody>{backtest_rows}
</tbody>
</table>

<p class="disclaimer">
"Moneyline" and "Vs. Puck Line" above are both about the scoring engine's
one pick (policy.yaml's weighted total_score); "Puck Line Record" and
"Over/Under Record" are separate, independent recommendations that can
name a different team or side (see the picks pages for why) -- each ROI
figure assumes a flat ${STAKE:.0f} stake per pick at the price recorded
when that type's recommendation was made, and only counts picks that had
odds on record. The Policy Backtest table is a simulation, not a record of
real picks -- it's what each policy_version's Money Line pick would have
been on every completed game, graded against the real final score and
whatever odds were on record, not what was actually logged in picks_log
at the time. Paper-trading analysis only, not betting advice.
</p>
<p class="updated">Last updated {generation_timestamp()}</p>
</body>
</html>
"""
    with open(RECORD_PATH, "w") as f:
        f.write(page)
    return RECORD_PATH


def build_record_page() -> None:
    """Load picks_log's performance and render the record page."""
    conn = get_connection()
    with conn:
        performance = policy_performance(conn)
        bet_types = bet_type_totals(conn)
        bankroll = bankroll_series(conn)
        streak = current_streak(conn)
        best_pick, worst_pick = best_worst_pick(conn)
    conn.close()
    policy_backtest_results = build_policy_backtest()
    path = render_record_html(
        performance, bet_types, policy_backtest_results, bankroll, streak, best_pick, worst_pick
    )
    print(f"Wrote {path}")


if __name__ == "__main__":
    build_record_page()
