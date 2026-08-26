"""
Runs the full Phase 1 + Phase 2 pipeline for one date: fetches the
schedule (including a trailing lookback window to pick up final scores
for recently-completed games), rebuilds travel metrics and the generic
metrics schema, pulls current odds, scores the slate, and builds the
Top-N report (CSV + HTML + picks_log).

Every step is cheap and idempotent (upsert or full-rebuild-on-run), so
running the whole chain is simpler and safer than trying to detect
which steps are "already done" -- there's no meaningful cost to redoing
them. This is meant to run once a day (e.g. via cron): the `games`
table only ever grows, `schedule_context`/`metric_values` are rebuilt
from all of it each run, and `odds` only appends -- nothing here ever
resets the database, so historical data accumulates across the season
as long as you keep running it. Odds are optional: if ODDS_API_KEY
isn't set, that step is skipped with a warning and the rest of the
pipeline still runs (picks just won't have a spread).

Usage:
    python run_daily.py --date 2026-10-05
    python run_daily.py                      # defaults to today
"""

import argparse
import os
from datetime import date as date_cls
from datetime import timedelta

from db import init_db
from fetch_odds import fetch_and_store_odds
from fetch_schedule import fetch_range
from form_metrics import rebuild_form_metrics
from metrics import rebuild_schedule_metrics
from policy_page import build_policy_page
from report import build_report
from score import score_date
from travel_metrics import rebuild_schedule_context


def run_daily(target_date: str, top_n: int = 10, lookback_days: int = 3) -> None:
    """Run every pipeline stage needed to produce a Top-N report for one date.

    :param target_date: Date to score and report on, as YYYY-MM-DD.
    :param top_n: How many top-edge picks to include in the report.
    :param lookback_days: How many days before target_date to also re-fetch,
        so games that finished in the last few days get their final score
        upserted even though they're no longer "today."
    """
    init_db()

    fetch_anchor = (date_cls.fromisoformat(target_date) - timedelta(days=lookback_days)).isoformat()
    print(f"== Fetching schedule from {fetch_anchor} through {target_date}'s game-week ==")
    fetch_range(fetch_anchor, target_date)

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
        print("== Skipping odds (ODDS_API_KEY not set) ==")

    print(f"== Scoring {target_date} ==")
    score_date(target_date)

    print(f"== Building report for {target_date} ==")
    build_report(target_date, top_n)

    print("== Updating policy page ==")
    build_policy_page()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the full daily NHL picks pipeline")
    parser.add_argument("--date", default=date_cls.today().isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--top", type=int, default=10, help="Number of picks to include")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=3,
        help="Days before --date to also re-fetch, to catch up recently-final scores",
    )
    args = parser.parse_args()
    run_daily(args.date, args.top, args.lookback_days)
