"""
Renders docs/reports/record.html: picks_log's overall record and ROI for
all three independent bet types -- Money Line, Puck Line, and Over/Under
(see report.py's puck_line_recommendation()/total_recommendation()), plus
the Live Policy at High Edge section -- the currently-live policy,
simulated against this season's odds-covered games above a high edge
bar (policy_backtest.py). This is the published, no-terminal-needed view
of the same numbers backtest.py/policy_backtest.py already print to the
console -- it reuses their policy_performance()/bet_type_totals() rather
than re-deriving them.

Used to also carry a "By Policy Version" table (per-policy_version Money
Line breakdown from real picks_log) and a "Policy Backtest" table
(policy_backtest.py's build_policy_backtest(), replaying every known
policy_version fairly against the same full history) -- both removed
2026-10-23 at the user's request, once the live policy settled on
2026-10-v3 and those cross-version comparisons stopped being useful day
to day. policy_backtest.py itself is unchanged and still prints both via
its own `python lib/policy_backtest.py` CLI if that comparison is ever
needed again.

Regenerated automatically by run_daily.py (right after grading, so this
is always current as of the last graded games), or run standalone:

Usage:
    python lib/record_page.py
"""

from pathlib import Path

from backtest import bet_type_totals, policy_performance
from db import get_connection
from grade import STAKE
from policy_backtest import (
    LIVE_POLICY_MIN_EDGE,
    build_live_policy_edge_backtest,
    build_live_policy_edge_series,
)
from report import DOCS_DIR, HTML_STYLE, generation_timestamp, strategy_markets

RECORD_PATH = DOCS_DIR / "reports" / "record.html"

