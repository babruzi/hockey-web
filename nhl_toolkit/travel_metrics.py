"""
Derives the "context" metrics that don't come straight from the API:
rest days, games played in the trailing 7/14/30 days, distance
traveled since the previous game, time zones crossed, and a
back-to-back flag.

Run this after fetch_schedule.py has populated `games`. It rebuilds
`schedule_context` from scratch each run (idempotent, cheap for a
single season's worth of games).

Usage:
    python travel_metrics.py
"""

import sqlite3
from datetime import datetime, timedelta
from math import atan2, cos, radians, sin, sqrt
from zoneinfo import ZoneInfo

from arenas import get_arena
from db import get_connection

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute great-circle distance between two lat/lon points, in kilometers.

    :param lat1: Latitude of the first point, in degrees.
    :param lon1: Longitude of the first point, in degrees.
    :param lat2: Latitude of the second point, in degrees.
    :param lon2: Longitude of the second point, in degrees.
    :returns: Distance between the two points in kilometers.
    """
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * atan2(sqrt(a), sqrt(1 - a))


def count_games_within(played_dates: list[datetime], before: datetime, days: int) -> int:
    """Count games played in the trailing window before a given date.

    :param played_dates: Dates the team has already played, chronologically.
    :param before: The cutoff date; only games strictly earlier count.
    :param days: Size of the trailing window, in days.
    :returns: Number of games played within the window.
    """
    cutoff = before - timedelta(days=days)
    return sum(1 for played in played_dates if cutoff <= played < before)


def utc_offset_hours(tz_name: str, on_date: datetime) -> float:
    """UTC offset (in hours) for a zone on a given date, DST-aware."""
    offset = on_date.replace(tzinfo=ZoneInfo(tz_name)).utcoffset()
    return offset.total_seconds() / 3600.0


def load_team_games(conn: sqlite3.Connection, team_abbrev: str) -> list[tuple]:
    """All games (home or away) for a team, chronologically, with the
    venue city treated as wherever the *home* team plays.

    :param conn: Open connection to the schedule database.
    :param team_abbrev: The team's 3-letter NHL API abbreviation.
    :returns: Rows of (game_id, game_date, home_team, away_team, game_state).
    """
    rows = conn.execute(
        """
        SELECT game_id, game_date, home_team, away_team, game_state
        FROM games
        WHERE (home_team = ? OR away_team = ?) AND game_date IS NOT NULL
        ORDER BY game_date ASC, game_id ASC
        """,
        (team_abbrev, team_abbrev),
    ).fetchall()
    return rows


def all_team_abbrevs(conn: sqlite3.Connection) -> list[str]:
    """List every team abbreviation that appears in the `games` table.

    :param conn: Open connection to the schedule database.
    :returns: Sorted team abbreviations.
    """
    rows = conn.execute(
        "SELECT DISTINCT home_team FROM games UNION SELECT DISTINCT away_team FROM games"
    ).fetchall()
    return sorted(r[0] for r in rows)


def compute_for_team(conn: sqlite3.Connection, team_abbrev: str) -> list[tuple]:
    """Derive schedule_context rows for every game a team has played.

    :param conn: Open connection to the schedule database.
    :param team_abbrev: The team's 3-letter NHL API abbreviation.
    :returns: One schedule_context row tuple per game, chronologically.
    """
    games = load_team_games(conn, team_abbrev)
    if not games:
        return []

    results = []
    # Rolling history of this team's own game dates, for the windowed counts.
    played_dates = []
    prev_venue_team = None  # abbrev of whoever hosted the previous game
    prev_date = None

    for game_id, game_date_str, home_team, away_team, game_state in games:
        game_date = datetime.strptime(game_date_str, "%Y-%m-%d")
        is_home = 1 if home_team == team_abbrev else 0
        venue_team = home_team  # the venue is always the home team's arena

        # --- rest days & back-to-back ---
        if prev_date is not None:
            rest_days = (game_date - prev_date).days
        else:
            rest_days = None
        back_to_back = 1 if rest_days is not None and rest_days <= 1 else 0

        # --- windowed game counts (games played strictly before this one) ---
        games_last_7 = count_games_within(played_dates, game_date, 7)
        games_last_14 = count_games_within(played_dates, game_date, 14)
        games_last_30 = count_games_within(played_dates, game_date, 30)

        # --- distance traveled & timezone shift since previous venue ---
        if prev_venue_team is not None:
            prev_arena = get_arena(prev_venue_team)
            cur_arena = get_arena(venue_team)
            distance_km = haversine_km(
                prev_arena["lat"], prev_arena["lon"], cur_arena["lat"], cur_arena["lon"]
            )
            tz_shift = abs(
                utc_offset_hours(cur_arena["tz"], game_date)
                - utc_offset_hours(prev_arena["tz"], game_date)
            )
        else:
            distance_km = None
            tz_shift = None

        results.append(
            (
                game_id,
                team_abbrev,
                is_home,
                rest_days,
                games_last_7,
                games_last_14,
                games_last_30,
                distance_km,
                tz_shift,
                back_to_back,
            )
        )

        # advance rolling state
        played_dates.append(game_date)
        prev_venue_team = venue_team
        prev_date = game_date

    return results


def rebuild_schedule_context() -> None:
    """Delete and recompute `schedule_context` from scratch for every team."""
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM schedule_context")
        teams = all_team_abbrevs(conn)
        total = 0
        for team in teams:
            rows = compute_for_team(conn, team)
            conn.executemany(
                """
                INSERT INTO schedule_context (
                    game_id, team_id, is_home, rest_days, games_last_7,
                    games_last_14, games_last_30, distance_traveled_km,
                    timezones_crossed, back_to_back
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            total += len(rows)
            print(f"  {team}: {len(rows)} game rows")
    conn.close()
    print(f"Rebuilt schedule_context: {total} rows across {len(teams)} teams.")


if __name__ == "__main__":
    rebuild_schedule_context()
