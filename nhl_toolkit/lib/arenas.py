"""
Static reference data: one row per current NHL team.
lat/lon are the team's home arena (city-level precision is fine for
travel-distance heuristics). timezone is the IANA zone name, used to
compute time-zone shifts between consecutive road games.

Keyed by the 3-letter abbreviation the NHL API uses in
game["homeTeam"]["abbrev"] / game["awayTeam"]["abbrev"].

NOTE: Arizona relocated and rebranded as Utah (UTA) starting the
2024-25 season. If you're pulling historical pre-2024 data you may
still see "ARI" in the feed -- it's aliased below to the same record
so lookups don't break.
"""

ARENAS = {
    "ANA": {
        "team": "Anaheim Ducks",
        "city": "Anaheim, CA",
        "lat": 33.8078,
        "lon": -117.8766,
        "tz": "America/Los_Angeles",
    },
    "UTA": {
        "team": "Utah Mammoth",
        "city": "Salt Lake City, UT",
        "lat": 40.7683,
        "lon": -111.9011,
        "tz": "America/Denver",
    },
    "BOS": {
        "team": "Boston Bruins",
        "city": "Boston, MA",
        "lat": 42.3662,
        "lon": -71.0621,
        "tz": "America/New_York",
    },
    "BUF": {
        "team": "Buffalo Sabres",
        "city": "Buffalo, NY",
        "lat": 42.8750,
        "lon": -78.8765,
        "tz": "America/New_York",
    },
    "CGY": {
        "team": "Calgary Flames",
        "city": "Calgary, AB",
        "lat": 51.0374,
        "lon": -114.0519,
        "tz": "America/Edmonton",
    },
    "CAR": {
        "team": "Carolina Hurricanes",
        "city": "Raleigh, NC",
        "lat": 35.8033,
        "lon": -78.7219,
        "tz": "America/New_York",
    },
    "CHI": {
        "team": "Chicago Blackhawks",
        "city": "Chicago, IL",
        "lat": 41.8807,
        "lon": -87.6742,
        "tz": "America/Chicago",
    },
    "COL": {
        "team": "Colorado Avalanche",
        "city": "Denver, CO",
        "lat": 39.7487,
        "lon": -105.0077,
        "tz": "America/Denver",
    },
    "CBJ": {
        "team": "Columbus Blue Jackets",
        "city": "Columbus, OH",
        "lat": 39.9692,
        "lon": -83.0061,
        "tz": "America/New_York",
    },
    "DAL": {
        "team": "Dallas Stars",
        "city": "Dallas, TX",
        "lat": 32.7905,
        "lon": -96.8103,
        "tz": "America/Chicago",
    },
    "DET": {
        "team": "Detroit Red Wings",
        "city": "Detroit, MI",
        "lat": 42.3411,
        "lon": -83.0553,
        "tz": "America/New_York",
    },
    "EDM": {
        "team": "Edmonton Oilers",
        "city": "Edmonton, AB",
        "lat": 53.5469,
        "lon": -113.4973,
        "tz": "America/Edmonton",
    },
    "FLA": {
        "team": "Florida Panthers",
        "city": "Sunrise, FL",
        "lat": 26.1584,
        "lon": -80.3255,
        "tz": "America/New_York",
    },
    "LAK": {
        "team": "Los Angeles Kings",
        "city": "Los Angeles, CA",
        "lat": 34.0430,
        "lon": -118.2673,
        "tz": "America/Los_Angeles",
    },
    "MIN": {
        "team": "Minnesota Wild",
        "city": "St. Paul, MN",
        "lat": 44.9447,
        "lon": -93.1011,
        "tz": "America/Chicago",
    },
    "MTL": {
        "team": "Montréal Canadiens",
        "city": "Montreal, QC",
        "lat": 45.4961,
        "lon": -73.5693,
        "tz": "America/Toronto",
    },
    "NSH": {
        "team": "Nashville Predators",
        "city": "Nashville, TN",
        "lat": 36.1593,
        "lon": -86.7785,
        "tz": "America/Chicago",
    },
    "NJD": {
        "team": "New Jersey Devils",
        "city": "Newark, NJ",
        "lat": 40.7336,
        "lon": -74.1711,
        "tz": "America/New_York",
    },
    "NYI": {
        "team": "New York Islanders",
        "city": "Elmont, NY",
        "lat": 40.7230,
        "lon": -73.5910,
        "tz": "America/New_York",
    },
    "NYR": {
        "team": "New York Rangers",
        "city": "New York, NY",
        "lat": 40.7505,
        "lon": -73.9934,
        "tz": "America/New_York",
    },
    "OTT": {
        "team": "Ottawa Senators",
        "city": "Ottawa, ON",
        "lat": 45.2969,
        "lon": -75.9269,
        "tz": "America/Toronto",
    },
    "PHI": {
        "team": "Philadelphia Flyers",
        "city": "Philadelphia, PA",
        "lat": 39.9012,
        "lon": -75.1720,
        "tz": "America/New_York",
    },
    "PIT": {
        "team": "Pittsburgh Penguins",
        "city": "Pittsburgh, PA",
        "lat": 40.4395,
        "lon": -79.9895,
        "tz": "America/New_York",
    },
    "SJS": {
        "team": "San Jose Sharks",
        "city": "San Jose, CA",
        "lat": 37.3327,
        "lon": -121.9012,
        "tz": "America/Los_Angeles",
    },
    "SEA": {
        "team": "Seattle Kraken",
        "city": "Seattle, WA",
        "lat": 47.6221,
        "lon": -122.3540,
        "tz": "America/Los_Angeles",
    },
    "STL": {
        "team": "St Louis Blues",
        "city": "St. Louis, MO",
        "lat": 38.6266,
        "lon": -90.2026,
        "tz": "America/Chicago",
    },
    "TBL": {
        "team": "Tampa Bay Lightning",
        "city": "Tampa, FL",
        "lat": 27.9427,
        "lon": -82.4518,
        "tz": "America/New_York",
    },
    "TOR": {
        "team": "Toronto Maple Leafs",
        "city": "Toronto, ON",
        "lat": 43.6435,
        "lon": -79.3791,
        "tz": "America/Toronto",
    },
    "VAN": {
        "team": "Vancouver Canucks",
        "city": "Vancouver, BC",
        "lat": 49.2778,
        "lon": -123.1088,
        "tz": "America/Vancouver",
    },
    "VGK": {
        "team": "Vegas Golden Knights",
        "city": "Las Vegas, NV",
        "lat": 36.1028,
        "lon": -115.1786,
        "tz": "America/Los_Angeles",
    },
    "WSH": {
        "team": "Washington Capitals",
        "city": "Washington, DC",
        "lat": 38.8981,
        "lon": -77.0209,
        "tz": "America/New_York",
    },
    "WPG": {
        "team": "Winnipeg Jets",
        "city": "Winnipeg, MB",
        "lat": 49.8927,
        "lon": -97.1435,
        "tz": "America/Winnipeg",
    },
}