CHART_TRACKS = [
    ("ml", "Money Line", "--chart-ml"),
    ("pl", "Puck Line", "--chart-pl"),
    ("ou", "Over/Under", "--chart-ou"),
    ("strategy", "Strategy", "--chart-strategy"),
    ("live_ml", "Live Edge ML", "--chart-live-ml"),
    ("live_pl", "Live Edge PL", "--chart-live-pl"),
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
    (see strategy_markets()): Money Line only, on disagree games only --
    this track stays at the flat $STAKE basis like the other three, not
    report.py's own STRATEGY_ML_STAKE display rescale. A date with
    nothing graded at all is skipped rather than plotted flat, so an
    ungraded "today" doesn't visually flatten the chart.

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
        if "ml" in strategy_markets(pick, puck_line_pick) and ml_profit is not None:
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


def merge_live_edge_series(series: list[dict], live_edge_daily: list[dict]) -> list[dict]:
    """Fold the live-policy-at-high-edge daily P&L into bankroll_series()'s series.

    Unlike that series' own tracks (derived from whatever was actually bet
    under whichever policy was live on a given day), this track is a
    simulated replay of the *current* live policy against every date --
    see policy_backtest.py's build_live_policy_edge_backtest() for why that
    comparison is deliberately not "what was actually bet." Sharing one
    merged series (rather than two separately-plotted ones) keeps both on
    the same x-axis/date alignment for free, since every qualifying
    high-edge date is already a date bankroll_series() has a point for (it
    takes a completed, graded game to qualify, and every completed graded
    game already has a picks_log row feeding bankroll_series()).

    :param series: Result of :func:`bankroll_series` (date-ordered).
    :param live_edge_daily: Result of
        :func:`policy_backtest.build_live_policy_edge_series`.
    :returns: The same series, each point extended with "live_ml"/"live_pl"
        running cumulative totals (0 added on a date with no qualifying
        game, not skipped, since that's a real "nothing cleared the edge
        that day," not "not graded yet").
    """
    daily_by_date = {point["date"]: point for point in live_edge_daily}
    running_ml = running_pl = 0.0
    merged = []
    for point in series:
        day = daily_by_date.get(point["date"])
        if day:
            running_ml += day["ml_profit"]
            running_pl += day["pl_profit"]
        merged.append({**point, "live_ml": running_ml, "live_pl": running_pl})
    return merged


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


STAKING_SPLIT_SCENARIOS = [
    ("Full Money Line / Full Puck Line", 1.0, 1.0),
    ("Full Money Line / Half Puck Line", 1.0, 0.5),
    ("Half Money Line / Full Puck Line", 0.5, 1.0),
    ("Full Money Line / Quarter Puck Line", 1.0, 0.25),
]


def staking_split_results(live_edge_totals: dict) -> list[tuple]:
    """Combined P&L/ROI for a few ML/PL stake-size ratios, on the same
    Live Policy at High Edge games.

    Purely illustrative, not a staking recommendation: picking a ratio by
    checking which one would have maximized ROI on this same small,
    already-observed sample is curve-fitting, not a real edge -- there's
    no reason whichever ratio looks best here would keep working on new
    games just because it fit these specific ones. The real-world reason
    to size a correlated secondary bet smaller is to reduce variance, not
    to chase a backward-looking ROI number.

    :param live_edge_totals: One policy's totals dict, from
        :func:`policy_backtest.simulate_policy` (via
        :func:`policy_backtest.build_live_policy_edge_backtest`).
    :returns: (label, combined_profit, combined_staked, roi_pct) tuples --
        roi_pct is None if nothing was staked in that scenario.
    """
    ml_profit = live_edge_totals["total_profit"]
    ml_bets = live_edge_totals["graded_bet_count"]
    pl_profit = live_edge_totals["puck_line_profit"]
    pl_bets = live_edge_totals["puck_line_bet_count"]

    results = []
    for label, ml_frac, pl_frac in STAKING_SPLIT_SCENARIOS:
        combined_profit = ml_profit * ml_frac + pl_profit * pl_frac
        combined_staked = STAKE * ml_frac * ml_bets + STAKE * pl_frac * pl_bets
        roi_pct = 100 * combined_profit / combined_staked if combined_staked else None
        results.append((label, combined_profit, combined_staked, roi_pct))
    return results


def render_record_html(
    performance: list,
    bet_types: dict,
    bankroll: list[dict],
    live_policy_edge_result: tuple[str, dict],
) -> Path:
    """Render the overall record as a static HTML page.

    :param performance: Rows from :func:`backtest.policy_performance`.
    :param bet_types: Result of :func:`backtest.bet_type_totals`.
    :param bankroll: Result of :func:`bankroll_series`, merged with
        :func:`merge_live_edge_series`.
    :param live_policy_edge_result: Result of
        :func:`policy_backtest.build_live_policy_edge_backtest`.
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

    live_policy_version, live_edge_totals = live_policy_edge_result
    live_edge_roi_str, live_edge_roi_class = format_roi(
        live_edge_totals["total_profit"], live_edge_totals["graded_bet_count"]
    )
    live_edge_pl_roi_str, live_edge_pl_roi_class = format_roi(
        live_edge_totals["puck_line_profit"], live_edge_totals["puck_line_bet_count"]
    )
    staking_rows = "\n".join(
        f"""
        <tr>
            <td>{label}</td>
            <td class="{"positive" if profit >= 0 else "negative"}">{profit:+.2f}</td>
            <td class="edge">{staked:.0f}</td>
            <td class="{"positive" if roi_pct is not None and roi_pct >= 0 else "negative"}">{
            f"{roi_pct:+.1f}%" if roi_pct is not None else "n/a"
        }</td>
        </tr>"""
        for label, profit, staked, roi_pct in staking_split_results(live_edge_totals)
    )

    chart_svg = render_bankroll_chart(bankroll)

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
flat. The two "Live Edge" lines are different from the rest: not what was
actually bet, but a day-by-day version of the Live Policy at High Edge
simulation below (the currently-live policy, replayed against every
odds-covered game, counted only once its edge clears {LIVE_POLICY_MIN_EDGE:g})
-- a day with no qualifying game adds $0 rather than being skipped, since
that's a real "nothing to bet," not "not graded yet."
</p>
<div class="chart-wrap">{chart_svg}</div>
<p class="chart-legend">
<span class="swatch" style="color:var(--chart-ml)">&#9632;</span> Money Line &nbsp;
<span class="swatch" style="color:var(--chart-pl)">&#9632;</span> Puck Line &nbsp;
<span class="swatch" style="color:var(--chart-ou)">&#9632;</span> Over/Under &nbsp;
<span class="swatch" style="color:var(--chart-strategy)">&#9632;</span> Strategy &nbsp;
<span class="swatch" style="color:var(--chart-live-ml)">&#9632;</span> Live Edge ML &nbsp;
<span class="swatch" style="color:var(--chart-live-pl)">&#9632;</span> Live Edge PL
</p>

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

<h2>Live Policy at High Edge</h2>
<p class="subtitle">
The currently-live policy (<strong>{live_policy_version}</strong>), restricted to this
season's games that actually have odds on record, and only the ones with a predicted
edge of {LIVE_POLICY_MIN_EDGE:g}+ -- the same filter and threshold as the picks page's
Minimum Edge dropdown, applied here to every qualifying game this season at once rather
than one day at a time. "Vs. Puck Line"/"Puck Line ROI" here grade the same Money Line
pick against the spread, not the independent puck_line_pick recommendation the picks
pages show (a different team, based on goal_differential rather than this policy).
</p>
<table>
<thead><tr><th></th><th>Record</th></tr></thead>
<tbody>
<tr><td>Games (edge &ge; {LIVE_POLICY_MIN_EDGE:g})</td>
    <td>{live_edge_totals["games_evaluated"]}</td></tr>
<tr><td>Moneyline</td>
    <td>{format_record_pct(live_edge_totals["su_wins"], live_edge_totals["su_losses"])}</td></tr>
<tr><td>Vs. Puck Line</td>
    <td>{
        format_record_with_pushes(
            live_edge_totals["ats_wins"],
            live_edge_totals["ats_losses"],
            live_edge_totals["ats_pushes"],
        )
    }</td></tr>
<tr><td>Moneyline ROI</td><td class="{live_edge_roi_class}">{live_edge_roi_str}</td></tr>
<tr><td>Puck Line ROI</td><td class="{live_edge_pl_roi_class}">{live_edge_pl_roi_str}</td></tr>
</tbody>
</table>

<h3>If You'd Sized Puck Line Differently</h3>
<p class="subtitle">
Combined P&amp;L on the same Live Policy at High Edge games if Puck Line had been
staked at a different fraction of the ${STAKE:.0f} Money Line stake, instead of the
full ${STAKE:.0f} both rows above assume. Purely illustrative, not a staking
recommendation -- picking a ratio because it maximized ROI on this same small,
already-observed sample would just be curve-fitting to these specific games, not a
real edge. The usual real-world reason to size a correlated second bet smaller is to
reduce variance, not to chase a backward-looking ROI number.
</p>
<table>
<thead>
<tr><th>Staking</th><th>Combined P&amp;L</th><th>Staked</th><th>ROI</th></tr>
</thead>
<tbody>{staking_rows}
</tbody>
</table>

<p class="disclaimer">
"Moneyline" and "Vs. Puck Line" above are both about the scoring engine's
one pick (policy.yaml's weighted total_score); "Puck Line Record" and
"Over/Under Record" are separate, independent recommendations that can
name a different team or side (see the picks pages for why) -- each ROI
figure assumes a flat ${STAKE:.0f} stake per pick at the price recorded
when that type's recommendation was made, and only counts picks that had
odds on record. Live Policy at High Edge is a simulation, not a record of
real picks -- it's what the currently-live policy's Money Line pick would
have been on every completed game, graded against the real final score
and whatever odds were on record, not what was actually logged in
picks_log at the time, filtered down to this season's odds-covered games
above a fairly high edge bar (a small sample by design). Paper-trading
analysis only, not betting advice.
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
    conn.close()
    live_policy_edge_result = build_live_policy_edge_backtest()
    bankroll = merge_live_edge_series(bankroll, build_live_policy_edge_series())
    path = render_record_html(
        performance,
        bet_types,
        bankroll,
        live_policy_edge_result,
    )
    print(f"Wrote {path}")


if __name__ == "__main__":
    build_record_page()
