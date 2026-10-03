"""
Renders docs/reports/record.html: picks_log's overall record and ROI for
all three independent bet types -- Money Line, Puck Line, and Over/Under
(see report.py's puck_line_recommendation()/total_recommendation()) --
plus a per-policy_version Money Line breakdown for comparing before/after
a weight change (Puck Line/Over-Under aren't policy.yaml-driven, so a
per-policy_version breakdown wouldn't mean anything for those two). This
is the published, no-terminal-needed view of the same numbers backtest.py
already prints to the console -- it reuses backtest.py's
policy_performance()/bet_type_totals() rather than re-deriving them.

Regenerated automatically by run_daily.py, or run standalone:

Usage:
    python lib/record_page.py
"""

from pathlib import Path

from backtest import bet_type_totals, policy_performance
from db import get_connection
from grade import STAKE
from report import DOCS_DIR, HTML_STYLE, generation_timestamp

RECORD_PATH = DOCS_DIR / "reports" / "record.html"


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


def render_record_html(performance: list, bet_types: dict) -> Path:
    """Render the overall + per-policy_version record as a static HTML page.

    :param performance: Rows from :func:`backtest.policy_performance`.
    :param bet_types: Result of :func:`backtest.bet_type_totals`.
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

<p class="disclaimer">
"Moneyline" and "Vs. Puck Line" above are both about the scoring engine's
one pick (policy.yaml's weighted total_score); "Puck Line Record" and
"Over/Under Record" are separate, independent recommendations that can
name a different team or side (see the picks pages for why) -- each ROI
figure assumes a flat ${STAKE:.0f} stake per pick at the price recorded
when that type's recommendation was made, and only counts picks that had
odds on record. Paper-trading analysis only, not betting advice.
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
    conn.close()
    path = render_record_html(performance, bet_types)
    print(f"Wrote {path}")


if __name__ == "__main__":
    build_record_page()
