"""
Pulls the current league-wide NHL injury report from ESPN's public,
undocumented, no-API-key Site API and appends it to the `injuries` table.

Like fetch_odds.py, each run inserts a fresh snapshot rather than
upserting -- the whole league's injury list is small (~100-150 rows) and
changes daily, so re-running accumulates a time series (useful later for
"who was hurt on game day X" lookups) instead of trying to diff against
the previous run.

ESPN's own team abbreviations mostly match this project's (arenas.py),
but not always -- confirmed by fetching the live endpoint and diffing
every team's abbreviation against arenas.py, the same discipline that
already caught three real team-name mismatches elsewhere in this
project (Utah, Montreal, St. Louis). Four teams differ:
    LA -> LAK, NJ -> NJD, SJ -> SJS, TB -> TBL
Everything else is passed through unchanged.

Usage:
    python lib/fetch_injuries.py
"""

import re
import sqlite3
from datetime import datetime, timezone
from typing import Optional

import requests
from db import get_connection, init_db

ESPN_INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries"

ESPN_ABBREV_TO_NHL = {
    "LA": "LAK",
    "NJ": "NJD",
    "SJ": "SJS",
    "TB": "TBL",
}

_HEADSHOT_ID_RE = re.compile(r"/players/full/(\d+)")


def fetch_espn_injuries() -> dict:
    """Fetch the raw league-wide injury report from ESPN.

    :returns: The parsed JSON response (top-level key `injuries` is a list
        of per-team groups).
    """
    resp = requests.get(ESPN_INJURIES_URL, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _player_id(athlete: dict) -> Optional[str]:
    """Pull ESPN's numeric player id out of the headshot URL.

    ESPN doesn't expose a plain `id` field on the athlete object here --
    the only stable identifier available is embedded in the headshot
    image URL (.../players/full/{id}.png). A handful of entries have no
    headshot at all, in which case this returns None.

    :param athlete: The `athlete` object from one injury entry.
    :returns: The numeric id as a string, or None if no headshot URL exists.
    """
    href = athlete.get("headshot", {}).get("href", "")
    match = _HEADSHOT_ID_RE.search(href)
    return match.group(1) if match else None


def parse_injuries(payload: dict) -> list[tuple]:
    """Flatten ESPN's per-team injury report into `injuries` table rows.

    :param payload: The JSON from :func:`fetch_espn_injuries`.
    :returns: (team, player_name, position, status, body_part,
        espn_player_id, espn_injury_id, report_date) tuples.
    """
    rows = []
    for team_group in payload.get("injuries", []):
        for entry in team_group.get("injuries", []):
            athlete = entry.get("athlete", {})
            espn_abbrev = athlete.get("team", {}).get("abbreviation")
            team = ESPN_ABBREV_TO_NHL.get(espn_abbrev, espn_abbrev)
            rows.append(
                (
                    team,
                    athlete.get("displayName"),
                    athlete.get("position", {}).get("abbreviation"),
                    entry.get("status"),
                    entry.get("details", {}).get("type"),
                    _player_id(athlete),
                    entry.get("id"),
                    entry.get("date"),
                )
            )
    return rows


def insert_injuries(conn: sqlite3.Connection, rows: list[tuple]) -> int:
    """Insert one injury snapshot for every row, stamped with the same fetch time.

    :param conn: Open connection to the schedule database.
    :param rows: Rows as returned by :func:`parse_injuries`.
    :returns: Number of rows inserted.
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        """
        INSERT INTO injuries (fetched_at, team, player_name, position, status,
                               body_part, espn_player_id, espn_injury_id, report_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [(fetched_at, *row) for row in rows],
    )
    return len(rows)


def fetch_and_store_injuries() -> None:
    """Fetch the current league-wide injury report and store a snapshot."""
    init_db()
    conn = get_connection()
    with conn:
        payload = fetch_espn_injuries()
        rows = parse_injuries(payload)
        inserted = insert_injuries(conn, rows)
    conn.close()
    print(f"Inserted {inserted} injury rows from ESPN.")


if __name__ == "__main__":
    fetch_and_store_injuries()
