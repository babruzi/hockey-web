"""
Pulls NHL odds (moneyline, puck line spread, totals) from The Odds API
and appends them to the `odds` table.

Each run inserts a new snapshot row per (game, bookmaker) rather than
upserting, so the table accumulates a time series of quotes -- useful
later for a "line movement" metric. Re-running frequently is fine and
expected; it's just more snapshots, not duplicates in the upsert sense.

Requires an API key from https://the-odds-api.com (free tier available)
set as the ODDS_API_KEY environment variable, e.g.:
    source .env  # if you stored it there as `export ODDS_API_KEY=...`
    python lib/fetch_odds.py

Usage:
    python lib/fetch_odds.py
"""

import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import requests
from arenas import get_abbrev_for_team_name, get_arena
from db import get_connection, init_db

BASE_URL = "https://api.the-odds-api.com/v4/sports/icehockey_nhl/odds/"


def fetch_events() -> list[dict]:
    """Fetch all upcoming NHL events with odds from The Odds API.

    :returns: List of event objects, each with nested bookmakers/markets.
    :raises RuntimeError: If ODDS_API_KEY is not set.
    """
    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ODDS_API_KEY is not set. Get a free key at https://the-odds-api.com "
            "and `export ODDS_API_KEY=...` (or `source .env`) before running this."
        )
    resp = requests.get(
        BASE_URL,
        params={
            "apiKey": api_key,
            "regions": "us",
            "markets": "h2h,spreads,totals",
            "oddsFormat": "american",
        },
        timeout=15,
    )
    resp.raise_for_status()
    remaining = resp.headers.get("x-requests-remaining")
    if remaining is not None:
        print(f"The Odds API requests remaining this period: {remaining}")
    return resp.json()


def find_game_id(
    conn: sqlite3.Connection, home_abbrev: str, away_abbrev: str, commence_time: str
) -> Optional[int]:
    """Match an odds-feed event to a row in `games` by matchup and local date.

    :param conn: Open connection to the schedule database.
    :param home_abbrev: Home team's 3-letter abbreviation.
    :param away_abbrev: Away team's 3-letter abbreviation.
    :param commence_time: Event start time as an ISO 8601 UTC string.
    :returns: The matching game_id, or None if no game is found.
    """
    utc_start = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
    local_start = utc_start.astimezone(ZoneInfo(get_arena(home_abbrev)["tz"]))
    local_date = local_start.date().isoformat()

    row = conn.execute(
        """
        SELECT game_id FROM games
        WHERE home_team = ? AND away_team = ? AND game_date = ?
        """,
        (home_abbrev, away_abbrev, local_date),
    ).fetchone()
    return row[0] if row else None


def extract_quote(bookmaker: dict, home_team_name: str, away_team_name: str) -> dict[str, object]:
    """Pull spread/moneyline/total values for one bookmaker out of its markets.

    :param bookmaker: A single bookmaker object from the odds API response.
    :param home_team_name: The home team's full display name, to match outcomes.
    :param away_team_name: The away team's full display name, to match outcomes.
    :returns: Flat dict of home_spread/away_spread/home_spread_price/away_spread_price/
        home_ml/away_ml/total/over_odds/under_odds.
    """
    quote: dict[str, object] = {
        "home_spread": None,
        "away_spread": None,
        "home_spread_price": None,
        "away_spread_price": None,
        "home_ml": None,
        "away_ml": None,
        "total": None,
        "over_odds": None,
        "under_odds": None,
    }
    for market in bookmaker.get("markets", []):
        outcomes = market.get("outcomes", [])
        if market["key"] == "h2h":
            for outcome in outcomes:
                if outcome["name"] == home_team_name:
                    quote["home_ml"] = outcome["price"]
                elif outcome["name"] == away_team_name:
                    quote["away_ml"] = outcome["price"]
        elif market["key"] == "spreads":
            for outcome in outcomes:
                if outcome["name"] == home_team_name:
                    quote["home_spread"] = outcome["point"]
                    quote["home_spread_price"] = outcome["price"]
                elif outcome["name"] == away_team_name:
                    quote["away_spread"] = outcome["point"]
                    quote["away_spread_price"] = outcome["price"]
        elif market["key"] == "totals":
            for outcome in outcomes:
                if outcome["name"] == "Over":
                    quote["total"] = outcome["point"]
                    quote["over_odds"] = outcome["price"]
                elif outcome["name"] == "Under":
                    quote["under_odds"] = outcome["price"]
    return quote


def upsert_odds(conn: sqlite3.Connection, events: list[dict]) -> tuple[int, int]:
    """Insert one odds snapshot row per (matched game, bookmaker).

    :param conn: Open connection to the schedule database.
    :param events: Events as returned by :func:`fetch_events`.
    :returns: (rows inserted, events skipped for lack of a matching game).
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    inserted = 0
    skipped = 0

    for event in events:
        try:
            home_abbrev = get_abbrev_for_team_name(event["home_team"])
            away_abbrev = get_abbrev_for_team_name(event["away_team"])
        except KeyError:
            skipped += 1
            continue

        game_id = find_game_id(conn, home_abbrev, away_abbrev, event["commence_time"])
        if game_id is None:
            skipped += 1
            continue

        for bookmaker in event.get("bookmakers", []):
            quote = extract_quote(bookmaker, event["home_team"], event["away_team"])
            conn.execute(
                """
                INSERT INTO odds (game_id, source, fetched_at, home_spread, away_spread,
                                   home_spread_price, away_spread_price,
                                   home_ml, away_ml, total, over_odds, under_odds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game_id,
                    bookmaker["key"],
                    fetched_at,
                    quote["home_spread"],
                    quote["away_spread"],
                    quote["home_spread_price"],
                    quote["away_spread_price"],
                    quote["home_ml"],
                    quote["away_ml"],
                    quote["total"],
                    quote["over_odds"],
                    quote["under_odds"],
                ),
            )
            inserted += 1

    return inserted, skipped


def fetch_and_store_odds() -> None:
    """Fetch current NHL odds and store a snapshot for every matched game."""
    init_db()
    conn = get_connection()
    with conn:
        events = fetch_events()
        print(f"Fetched odds for {len(events)} events.")
        inserted, skipped = upsert_odds(conn, events)
        print(f"Inserted {inserted} odds rows; skipped {skipped} events with no matching game.")
    conn.close()


if __name__ == "__main__":
    fetch_and_store_odds()
