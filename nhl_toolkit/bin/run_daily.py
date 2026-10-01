"""
Runs the full Phase 1 + Phase 2 pipeline for one date: fetches the
schedule (including a trailing lookback window to pick up final scores
for recently-completed games), grades any picks_log rows those final
scores make gradeable, updates the overall performance/ROI record page,
re-renders every past HTML report (not just the lookback window -- a
team's all-time ATS record can change any of its past reports, not
only the most recent ones), rebuilds travel/form metrics, pulls current
odds and derives market_edge from them, scores the slate, and builds
the full report (every game, CSV + HTML + picks_log).

Every step is cheap and idempotent (upsert or full-rebuild-on-run), so
running the whole chain is simpler and safer than trying to detect
which steps are "already done" -- there's no meaningful cost to redoing
them. This is meant to run once a day (e.g. via cron): the `games`
table only ever grows, `schedule_context`/`metric_values` are rebuilt
from all of it each run, and `odds` only appends -- nothing here ever
resets the database, so historical data accumulates across the season
as long as you keep running it. Odds are optional: if ODDS_API_KEY
isn't set, the fetch step is skipped with a warning, but market_edge
still rebuilds from whatever odds snapshots are already on record (so
a game with no ODDS_API_KEY today but a quote from an earlier run still
gets a value) -- the rest of the pipeline runs regardless either way
(picks just won't have a spread/market_edge for games with no quotes).

Usage (from nhl_toolkit/):
    python bin/run_daily.py --date 2026-10-05
    python bin/run_daily.py                      # defaults to today
"""

import argparse
import os
import sys
from datetime import date as date_cls
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from db import init_db  # noqa: E402
from fetch_odds import fetch_and_store_odds  # noqa: E402
from fetch_schedule import fetch_range  # noqa: E402
from form_metrics import rebuild_form_metrics  # noqa: E402
from grade import grade_all  # noqa: E402
from market_metrics import rebuild_market_metrics  # noqa: E402
from metrics import rebuild_schedule_metrics  # noqa: E402
from policy_page import build_policy_page  # noqa: E402
from record_page import build_record_page  # noqa: E402
from report import all_report_dates, build_report  # noqa: E402
from score import score_date  # noqa: E402
from travel_metrics import rebuild_schedule_context  # noqa: E402


def run_daily(target_date: str, lookback_days: int = 3) -> None:
    """Run every pipeline stage needed to produce a full report for one date.

    :param target_date: Date to score and report on, as YYYY-MM-DD.
    :param lookback_days: How many days before target_date to also re-fetch,
        so games that finished in the last few days get their final score
        upserted even though they're no longer "today."
    """
    init_db()

    fetch_anchor = (date_cls.fromisoformat(target_date) - timedelta(days=lookback_days)).isoformat()
    print(f"== Fetching schedule from {fetch_anchor} through {target_date}'s game-week ==")
    fetch_range(fetch_anchor, target_date)

    print("== Grading completed picks ==")
    grade_all()

    print("== Updating performance record page ==")
    build_record_page()

    print("== Refreshing every past report (scores/grading/team ATS records) ==")
    for report_date in all_report_dates():
        if report_date != target_date:
            build_report(report_date)

    print("== Rebuilding travel/rest metrics ==")
    rebuild_schedule_context()

    print("== Rebuilding generic metric_values ==")
    rebuild_schedule_metrics()

    print("== Rebuilding recent form / goal differential ==")
    rebuild_form_metrics()

    if os.environ.get("ODDS_API_KEY"):
        print("== Fetching odds ==")
        fetch_and_store_odds()
    else:
        print("== Skipping odds fetch (ODDS_API_KEY not set) ==")

    print("== Rebuilding market_edge from odds on record ==")
    rebuild_market_metrics()

    print(f"== Scoring {target_date} ==")
    score_date(target_date)

    print(f"== Building report for {target_date} ==")
    build_report(target_date)

    print("== Updating policy page ==")
    build_policy_page()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the full daily NHL picks pipeline")
    parser.add_argument("--date", default=date_cls.today().isoformat(), help="YYYY-MM-DD")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=3,
        help="Days before --date to also re-fetch, to catch up recently-final scores",
    )
    args = parser.parse_args()
    run_daily(args.date, args.lookback_days)
