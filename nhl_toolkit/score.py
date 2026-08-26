"""
Config-driven scoring engine. Reads policy.yaml, normalizes each
metric's values across a day's slate of games, applies the configured
weights, and writes one weighted total_score row per (game, team) to
`daily_scores`. See nhl-betting-toolkit-design.md section 6.

Run this after metrics.py has populated metric_values for the target
date. Rescoring a date is idempotent -- it deletes and rewrites that
date+policy_version's daily_scores rows.

Usage:
    python score.py --date 2026-10-05
    python score.py                      # defaults to today
"""

import argparse
import sqlite3
from datetime import date as date_cls
from pathlib import Path
from statistics import mean, pstdev
from typing import Optional

import yaml
from db import get_connection, init_db

POLICY_PATH = Path(__file__).parent / "policy.yaml"


def load_policy(path: Path = POLICY_PATH) -> dict:
    """Load the policy config: a policy_version and a metrics -> {weight, normalize} map.

    :param path: Path to the policy YAML file.
    :returns: The parsed policy config.
    """
    with open(path) as f:
        return yaml.safe_load(f)


def sync_policy_weights(conn: sqlite3.Connection, policy: dict) -> str:
    """Write the policy's metric weights into policy_weights, replacing any prior version row.

    :param conn: Open connection to the schedule database.
    :param policy: Parsed policy config from :func:`load_policy`.
    :returns: The policy_version that was synced.
    :raises ValueError: If the policy references a metric name that doesn't exist yet.
    """
    policy_version = policy["policy_version"]
    metric_names = list(policy["metrics"].keys())
    placeholders = ",".join("?" * len(metric_names))
    rows = conn.execute(
        f"SELECT name, metric_id FROM metrics WHERE name IN ({placeholders})", metric_names
    ).fetchall()
    metric_ids = {name: metric_id for name, metric_id in rows}

    missing = set(metric_names) - set(metric_ids)
    if missing:
        raise ValueError(
            f"policy.yaml references unknown metrics: {sorted(missing)}. Run metrics.py first."
        )

    conn.execute("DELETE FROM policy_weights WHERE policy_version = ?", (policy_version,))
    conn.executemany(
        """
        INSERT INTO policy_weights (policy_version, metric_id, weight, normalize)
        VALUES (?, ?, ?, ?)
        """,
        [
            (policy_version, metric_ids[name], cfg["weight"], cfg["normalize"])
            for name, cfg in policy["metrics"].items()
        ],
    )
    return policy_version


def normalize_values(values: list, method: str) -> list:
    """Scale a batch of metric values so they combine fairly with other metrics.

    :param values: Raw values, one per (game, team); may contain None.
    :param method: One of 'minmax', 'zscore', 'linear', or 'none'.
    :returns: Scaled values in the same order, with None preserved for missing data.
    :raises ValueError: If method is not a recognized normalization scheme.
    """
    present = [v for v in values if v is not None]
    if not present:
        return [None] * len(values)

    if method in ("none", "linear"):
        return values

    if method == "minmax":
        lo, hi = min(present), max(present)
        span = hi - lo
        return [None if v is None else (0.5 if span == 0 else (v - lo) / span) for v in values]

    if method == "zscore":
        mu = mean(present)
        sigma = pstdev(present)
        return [None if v is None else (0.0 if sigma == 0 else (v - mu) / sigma) for v in values]

    raise ValueError(f"Unknown normalize method: {method}")


def compute_daily_scores(conn: sqlite3.Connection, target_date: str, policy: dict) -> int:
    """Score every team in every game on a date and write daily_scores rows.

    :param conn: Open connection to the schedule database.
    :param target_date: Date to score, as YYYY-MM-DD.
    :param policy: Parsed policy config from :func:`load_policy`.
    :returns: Number of (game, team) rows scored.
    """
    policy_version = sync_policy_weights(conn, policy)

    game_ids = [
        row[0]
        for row in conn.execute(
            "SELECT game_id FROM games WHERE game_date = ?", (target_date,)
        ).fetchall()
    ]
    if not game_ids:
        return 0
    game_placeholders = ",".join("?" * len(game_ids))

    weight_rows = conn.execute(
        """
        SELECT m.name, m.metric_id, pw.weight, pw.normalize
        FROM policy_weights pw JOIN metrics m ON m.metric_id = pw.metric_id
        WHERE pw.policy_version = ?
        """,
        (policy_version,),
    ).fetchall()

    team_rows = conn.execute(
        f"""
        SELECT DISTINCT game_id, team_id FROM metric_values
        WHERE game_id IN ({game_placeholders})
        """,
        game_ids,
    ).fetchall()
    if not team_rows:
        return 0
    scores = {key: 0.0 for key in team_rows}

    for _metric_name, metric_id, weight, normalize in weight_rows:
        value_rows = conn.execute(
            f"""
            SELECT game_id, team_id, value FROM metric_values
            WHERE metric_id = ? AND game_id IN ({game_placeholders})
            """,
            [metric_id, *game_ids],
        ).fetchall()
        keys = [(game_id, team_id) for game_id, team_id, _value in value_rows]
        raw_values = [value for _game_id, _team_id, value in value_rows]
        normalized = normalize_values(raw_values, normalize)
        for key, norm_value in zip(keys, normalized):
            if norm_value is not None:
                scores[key] += norm_value * weight

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)

    conn.execute(
        "DELETE FROM daily_scores WHERE date = ? AND policy_version = ?",
        (target_date, policy_version),
    )
    conn.executemany(
        """
        INSERT INTO daily_scores (date, game_id, team_id, total_score, rank, policy_version)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (target_date, game_id, team_id, score, rank, policy_version)
            for rank, ((game_id, team_id), score) in enumerate(ranked, start=1)
        ],
    )
    return len(ranked)


def score_date(target_date: str, policy_path: Optional[Path] = None) -> None:
    """Score all of a date's games against the configured policy and store the results.

    :param target_date: Date to score, as YYYY-MM-DD.
    :param policy_path: Optional override for the policy YAML file location.
    """
    init_db()
    conn = get_connection()
    with conn:
        policy = load_policy(policy_path or POLICY_PATH)
        written = compute_daily_scores(conn, target_date, policy)
    conn.close()
    print(f"Scored {written} team-rows for {target_date} using policy {policy['policy_version']}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score NHL games for a date using policy.yaml")
    parser.add_argument("--date", default=date_cls.today().isoformat(), help="YYYY-MM-DD")
    args = parser.parse_args()
    score_date(args.date)