# Pre-2024-25 alias: ARI feed rows should resolve to the same arena record.
ARENAS["ARI"] = ARENAS["UTA"]

# Full team name -> abbrev, for sources (e.g. odds feeds) that identify
# teams by name instead of the NHL API's 3-letter abbreviation. Built from
# ARENAS rather than hand-maintained separately so the two can't drift.
TEAM_NAME_TO_ABBREV = {
    record["team"]: abbrev for abbrev, record in ARENAS.items() if abbrev != "ARI"
}

# Utah's inaugural-season (2024-25) placeholder name, before "Utah Mammoth"
# became the permanent one -- kept as an alias in case any feed is still
# using it, same spirit as the ARI->UTA aliasing above.
TEAM_NAME_TO_ABBREV["Utah Hockey Club"] = "UTA"

# Unaccented fallback: The Odds API spells it "Montréal Canadiens" (the
# canonical form, used above), but some other feed or a copy-paste of this
# file elsewhere could plausibly drop the accent -- every Canadiens game
# silently got zero odds for the franchise's entire history here until this
# exact-match mismatch was caught by querying the live feed directly.
TEAM_NAME_TO_ABBREV["Montreal Canadiens"] = "MTL"

# Punctuated fallback: The Odds API spells it "St Louis Blues" (no period
# after "St", the canonical form used above), but "St. Louis Blues" is the
# more common/grammatically-standard spelling elsewhere -- every Blues game
# silently got zero odds for the franchise's entire history here until this
# exact-match mismatch was caught the same way the Utah/Montreal ones were:
# querying the live feed directly and diffing its team names against this
# file, rather than assuming the punctuated spelling here was correct.
TEAM_NAME_TO_ABBREV["St. Louis Blues"] = "STL"


def get_abbrev_for_team_name(team_name: str) -> str:
    """Look up a team's abbreviation by its full name, raising a clear error on typos.

    :param team_name: The team's full display name, e.g. "Boston Bruins".
    :returns: The team's 3-letter NHL API abbreviation.
    :raises KeyError: If the team name is not recognized.
    """
    try:
        return TEAM_NAME_TO_ABBREV[team_name]
    except KeyError as e:
        raise KeyError(
            f"Unknown team name '{team_name}'. Known names: {sorted(TEAM_NAME_TO_ABBREV.keys())}"
        ) from e


def get_arena(abbrev: str) -> dict[str, object]:
    """Look up arena info by team abbreviation, raising a clear error on typos.

    :param abbrev: The team's 3-letter NHL API abbreviation.
    :returns: The arena record for the team.
    :raises KeyError: If the abbreviation is not a known team.
    """
    try:
        return ARENAS[abbrev.upper()]
    except KeyError as e:
        raise KeyError(
            f"Unknown team abbreviation '{abbrev}'. Known abbrevs: {sorted(ARENAS.keys())}"
        ) from e
