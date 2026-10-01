"""
Pulls schedule + score data from the NHL Web API and upserts it into
the `games` table.

The endpoint /v1/schedule/{date} returns a full "game week" (that
date plus the following ~6 days), so we only need to hit it roughly
once per week to stay current -- but calling it daily is cheap and
keeps scores/status fresh as games go final.

Usage:
    python lib/fetch_schedule.py --start 2026-10-01 --end 2026-10-31
    python lib/fetch_schedule.py                      # defaults to today's game week
"""

import argparse
import sqlite3
import time
from datetime import date, datetime, timedelta

import requests
from db import get_connection, init_db

BASE_URL = "https://api-web.nhle.com/v1/schedule"


def fetch_game_week(anchor_date: str) -> dict:
    """Fetch one game-week payload starting at anchor_date (YYYY-MM-DD)."""
    resp = requests.get(f"{BASE_URL}/{anchor_date}", timeout=15)
    resp.raise_for_status()
    return resp.json()


def upsert_games(conn: sqlite3.Connection, payload: dict) -> int:
    """Upsert every game in a game-week payload into the `games` table.

    :param conn: Open connection to the schedule database.
    :param payload: JSON payload from the NHL schedule API.
    :returns: Number of game rows upserted.
    """
    count = 0
    for day in payload.get("gameWeek", []):
        for game in day.get("games", []):
            venue = game.get("venue")
            row = (
                game["id"],
                day["date"],
                game.get("startTimeUTC"),
                game["homeTeam"]["abbrev"],
                game["awayTeam"]["abbrev"],
                game["homeTeam"].get("score"),
                game["awayTeam"].get("score"),
                game.get("gameState"),
                venue.get("default") if isinstance(venue, dict) else venue,
            )
            conn.execute(
                """
                INSERT INTO games (game_id, game_date, start_time_utc, home_team,
                                    away_team, home_score, away_score, game_state, venue)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id) DO UPDATE SET
                    home_score = excluded.home_score,
                    away_score = excluded.away_score,
                    game_state = excluded.game_state,
                    start_time_utc = excluded.start_time_utc
                """,
                row,
            )
            count += 1
    return count


def fetch_range(start: str, end: str) -> None:
    """
    Walk the date range one game-week at a time (the API returns ~7 days
    per call), so this stays efficient even for a full-month backfill.
    """
    init_db()
    conn = get_connection()

    start_d = datetime.strptime(start, "%Y-%m-%d").date()
    end_d = datetime.strptime(end, "%Y-%m-%d").date()

    cursor_d = start_d
    total = 0
    with conn:
        while cursor_d <= end_d:
            anchor = cursor_d.isoformat()
            print(f"Fetching game week starting {anchor} ...")
            payload = fetch_game_week(anchor)
            n = upsert_games(conn, payload)
            total += n
            print(f"  upserted {n} games")
            cursor_d += timedelta(days=7)
            time.sleep(0.5)  # be polite to the API

    conn.close()
    print(f"Done. {total} game rows upserted for {start} .. {end}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch NHL schedule/scores into SQLite")
    parser.add_argument("--start", default=date.today().isoformat(), help="YYYY-MM-DD")
    parser.add_argument(
        "--end",
        default=(date.today() + timedelta(days=6)).isoformat(),
        help="YYYY-MM-DD",
    )
    args = parser.parse_args()
    fetch_range(args.start, args.end)
